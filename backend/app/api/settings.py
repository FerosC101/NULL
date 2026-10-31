from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import get_workspace
from app.api.serializers import ai_status, user_out
from app.config import get_settings
from app.db import get_db
from app.models import AuditLog, User
from app.reasoning.base import ReasoningFailure
from app.reasoning.factory import CONTRIBUTOR_SUFFIX
from app.reasoning.meta import MetaClient
from app.security import ROLE_PERMISSIONS, audit, current_user, hash_password, require

router = APIRouter(prefix="/settings", tags=["settings"])


class WorkspaceBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class ProfileBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    title: str = Field(default="", max_length=120)


class AiBody(BaseModel):
    reasoning_mode: str = Field(pattern="^(auto|deterministic)$")
    model_id: str = Field(default="", max_length=120, pattern=r"^[A-Za-z0-9._:/-]*$")
    reasoning_effort: str = Field(default="medium", pattern="^(minimal|low|medium|high|xhigh)$")


class PreferencesBody(BaseModel):
    critical_findings: bool
    approval_requests: bool
    verification_results: bool
    weekly_digest: bool


class SecurityBody(BaseModel):
    separate_approver: bool


class InviteBody(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=120)
    role: str = Field(pattern="^(admin|approver|investigator|viewer)$")
    password: str = Field(min_length=12, max_length=200)


class RoleBody(BaseModel):
    role: str = Field(pattern="^(admin|approver|investigator|viewer)$")
    is_active: bool = True


def _merge(workspace, key: str, value: dict) -> None:
    workspace.settings = {**(workspace.settings or {}), key: value}
    flag_modified(workspace, "settings")


@router.get("")
def read_settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    workspace = get_workspace(db, user)
    settings = workspace.settings or {}
    members = db.scalars(select(User).where(User.workspace_id == user.workspace_id).order_by(User.name)).all()
    return {
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
            "is_demo": workspace.is_demo,
            "created_at": workspace.created_at,
        },
        "profile": user_out(user),
        "members": [user_out(m) for m in members],
        "roles": {role: sorted(permissions) for role, permissions in ROLE_PERMISSIONS.items()},
        "ai": ai_status(settings.get("ai", {})),
        "notifications": settings.get("notifications", {}),
        "security": settings.get("security", {}),
        "api": {
            "base_path": "/api/v1",
            "docs_path": "/api/docs",
            "tokens_available": False,
        },
    }


@router.patch("/workspace")
def update_workspace(
    body: WorkspaceBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings.manage")),
):
    workspace = get_workspace(db, user)
    workspace.name = body.name
    audit(db, user, user.workspace_id, "settings.workspace_updated", body.name, request=request)
    db.commit()
    return {"name": workspace.name}


@router.patch("/profile")
def update_profile(
    body: ProfileBody, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    user.name, user.title = body.name, body.title
    audit(db, user, user.workspace_id, "settings.profile_updated", user.email, request=request)
    db.commit()
    return user_out(user)


@router.patch("/ai")
def update_ai(
    body: AiBody, request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.manage"))
):
    workspace = get_workspace(db, user)
    if body.model_id.endswith(CONTRIBUTOR_SUFFIX) and not get_settings().null_allow_contributor_models:
        raise HTTPException(422, "Contributor models may use inputs for training and are blocked for evidence data.")
    _merge(workspace, "ai", body.model_dump())
    audit(db, user, user.workspace_id, "settings.ai_updated", body.model_id, body.model_dump(), request)
    db.commit()
    return ai_status(workspace.settings["ai"])


@router.post("/ai/test")
def test_ai(request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.manage"))):
    settings = get_settings()
    if not settings.model_api_key:
        return {"ok": False, "message": "MODEL_API_KEY is not set on the server.", "models": []}
    try:
        models = MetaClient(settings.model_api_key, settings.meta_api_base, timeout=20).list_models()
    except ReasoningFailure as exc:
        audit(db, user, user.workspace_id, "settings.ai_test_failed", detail={"error": str(exc)}, request=request)
        db.commit()
        return {"ok": False, "message": str(exc), "models": []}
    audit(db, user, user.workspace_id, "settings.ai_tested", detail={"models": len(models)}, request=request)
    db.commit()
    return {"ok": True, "message": f"Connected. {len(models)} models available.", "models": models}


@router.patch("/notifications")
def update_notifications(
    body: PreferencesBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings.manage")),
):
    workspace = get_workspace(db, user)
    _merge(workspace, "notifications", body.model_dump())
    audit(db, user, user.workspace_id, "settings.notifications_updated", detail=body.model_dump(), request=request)
    db.commit()
    return body.model_dump()


@router.patch("/security")
def update_security(
    body: SecurityBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings.manage")),
):
    workspace = get_workspace(db, user)
    current = (workspace.settings or {}).get("security", {})
    updated = {**current, "separate_approver": body.separate_approver}
    _merge(workspace, "security", updated)
    audit(db, user, user.workspace_id, "settings.security_updated", detail=body.model_dump(), request=request)
    db.commit()
    return updated


@router.post("/members", status_code=201)
def add_member(
    body: InviteBody, request: Request, db: Session = Depends(get_db), user: User = Depends(require("settings.manage"))
):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "A user with this email already exists")
    member = User(
        workspace_id=user.workspace_id,
        email=email,
        name=body.name,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(member)
    audit(db, user, user.workspace_id, "member.added", email, {"role": body.role}, request)
    db.commit()
    return user_out(member)


@router.patch("/members/{member_id}")
def update_member(
    member_id: str,
    body: RoleBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("settings.manage")),
):
    member = db.get(User, member_id)
    if member is None or member.workspace_id != user.workspace_id:
        raise HTTPException(404, "Member not found")
    if member.id == user.id and (body.role != "admin" or not body.is_active):
        raise HTTPException(409, "You can't remove your own admin access")
    member.role, member.is_active = body.role, body.is_active
    audit(db, user, user.workspace_id, "member.updated", member.email, body.model_dump(), request)
    db.commit()
    return user_out(member)


@router.get("/audit")
def audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    action: str = Query(default="", max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(require("audit.read")),
):
    query = select(AuditLog).where(AuditLog.workspace_id == user.workspace_id)
    if action:
        query = query.where(AuditLog.action.ilike(f"%{action}%"))
    rows = db.scalars(query.order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return [
        {
            "id": r.id,
            "at": r.created_at,
            "actor": r.actor_label,
            "action": r.action,
            "target": r.target,
            "detail": r.detail,
            "ip": r.ip,
        }
        for r in rows
    ]
