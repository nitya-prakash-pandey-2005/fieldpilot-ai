"""
Auth — FieldPilot AI
------------------------
JWT issuance/verification + password hashing + FastAPI dependencies for
role-based access control. This is the first auth of any kind in the
codebase — previously verified (repo-wide grep) that NO route, including
POST /api/v1/graph/query (raw Cypher passthrough), had any protection.

Role hierarchy (system_prompt.md Section 9.1): worker < engineer < pm <
admin/executive. require_role(*roles) checks membership in an explicit
allow-list rather than a numeric hierarchy, since admin/executive are
siblings, not one strictly above the other.
"""

import os
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# HS256 with a real secret is fine for a single-deployment JWT; a
# multi-service deployment would want RS256 with a shared public key
# instead — flagged here for whoever picks this up for real multi-tenant
# production use.
_DEV_SECRET = "dev-only-insecure-secret-change-in-production"
JWT_SECRET = os.getenv("JWT_SECRET", _DEV_SECRET)
JWT_ALGORITHM = "HS256"

# A known default signing key means anyone can mint an admin token. That is
# tolerable on a laptop and not tolerable anywhere reachable, so refuse to boot
# rather than come up quietly insecure — a silent fallback is exactly the kind
# of thing that survives all the way to a public demo URL.
if JWT_SECRET == _DEV_SECRET:
    if os.getenv("FIELDPILOT_ENV", "development").lower() in ("production", "prod", "staging"):
        raise RuntimeError(
            "JWT_SECRET is unset while FIELDPILOT_ENV is production/staging. "
            "Generate one with:  python -c \"import secrets;print(secrets.token_urlsafe(48))\""
        )
    print("[AUTH] ⚠ using the built-in development JWT secret — anyone who has "
          "read this repo can forge a token. Set JWT_SECRET before exposing "
          "this API beyond localhost.")
ACCESS_TOKEN_EXPIRE_HOURS = 8  # matches system_prompt.md Section 9.1's "JWT tokens with 8-hour expiry"

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


class CurrentUser:
    def __init__(self, id: str, email: str, role: str):
        self.id = id
        self.email = email
        self.role = role


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(credentials.credentials)
    return CurrentUser(id=payload["sub"], email=payload["email"], role=payload["role"])


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[CurrentUser]:
    """For routes that enrich behavior when logged in but don't require it."""
    if credentials is None:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        return CurrentUser(id=payload["sub"], email=payload["email"], role=payload["role"])
    except HTTPException:
        return None


def require_role(*allowed_roles: str):
    """
    Dependency factory: raises 403 unless the current user's role is in
    allowed_roles. Usage: Depends(require_role("admin", "executive")).
    """
    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted — requires one of {allowed_roles}",
            )
        return user
    return _check
