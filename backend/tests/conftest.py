import os

os.environ["NULL_DATABASE_URL"] = "postgresql+psycopg://localhost/null_test"
os.environ["NULL_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256-signing"
os.environ["NULL_DEMO_PASSWORD"] = "test-password"
os.environ["MODEL_API_KEY"] = ""
os.environ["META_MODEL_ID"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.demo import seed as seed_module  # noqa: E402
from app.demo.generator import DATASETS  # noqa: E402
from app.models import GroundTruth, User, Workspace  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import sources  # noqa: E402


@pytest.fixture(scope="session")
def seeded():
    """One database with all four snapshots loaded, shared by the whole run."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        from app.models import DataSource

        workspace = Workspace(name="Test", is_demo=True, settings={"active_dataset": "A", "ai": {}})
        db.add(workspace)
        db.flush()
        for email, name, title, role in seed_module.DEMO_USERS:
            db.add(
                User(
                    workspace_id=workspace.id,
                    email=email,
                    name=name,
                    title=title,
                    role=role,
                    password_hash=hash_password("test-password"),
                )
            )
        for definition in sources.SOURCE_DEFINITIONS:
            db.add(
                DataSource(
                    workspace_id=workspace.id,
                    mode="simulated",
                    status="connected",
                    restricted=definition.get("restricted", False),
                    **{k: definition[k] for k in ("key", "name", "description", "permissions")},
                )
            )
        for definition in sources.UNCONNECTED_SOURCES:
            db.add(DataSource(workspace_id=workspace.id, mode="simulated", status="disconnected", **definition))
        db.commit()
        seed_module.load_records(db)
        db.commit()
    yield
    engine.dispose()


@pytest.fixture
def db(seeded):
    with SessionLocal() as session:
        yield session


@pytest.fixture
def workspace(db):
    return db.scalar(select(Workspace))


@pytest.fixture
def admin(db):
    return db.scalar(select(User).where(User.role == "admin"))


@pytest.fixture
def truth(db):
    return {t.dataset: t.truth for t in db.scalars(select(GroundTruth))}


@pytest.fixture
def client(seeded):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str = "ada@cobalt.example") -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": "test-password"})
    assert response.status_code == 200, response.text


__all__ = ["DATASETS", "login"]
