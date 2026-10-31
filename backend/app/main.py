import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import assurance, auth, investigations, network, overview, reports, settings, sources
from app.config import get_settings
from app.db import engine
from app.services.orchestrator import mark_interrupted

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if not get_settings().secret_key:  # The property raises in production when the secret is missing.
        raise RuntimeError("A session secret is required")
    mark_interrupted()
    yield


app = FastAPI(
    title="NULL API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if get_settings().is_production else "/api/docs",
    openapi_url=None if get_settings().is_production else "/api/openapi.json",
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["content-type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


api = APIRouter(prefix="/api/v1")
for module in (auth, overview, investigations, network, assurance, reports, sources, settings):
    api.include_router(module.router)


@api.get("/health")
def health() -> dict:
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    return {"status": "ok"}


app.include_router(api)
