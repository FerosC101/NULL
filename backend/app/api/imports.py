from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import Dataset, ImportFile, User
from app.security import audit, require
from app.services import imports

router = APIRouter(prefix="/imports", tags=["imports"])


class ImportBody(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    data_class: str = Field(pattern="^(real|synthetic)$")
    allow_model: bool = False


class FileBody(BaseModel):
    kind: str | None = None
    mapping: dict[str, str] = {}
    timezone: str | None = Field(default=None, max_length=60)


class CommitBody(BaseModel):
    accept_rejected: bool = False


def _dataset(db: Session, user: User, key: str) -> Dataset:
    dataset = db.get(Dataset, key)
    if dataset is None or dataset.workspace_id != user.workspace_id:
        raise HTTPException(404, "Upload not found")
    return dataset


def _out(db: Session, dataset: Dataset) -> dict:
    files = db.scalars(
        select(ImportFile).where(ImportFile.dataset_key == dataset.key).order_by(ImportFile.created_at)
    ).all()
    return {
        "key": dataset.key,
        "label": dataset.label,
        "data_class": dataset.data_class,
        "status": dataset.status,
        "window_start": dataset.window_start,
        "window_end": dataset.window_end,
        "summary": dataset.summary,
        "created_at": dataset.created_at,
        "files": [imports.file_out(f) for f in files],
    }


def _problem(exc: imports.ImportProblem) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("/options")
def options(user: User = Depends(require("sources.manage"))):
    return {"kinds": imports.options(), "max_bytes": imports.MAX_FILE_BYTES}


@router.get("")
def list_imports(db: Session = Depends(get_db), user: User = Depends(require("sources.manage"))):
    rows = db.scalars(
        select(Dataset).where(Dataset.workspace_id == user.workspace_id).order_by(Dataset.created_at.desc())
    ).all()
    return [_out(db, row) for row in rows]


@router.post("", status_code=201)
def create_import(
    body: ImportBody, request: Request, db: Session = Depends(get_db), user: User = Depends(require("sources.manage"))
):
    dataset = Dataset(
        key=imports.new_key(),
        workspace_id=user.workspace_id,
        label=body.label.strip(),
        data_class=body.data_class,
        created_by_id=user.id,
        summary={"allow_model": body.allow_model},
    )
    db.add(dataset)
    detail = {"data_class": body.data_class, "allow_model": body.allow_model}
    audit(db, user, user.workspace_id, "import.created", dataset.key, detail, request)
    db.commit()
    return _out(db, dataset)


@router.get("/{key}")
def get_import(key: str, db: Session = Depends(get_db), user: User = Depends(require("sources.manage"))):
    return _out(db, _dataset(db, user, key))


def _store_file(key: str, user: User, name: str, content: bytes, request: Request) -> dict:
    with SessionLocal() as db:
        dataset = _dataset(db, user, key)
        try:
            file = imports.add_file(db, dataset, name, content)
        except imports.ImportProblem as exc:
            raise _problem(exc) from exc
        db.flush()
        detail = {"file": file.name, "sha256": file.sha256, "kind": file.kind}
        audit(db, user, user.workspace_id, "import.file_added", key, detail, request)
        db.commit()
        return imports.file_out(file)


@router.post("/{key}/files", status_code=201)
async def add_file(
    key: str,
    request: Request,
    name: str = Query(min_length=1, max_length=255),
    user: User = Depends(require("sources.manage")),
):
    """Takes the file as the raw request body, so nothing is parsed before the size check."""
    declared = int(request.headers.get("content-length") or 0)
    if declared > imports.MAX_FILE_BYTES:
        raise HTTPException(413, "This file is larger than 64 MB. Split it and upload the parts.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > imports.MAX_FILE_BYTES:
            raise HTTPException(413, "This file is larger than 64 MB. Split it and upload the parts.")
        chunks.append(chunk)
    if not size:
        raise HTTPException(422, "This file is empty.")
    return await run_in_threadpool(_store_file, key, user, name, b"".join(chunks), request)


def _file(db: Session, dataset: Dataset, file_id: str) -> ImportFile:
    file = db.get(ImportFile, file_id)
    if file is None or file.dataset_key != dataset.key:
        raise HTTPException(404, "File not found")
    return file


@router.put("/{key}/files/{file_id}")
def update_file(
    key: str,
    file_id: str,
    body: FileBody,
    db: Session = Depends(get_db),
    user: User = Depends(require("sources.manage")),
):
    dataset = _dataset(db, user, key)
    if dataset.status != "draft":
        raise HTTPException(409, "This upload is already committed")
    file = _file(db, dataset, file_id)
    try:
        imports.update_file(file, body.kind, body.mapping, body.timezone)
    except imports.ImportProblem as exc:
        raise _problem(exc) from exc
    db.commit()
    return imports.file_out(file)


@router.delete("/{key}/files/{file_id}")
def remove_file(
    key: str,
    file_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("sources.manage")),
):
    dataset = _dataset(db, user, key)
    if dataset.status != "draft":
        raise HTTPException(409, "Committed evidence can't be removed")
    file = _file(db, dataset, file_id)
    audit(db, user, user.workspace_id, "import.file_removed", key, {"file": file.name}, request)
    db.delete(file)
    db.commit()
    return {"removed": file_id}


@router.post("/{key}/commit")
def commit_import(
    key: str,
    body: CommitBody,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require("sources.manage")),
):
    dataset = _dataset(db, user, key)
    try:
        summary = imports.commit(db, dataset, user, body.accept_rejected)
    except imports.ImportProblem as exc:
        raise _problem(exc) from exc
    audit(db, user, user.workspace_id, "import.committed", key, summary, request)
    db.commit()
    return _out(db, dataset)


@router.delete("/{key}")
def discard_import(
    key: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require("sources.manage"))
):
    dataset = _dataset(db, user, key)
    if dataset.status != "draft":
        raise HTTPException(409, "Committed evidence can't be removed")
    audit(db, user, user.workspace_id, "import.discarded", key, request=request)
    db.delete(dataset)
    db.commit()
    return {"removed": key}
