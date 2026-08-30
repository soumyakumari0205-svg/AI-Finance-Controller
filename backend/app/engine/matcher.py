"""
Reconciliation Engine — Real fuzzy matching between bank, ERP, and gateway records.

NO Math.random() anywhere. Every confidence score traces back to actual field comparisons.

Algorithm:
  Pass 1 — Exact match: same amount (±0.01), date within DATE_WINDOW_DAYS, reference overlap
            → confidence 95–100%, status "matched"
  Pass 2 — Fuzzy match: weighted composite of amount proximity, date proximity, description similarity
            using rapidfuzz.fuzz.token_set_ratio
            score ≥ FUZZY_THRESHOLD → confidence 70–94%, status "review"
  Remainder → status "exception", with human-readable match_reason
  Duplicate guard → if two candidates both score ≥ DUPLICATE_TIE_THRESHOLD against one source row
                    → status "exception", match_reason explains both candidates

Every reconciliation result is written atomically with an audit_log row.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple

from rapidfuzz import fuzz
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AuditLog, BankTransaction, ErpInvoice, GatewaySettlement,
    ReconciliationMatch, Exception_, ExceptionPriority, ExceptionStatus,
    MatchStatus, MatchedBy,
)

settings = get_settings()


# ─── Data containers ─────────────────────────────────────────────────────────

@dataclass
class SourceRecord:
    """Normalised view of any source record (bank / erp / gateway)."""
    id: uuid.UUID
    source_type: str          # "bank" | "erp" | "gateway"
    amount: Decimal
    currency: str
    date: date
    description: str          # vendor / description / invoice number for fuzzy matching
    external_ref: str         # reference number / settlement_id / invoice_number
    vendor: Optional[str] = None


@dataclass
class MatchResult:
    source_a: SourceRecord
    source_b: SourceRecord
    confidence: float         # 0.0 – 1.0
    status: MatchStatus
    match_reason: str


# ─── Score helpers ───────────────────────────────────────────────────────────

def _amount_score(a: Decimal, b: Decimal) -> float:
    """
    Proximity of two amounts.
    Returns 1.0 for identical, approaching 0.0 as they diverge.
    """
    if a == 0 and b == 0:
        return 1.0
    denom = max(abs(float(a)), abs(float(b)))
    if denom == 0:
        return 0.0
    diff = abs(float(a) - float(b))
    return max(0.0, 1.0 - diff / denom)


def _date_score(d1: date, d2: date, window: int) -> float:
    """
    How close two dates are within the allowed window.
    Returns 1.0 if same day, 0.0 at or beyond window days.
    """
    days_diff = abs((d1 - d2).days)
    if days_diff == 0:
        return 1.0
    if days_diff >= window:
        return 0.0
    return 1.0 - (days_diff / window)


def _ref_overlap(ref_a: str, ref_b: str) -> bool:
    """Returns True if at least one meaningful token from ref_a appears in ref_b or vice-versa."""
    if not ref_a or not ref_b:
        return False
    import re
    tokens_a = set(t for t in re.split(r'[^A-Z0-9]+', ref_a.upper()) if len(t) >= 2)
    tokens_b = set(t for t in re.split(r'[^A-Z0-9]+', ref_b.upper()) if len(t) >= 2)
    return bool(tokens_a & tokens_b)


def _composite_score(a: SourceRecord, b: SourceRecord, window: int) -> float:
    """
    Weighted composite score for fuzzy pass.
      amount_score  × 0.40
      date_score    × 0.30
      desc_score    × 0.30  (rapidfuzz token_set_ratio)
    """
    amt = _amount_score(a.amount, b.amount)
    dt = _date_score(a.date, b.date, window)
    desc_a = f"{a.description or ''} {a.vendor or ''} {a.external_ref or ''}"
    desc_b = f"{b.description or ''} {b.vendor or ''} {b.external_ref or ''}"
    desc = fuzz.token_set_ratio(desc_a, desc_b) / 100.0
    return amt * 0.40 + dt * 0.30 + desc * 0.30


def _confidence_from_score(score: float, is_exact: bool) -> float:
    """Map composite score (0–1) to a confidence percentage (0–100)."""
    if is_exact:
        # Scale exact matches to 95–100%
        return round(95.0 + score * 5.0, 2)
    # Scale fuzzy matches to 70–94%
    return round(70.0 + score * 24.0, 2)


# ─── Core matching logic ──────────────────────────────────────────────────────

def _match_pairs(
    sources_a: List[SourceRecord],
    sources_b: List[SourceRecord],
    window: int,
    fuzzy_threshold: float,
    tie_threshold: float,
) -> List[MatchResult]:
    """
    Attempt to match each record in sources_a against all records in sources_b.
    Returns a list of MatchResult (one per matched/reviewed/excepted pair from sources_a).
    """
    used_b: set[uuid.UUID] = set()
    results: List[MatchResult] = []

    for a in sources_a:
        exact_candidates: List[Tuple[float, SourceRecord]] = []
        fuzzy_candidates: List[Tuple[float, SourceRecord]] = []

        for b in sources_b:
            if b.id in used_b:
                continue
            if a.currency != b.currency:
                continue

            days_diff = abs((a.date - b.date).days)
            amount_close = abs(float(a.amount) - float(b.amount)) <= 0.01
            date_in_window = days_diff <= window

            # ── Exact pass ──
            if amount_close and date_in_window and _ref_overlap(a.external_ref, b.external_ref):
                score = _composite_score(a, b, window)
                exact_candidates.append((score, b))
                continue

            # ── Fuzzy pass ──
            if date_in_window:
                score = _composite_score(a, b, window)
                if score >= fuzzy_threshold:
                    fuzzy_candidates.append((score, b))

        # ── Decide outcome ──────────────────────────────────────────────────
        if exact_candidates:
            # Duplicate guard: two exact candidates both above tie_threshold → exception
            above_tie = [(s, c) for s, c in exact_candidates if s >= tie_threshold]
            if len(above_tie) >= 2:
                above_tie.sort(key=lambda x: x[0], reverse=True)
                reason = (
                    f"Duplicate risk: two records ({above_tie[0][1].external_ref}, "
                    f"{above_tie[1][1].external_ref}) both matched {a.external_ref} "
                    f"with scores {above_tie[0][0]:.2f} and {above_tie[1][0]:.2f}"
                )
                results.append(MatchResult(a, above_tie[0][1], above_tie[0][0], MatchStatus.exception, reason))
            else:
                exact_candidates.sort(key=lambda x: x[0], reverse=True)
                best_score, best_b = exact_candidates[0]
                conf = _confidence_from_score(best_score, is_exact=True)
                reason = (
                    f"Exact match: amount match (±0.01), date within {window} days, "
                    f"reference overlap ({a.external_ref} ↔ {best_b.external_ref})"
                )
                results.append(MatchResult(a, best_b, conf, MatchStatus.matched, reason))
                used_b.add(best_b.id)

        elif fuzzy_candidates:
            # Duplicate guard for fuzzy
            above_tie = [(s, c) for s, c in fuzzy_candidates if s >= tie_threshold]
            if len(above_tie) >= 2:
                above_tie.sort(key=lambda x: x[0], reverse=True)
                reason = (
                    f"Duplicate risk: two fuzzy candidates ({above_tie[0][1].external_ref}, "
                    f"{above_tie[1][1].external_ref}) both matched {a.external_ref}"
                )
                results.append(MatchResult(a, above_tie[0][1], above_tie[0][0], MatchStatus.exception, reason))
            else:
                fuzzy_candidates.sort(key=lambda x: x[0], reverse=True)
                best_score, best_b = fuzzy_candidates[0]
                conf = _confidence_from_score(best_score, is_exact=False)
                score_breakdown = (
                    f"amount_score={_amount_score(a.amount, best_b.amount):.2f}, "
                    f"date_score={_date_score(a.date, best_b.date, window):.2f}, "
                    f"desc_similarity={fuzz.token_set_ratio(a.description or '', best_b.description or '')}%"
                )
                reason = f"Fuzzy match (composite={best_score:.2f}): {score_breakdown}"
                results.append(MatchResult(a, best_b, conf, MatchStatus.review, reason))
                used_b.add(best_b.id)

        else:
            # No match found in any pass
            reason = (
                f"No {sources_b[0].source_type if sources_b else 'counterpart'} record found "
                f"within ±{window} days and acceptable amount/description similarity for {a.external_ref}"
            )
            # Create a placeholder SourceRecord representing "unmatched"
            dummy = SourceRecord(
                id=uuid.uuid4(),
                source_type="none",
                amount=Decimal("0"),
                currency=a.currency,
                date=a.date,
                description="Unmatched",
                external_ref="N/A",
            )
            results.append(MatchResult(a, dummy, 0.0, MatchStatus.exception, reason))

    return results


# ─── DB helpers ──────────────────────────────────────────────────────────────

def _to_source(obj, source_type: str) -> SourceRecord:
    """Convert an ORM row to a normalised SourceRecord."""
    if source_type == "bank":
        return SourceRecord(
            id=obj.id,
            source_type="bank",
            amount=obj.amount,
            currency=obj.currency,
            date=obj.date,
            description=obj.description or "",
            external_ref=obj.external_ref,
        )
    if source_type == "erp":
        return SourceRecord(
            id=obj.id,
            source_type="erp",
            amount=obj.amount,
            currency=obj.currency,
            date=obj.due_date,
            description=obj.vendor or "",
            external_ref=obj.invoice_number,
            vendor=obj.vendor,
        )
    if source_type == "gateway":
        return SourceRecord(
            id=obj.id,
            source_type="gateway",
            amount=obj.amount,
            currency=obj.currency,
            date=obj.date,
            description=obj.vendor or obj.gateway_name or "",
            external_ref=obj.settlement_id,
            vendor=obj.vendor,
        )
    raise ValueError(f"Unknown source_type: {source_type}")


async def _write_match(
    db: AsyncSession,
    result: MatchResult,
    actor: str = "ai",
) -> ReconciliationMatch:
    """Persist one match result + audit log entry atomically."""
    # Only write source_b_id if it's a real record (not our dummy unmatched placeholder)
    source_b_id = result.source_b.id if result.status != MatchStatus.exception or result.source_b.source_type != "none" else None

    match = ReconciliationMatch(
        source_a_type=result.source_a.source_type,
        source_a_id=result.source_a.id,
        source_b_type=result.source_b.source_type,
        source_b_id=source_b_id if source_b_id else result.source_a.id,  # self-ref for unmatched
        confidence_score=Decimal(str(round(result.confidence, 2))),
        match_reason=result.match_reason,
        status=result.status,
        matched_by=MatchedBy.ai,
    )
    db.add(match)
    await db.flush()  # get match.id before audit log

    # Atomic audit log entry
    audit = AuditLog(
        actor=actor,
        action=f"reconcile:{result.status.value}",
        entity_type="reconciliation_match",
        entity_id=str(match.id),
        detail={
            "source_a": str(result.source_a.id),
            "source_b": str(result.source_b.id),
            "confidence": float(result.confidence),
            "reason": result.match_reason,
        },
    )
    db.add(audit)
    return match


async def _write_exception(
    db: AsyncSession,
    match: ReconciliationMatch,
    source_record: SourceRecord,
    reason: str,
) -> Exception_:
    """Create an exception record for an unmatched or problematic pair."""
    # Determine priority from confidence and reason
    conf = float(match.confidence_score)
    if conf == 0 or "no" in reason.lower():
        priority = ExceptionPriority.critical
    elif "duplicate" in reason.lower():
        priority = ExceptionPriority.high
    elif conf < 0.75:
        priority = ExceptionPriority.medium
    else:
        priority = ExceptionPriority.low

    exc = Exception_(
        match_id=match.id,
        title=f"{source_record.source_type.upper()} record {source_record.external_ref} — {reason[:80]}",
        description=reason,
        exposure_amount=source_record.amount,
        exposure_currency=source_record.currency,
        priority=priority,
        status=ExceptionStatus.open,
    )
    db.add(exc)
    await db.flush()

    audit = AuditLog(
        actor="ai",
        action="exception:created",
        entity_type="exception",
        entity_id=str(exc.id),
        detail={
            "match_id": str(match.id),
            "priority": priority.value,
            "exposure": float(source_record.amount),
            "reason": reason,
        },
    )
    db.add(audit)
    return exc


# ─── Public entry point ───────────────────────────────────────────────────────

async def run_reconciliation(db: AsyncSession) -> dict:
    """
    Main reconciliation pass. Reads all source tables, matches bank → erp and
    bank → gateway, persists results, then returns a run summary dict.
    """
    window = settings.date_window_days
    fuzzy_thresh = settings.fuzzy_threshold
    tie_thresh = settings.duplicate_tie_threshold

    # Load all source records
    banks = (await db.execute(select(BankTransaction))).scalars().all()
    erps = (await db.execute(select(ErpInvoice))).scalars().all()
    gateways = (await db.execute(select(GatewaySettlement))).scalars().all()

    bank_srcs = [_to_source(b, "bank") for b in banks]
    erp_srcs = [_to_source(e, "erp") for e in erps]
    gw_srcs = [_to_source(g, "gateway") for g in gateways]

    # Clear previous AI matches (keep human-overridden ones)
    from sqlalchemy import delete
    await db.execute(
        delete(ReconciliationMatch).where(ReconciliationMatch.matched_by == MatchedBy.ai)
    )
    await db.flush()

    # Clear previous open exceptions before regenerating them this run — otherwise
    # every reconciliation run (manual or scheduled) permanently stacks new exception
    # rows on top of old ones for the same underlying unresolved records. Approved/
    # rejected exceptions (status != open) are a human decision and audit trail, so
    # they're preserved.
    await db.execute(
        delete(Exception_).where(Exception_.status == ExceptionStatus.open)
    )
    await db.flush()

    all_results: List[MatchResult] = []

    # Bank → ERP matching
    if bank_srcs and erp_srcs:
        all_results.extend(_match_pairs(bank_srcs, erp_srcs, window, fuzzy_thresh, tie_thresh))

    # Bank → Gateway matching (for unmatched bank records after ERP pass)
    matched_bank_ids = {r.source_a.id for r in all_results if r.status == MatchStatus.matched}
    unmatched_banks = [s for s in bank_srcs if s.id not in matched_bank_ids]
    if unmatched_banks and gw_srcs:
        all_results.extend(_match_pairs(unmatched_banks, gw_srcs, window, fuzzy_thresh, tie_thresh))

    # Persist all results
    matched_count = 0
    review_count = 0
    exception_count = 0

    for result in all_results:
        match = await _write_match(db, result)
        if result.status == MatchStatus.matched:
            matched_count += 1
        elif result.status == MatchStatus.review:
            review_count += 1
        else:
            exception_count += 1
            await _write_exception(db, match, result.source_a, result.match_reason)

    total = len(all_results)
    match_rate = matched_count / total if total > 0 else 0.0

    return {
        "total_processed": total,
        "matched": matched_count,
        "review": review_count,
        "exceptions": exception_count,
        "match_rate": round(match_rate, 4),
        "bank_count": len(banks),
        "erp_count": len(erps),
        "gateway_count": len(gateways),
    }
