"""
Unit tests for the reconciliation matching engine.
Uses known input pairs and asserts exact expected confidence/status.
No database required — tests the pure matching logic directly.
"""
import pytest
import uuid
from datetime import date
from decimal import Decimal

from app.engine.matcher import (
    SourceRecord,
    _amount_score,
    _date_score,
    _composite_score,
    _confidence_from_score,
    _match_pairs,
    MatchStatus,
)

# ─── Helper ───────────────────────────────────────────────────────────────────

def make_record(
    amount: float,
    date_: date,
    ref: str = "REF-001",
    desc: str = "Stripe Payment",
    source_type: str = "bank",
    currency: str = "INR",
) -> SourceRecord:
    return SourceRecord(
        id=uuid.uuid4(),
        source_type=source_type,
        amount=Decimal(str(amount)),
        currency=currency,
        date=date_,
        description=desc,
        external_ref=ref,
    )


# ─── Amount score tests ───────────────────────────────────────────────────────

def test_amount_score_identical():
    """Identical amounts → score 1.0."""
    assert _amount_score(Decimal("1000.00"), Decimal("1000.00")) == 1.0


def test_amount_score_close():
    """Amounts within 1% should have high score."""
    score = _amount_score(Decimal("10000.00"), Decimal("10050.00"))
    assert score > 0.99


def test_amount_score_far():
    """Very different amounts → low score."""
    score = _amount_score(Decimal("1000.00"), Decimal("50000.00"))
    assert score < 0.10


def test_amount_score_zero():
    """Both zero → 1.0."""
    assert _amount_score(Decimal("0"), Decimal("0")) == 1.0


# ─── Date score tests ─────────────────────────────────────────────────────────

def test_date_score_same_day():
    d = date(2026, 8, 1)
    assert _date_score(d, d, window=3) == 1.0


def test_date_score_within_window():
    d1 = date(2026, 8, 1)
    d2 = date(2026, 8, 3)
    score = _date_score(d1, d2, window=3)
    assert 0.0 < score < 1.0


def test_date_score_at_window_edge():
    d1 = date(2026, 8, 1)
    d2 = date(2026, 8, 4)  # exactly window days away
    score = _date_score(d1, d2, window=3)
    assert score == 0.0


def test_date_score_beyond_window():
    d1 = date(2026, 8, 1)
    d2 = date(2026, 8, 10)
    assert _date_score(d1, d2, window=3) == 0.0


# ─── Exact match tests ────────────────────────────────────────────────────────

def test_exact_match_produces_matched_status():
    """Same amount, same ref token, date within window → status matched, confidence >= 95."""
    d = date(2026, 8, 15)
    bank = make_record(42850.0, d, ref="TXN-9821")
    erp = make_record(42850.0, d, ref="TXN-9821", source_type="erp")

    results = _match_pairs([bank], [erp], window=3, fuzzy_threshold=0.70, tie_threshold=0.80)

    assert len(results) == 1
    assert results[0].status == MatchStatus.matched
    assert results[0].confidence >= 95.0


def test_exact_match_small_amount_diff_within_tolerance():
    """Amounts differ by 0.005 (within 0.01 tolerance) → still matched."""
    d = date(2026, 8, 15)
    bank = make_record(1000.005, d, ref="INV-100")
    erp = make_record(1000.00, d, ref="INV-100", source_type="erp")

    results = _match_pairs([bank], [erp], window=3, fuzzy_threshold=0.70, tie_threshold=0.80)
    assert results[0].status == MatchStatus.matched


# ─── Fuzzy match tests ────────────────────────────────────────────────────────

def test_fuzzy_match_slight_amount_variance():
    """Amounts differ by 2%, date within window, same vendor → review status, confidence 70–94."""
    d = date(2026, 8, 15)
    bank = make_record(10000.0, d, ref="TXN-X", desc="Stripe payment")
    erp = make_record(10200.0, d + __import__('datetime').timedelta(days=1),
                      ref="INV-X", desc="Stripe invoice", source_type="erp")

    results = _match_pairs([bank], [erp], window=3, fuzzy_threshold=0.70, tie_threshold=0.80)
    assert len(results) == 1
    assert results[0].status == MatchStatus.review
    assert 70.0 <= results[0].confidence <= 94.0


def test_fuzzy_no_match_different_currency():
    """Different currencies → no match → exception."""
    d = date(2026, 8, 15)
    bank = make_record(1000.0, d, ref="T1", currency="INR")
    erp = make_record(1000.0, d, ref="T1", source_type="erp", currency="USD")

    results = _match_pairs([bank], [erp], window=3, fuzzy_threshold=0.70, tie_threshold=0.80)
    assert results[0].status == MatchStatus.exception


# ─── Exception tests ─────────────────────────────────────────────────────────

def test_no_match_produces_exception():
    """Bank record with no ERP counterpart → exception status."""
    d = date(2026, 8, 15)
    bank = make_record(99999.0, d, ref="UNIQUE-ORPHAN")
    erp = make_record(100.0, d, ref="COMPLETELY-DIFFERENT", source_type="erp")

    results = _match_pairs([bank], [erp], window=3, fuzzy_threshold=0.70, tie_threshold=0.80)
    assert results[0].status == MatchStatus.exception
    assert results[0].confidence == 0.0


def test_duplicate_risk_produces_exception():
    """Two ERP records that both score above tie_threshold against same bank record → exception."""
    d = date(2026, 8, 15)
    bank = make_record(50000.0, d, ref="TXN-DUP")
    erp1 = make_record(50000.0, d, ref="TXN-DUP", desc="Vendor A", source_type="erp")
    erp2 = make_record(50000.0, d, ref="TXN-DUP", desc="Vendor A", source_type="erp")

    results = _match_pairs([bank], [erp1, erp2], window=3, fuzzy_threshold=0.70, tie_threshold=0.80)
    assert results[0].status == MatchStatus.exception
    assert "Duplicate risk" in results[0].match_reason


# ─── Confidence mapping tests ─────────────────────────────────────────────────

def test_exact_confidence_range():
    conf = _confidence_from_score(1.0, is_exact=True)
    assert 95.0 <= conf <= 100.0


def test_fuzzy_confidence_range():
    conf = _confidence_from_score(0.70, is_exact=False)
    assert 70.0 <= conf <= 94.0


def test_match_reason_not_empty():
    """Every result must have a non-empty match_reason."""
    d = date(2026, 8, 15)
    bank = make_record(1000.0, d, ref="REF-X")
    erp = make_record(5000.0, d + __import__('datetime').timedelta(days=10), ref="DIFFERENT", source_type="erp")
    results = _match_pairs([bank], [erp], window=3, fuzzy_threshold=0.70, tie_threshold=0.80)
    for r in results:
        assert r.match_reason is not None and len(r.match_reason) > 0
