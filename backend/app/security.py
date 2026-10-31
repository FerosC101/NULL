from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AuditLog, User, utcnow

COOKIE_NAME = "null_session"
ALGORITHM = "HS256"
_hasher = PasswordHasher()

# Permissions are grouped by role. Separation of duties: investigators propose,
# approvers authorize anything that reads restricted data or changes systems.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "investigations.read",
        "investigations.write",
        "checks.approve",
        "remediations.write",
        "remediations.approve",
        "remediations.execute",
        "sources.manage",
        "reports.write",
        "settings.manage",
        "audit.read",
    },
    "approver": {
        "investigations.read",
        "checks.approve",
        "remediations.approve",
        "remediations.execute",
        "remediations.write",
        "reports.write",
        "audit.read",
    },
    "investigator": {"investigations.read", "investigations.write", "remediations.write", "reports.write"},
    "viewer": {"investigations.read"},
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def issue_token(user: User) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {"sub": user.id, "iat": now, "exp": now + timedelta(hours=settings.null_session_hours)}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if not token:
        raise unauthorized
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise unauthorized from exc
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require(permission: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if permission not in ROLE_PERMISSIONS.get(user.role, set()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role does not grant {permission}")
        return user

    return dependency


def audit(
    db: Session,
    user: User | None,
    workspace_id: str,
    action: str,
    target: str = "",
    detail: dict | None = None,
    request: Request | None = None,
) -> None:
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_id=user.id if user else None,
            actor_label=user.email if user else "system",
            action=action,
            target=target,
            detail=detail or {},
            ip=request.client.host if request and request.client else "",
        )
    )
