import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_workspace
from app.api.serializers import ai_status, user_out
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.security import COOKIE_NAME, audit, current_user, issue_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILURES = 8
LOCK_SECONDS = 300
_failures: dict[str, list[float]] = defaultdict(list)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


def _locked(key: str) -> bool:
    now = time.monotonic()
    _failures[key] = [t for t in _failures[key] if now - t < LOCK_SECONDS]
    return len(_failures[key]) >= MAX_FAILURES


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else ''}:{body.email.lower()}"
    if _locked(key):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        _failures[key].append(time.monotonic())
        if user:
            audit(db, None, user.workspace_id, "auth.login_failed", user.email, request=request)
            db.commit()
        raise HTTPException(401, "Email or password is incorrect")
    _failures.pop(key, None)
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        issue_token(user),
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.null_session_hours * 3600,
        path="/",
    )
    audit(db, user, user.workspace_id, "auth.login", user.email, request=request)
    db.commit()
    return user_out(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = get_workspace(db, user)
    settings = workspace.settings or {}
    return {
        "user": user_out(user),
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
            "is_demo": workspace.is_demo,
            "active_dataset": settings.get("active_dataset", "A"),
        },
        "ai": ai_status(settings.get("ai", {})),
    }
