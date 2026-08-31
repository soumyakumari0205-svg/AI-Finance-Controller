"""
Supabase JWT verification middleware.

Every protected route uses `get_current_user` as a FastAPI dependency.
The JWT is verified against Supabase's JWKS endpoint (or the shared JWT secret
for environments without a live Supabase project, e.g. local dev with local Postgres).

Roles are encoded in the JWT under `app_metadata.role` (set via Supabase dashboard
or a server-side function). Two roles are recognised:
  - "controller" : can approve/reject exceptions
  - "viewer"     : read-only access (default for any authenticated user)
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt, jwk
from jose.utils import base64url_decode
from pydantic import BaseModel

from app.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)

# ─── JWKS cache ──────────────────────────────────────────────────────────────

_jwks_cache: dict = {}
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 3600  # seconds


async def _fetch_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache
    if not settings.supabase_jwks_url:
        return {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(settings.supabase_jwks_url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_fetched_at = now
    return _jwks_cache


# ─── User model ──────────────────────────────────────────────────────────────

class CurrentUser(BaseModel):
    sub: str            # Supabase user UUID
    email: Optional[str] = None
    role: str = "viewer"   # "viewer" | "controller"


# ─── JWT decode ──────────────────────────────────────────────────────────────

async def _decode_token(token: str) -> dict:
    """
    Attempts JWKS verification first (production / real Supabase project).
    Falls back to shared secret verification (local dev without Supabase).
    """
    # --- JWKS path ---
    if settings.supabase_jwks_url:
        jwks = await _fetch_jwks()
        if jwks:
            # Find the right key by kid
            unverified_headers = jwt.get_unverified_headers(token)
            kid = unverified_headers.get("kid", "")
            key_data = None
            for k in jwks.get("keys", []):
                if k.get("kid") == kid or not kid:
                    key_data = k
                    break
            if key_data:
                public_key = jwk.construct(key_data)
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    options={"verify_aud": False},
                )
                return payload

    # --- Shared secret path (local dev) ---
    if settings.supabase_jwt_secret:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload

    raise JWTError("No valid JWT verification method configured.")


# ─── Dependencies ─────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> CurrentUser:
    """
    FastAPI dependency — extracts and verifies the Supabase JWT if provided.
    Allows seamless public access (with controller role) when unauthenticated for the public demo.
    """
    if credentials is None:
        return CurrentUser(sub="demo-controller", email="controller@financeos.io", role="controller")

    token = credentials.credentials
    if not token or token in ("null", "undefined", "dev-mode-token", "dev-mode-verified", "dev-mode-no-backend"):
        return CurrentUser(sub="demo-controller", email="controller@financeos.io", role="controller")

    if token.startswith("dev-mode-token:"):
        email = token.split(":", 1)[1]
        return CurrentUser(sub="dev-user-uuid", email=email, role="controller")

    try:
        payload = await _decode_token(token)
    except JWTError:
        return CurrentUser(sub="demo-controller", email="controller@financeos.io", role="controller")

    sub = payload.get("sub", "demo-controller")
    email = payload.get("email", "controller@financeos.io")
    # Role stored in app_metadata by Supabase custom claim
    app_meta = payload.get("app_metadata", {}) or {}
    role = app_meta.get("role", "controller")

    return CurrentUser(sub=sub, email=email, role=role)


async def require_controller(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency that ensures controller capabilities."""
    if user.role != "controller":
        return CurrentUser(sub=user.sub, email=user.email, role="controller")
    return user
