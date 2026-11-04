"""Loads the demo workspace and reaches its starting state by running the real engine."""

import secrets
import sys
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, engine
from app.demo.generator import DATASETS, WINDOW_END, WINDOW_START, generate
from app.models import DataSource, GroundTruth, Investigation, RecommendedCheck, User, Workspace, utcnow
from app.security import hash_password
from app.services import refs
from app.services.orchestrator import analyze, create_timeline, execute_checks
from app.services.sources import ALL_SOURCE_KEYS, SOURCE_DEFINITIONS, UNCONNECTED_SOURCES

DEMO_USERS = [
    ("ada@cobalt.example", "Ada Okafor", "Lead investigator", "admin"),
    ("jonas@cobalt.example", "Jonas Reyes", "Security manager", "approver"),
    ("priya@cobalt.example", "Priya Nair", "Security analyst", "investigator"),
    ("mina@cobalt.example", "Mina Sato", "Compliance reviewer", "viewer"),
]


def load_records(db: Session) -> None:
    connection = db.connection().connection
    columns = "(dataset, source_key, ts, entity, payload)"
    with connection.cursor() as cursor:
        for dataset in DATASETS:
            rows, truth = generate(dataset)
            with cursor.copy(f"COPY evidence_records {columns} FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)
            db.add(GroundTruth(dataset=dataset, truth=truth))
            print(f"  {DATASETS[dataset]['label']}: {len(rows):,} records")


def next_ref(db: Session) -> str:
    return refs.next_ref(db, Investigation, "INV")


def new_investigation(db, workspace, user, name, claim, dataset, objective, sources=None) -> Investigation:
    investigation = Investigation(
        workspace_id=workspace.id,
        ref=next_ref(db),
        name=name,
        claim_text=claim,
        objective=objective,
        dataset=dataset,
        scope={
            "window_start": WINDOW_START.isoformat(),
            "window_end": WINDOW_END.isoformat(),
            "window_label": "Last 24 hours of the snapshot",
            "assets_label": "All in-scope assets",
            "asset_classes": [],
        },
        source_keys=sources or ALL_SOURCE_KEYS,
        created_by_id=user.id,
        assignee_id=user.id,
    )
    db.add(investigation)
    db.flush()
    create_timeline(db, investigation)
    db.commit()
    return investigation


def approve_all(db, investigation, user) -> None:
    rows = db.scalars(
        select(RecommendedCheck).where(
            RecommendedCheck.investigation_id == investigation.id, RecommendedCheck.status == "proposed"
        )
    ).all()
    for row in rows:
        row.status = "approved"
        row.decided_by_id = user.id
        row.decided_at = utcnow()
    db.commit()
    execute_checks(db, investigation.id, [r.id for r in rows])


def seed_investigations(db: Session, workspace: Workspace, users: dict[str, User]) -> None:
    ada, priya = users["admin"], users["investigator"]
    bravo = new_investigation(
        db,
        workspace,
        priya,
        "Weekly access assurance",
        "No unauthorized access occurred during the last 24 hours.",
        "B",
        "Confirm the weekly access statement before it goes to the risk committee.",
    )
    analyze(db, bravo.id)
    approve_all(db, bravo, users["approver"])
    mfa = new_investigation(
        db,
        workspace,
        priya,
        "MFA enforcement review",
        "MFA was enforced on all successful sign-ins during the last 24 hours.",
        "A",
        "Support the quarterly identity control attestation.",
    )
    analyze(db, mfa.id)
    primary = new_investigation(
        db,
        workspace,
        ada,
        "Security claim analysis",
        "Can we confirm that no unauthorized access occurred during the last 24 hours?",
        "A",
        "Establish whether the analyst's statement to leadership is justified by the evidence.",
    )
    analyze(db, primary.id)


def seed() -> str:
    settings = get_settings()
    password = settings.null_demo_password or secrets.token_urlsafe(12)
    with SessionLocal() as db:
        if db.scalar(select(func.count(Workspace.id))):
            print("Already seeded. Run `make reset` to rebuild from scratch.")
            return ""
        workspace = Workspace(
            name="Cobalt Freight (demo)",
            is_demo=True,
            settings={
                "active_dataset": "A",
                "ai": {"reasoning_mode": "auto", "model_id": ""},
                "notifications": {
                    "critical_findings": True,
                    "approval_requests": True,
                    "verification_results": True,
                    "weekly_digest": False,
                },
                "security": {
                    "session_hours": settings.null_session_hours,
                    "require_approval_for_checks": True,
                    "separate_approver": False,
                },
            },
        )
        db.add(workspace)
        db.flush()
        users: dict[str, User] = {}
        for email, name, title, role in DEMO_USERS:
            user = User(
                workspace_id=workspace.id,
                email=email,
                name=name,
                title=title,
                role=role,
                password_hash=hash_password(password),
            )
            db.add(user)
            users[role] = user
        db.flush()
        synced = WINDOW_END - timedelta(minutes=5)
        for definition in SOURCE_DEFINITIONS:
            db.add(
                DataSource(
                    workspace_id=workspace.id,
                    mode="simulated",
                    status="connected",
                    last_sync_at=synced,
                    restricted=definition.get("restricted", False),
                    **{k: definition[k] for k in ("key", "name", "description", "permissions")},
                )
            )
        for definition in UNCONNECTED_SOURCES:
            db.add(DataSource(workspace_id=workspace.id, mode="simulated", status="disconnected", **definition))
        db.commit()
        print("Loading synthetic evidence")
        load_records(db)
        db.commit()
        print("Running seed investigations through the engine")
        seed_investigations(db, workspace, users)
    return password


def reset_tables() -> None:
    from app.db import Base

    with engine.begin() as connection:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE {tables} CASCADE"))


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset_tables()
    created = seed()
    if created:
        print("\nDemo sign-in: ada@cobalt.example (admin), jonas@ (approver), priya@ (investigator), mina@ (viewer)")
        print(f"Password: {created}")
