from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import GraphEdge, GraphNode, Investigation, User
from app.security import require

router = APIRouter(prefix="/network", tags=["network"])


@router.get("")
def network(
    investigation_id: str = "", db: Session = Depends(get_db), user: User = Depends(require("investigations.read"))
):
    edges_query = (
        select(GraphEdge)
        .join(Investigation, GraphEdge.investigation_id == Investigation.id)
        .where(Investigation.workspace_id == user.workspace_id)
    )
    nodes_query = select(GraphNode).where(GraphNode.workspace_id == user.workspace_id)
    if investigation_id:
        edges_query = edges_query.where(GraphEdge.investigation_id == investigation_id)
        nodes_query = nodes_query.where(
            or_(GraphNode.investigation_id == investigation_id, GraphNode.investigation_id.is_(None))
        )
    edges = db.scalars(edges_query).all()
    linked = {e.source_id for e in edges} | {e.target_id for e in edges}
    nodes = [n for n in db.scalars(nodes_query) if n.id in linked]
    investigations = db.execute(
        select(Investigation.id, Investigation.ref, Investigation.name)
        .where(Investigation.workspace_id == user.workspace_id)
        .order_by(Investigation.ref.desc())
    ).all()
    return {
        "nodes": [
            {"id": n.id, "kind": n.kind, "label": n.label, "investigation_id": n.investigation_id, "data": n.data}
            for n in nodes
        ],
        "edges": [
            {
                "id": e.id,
                "source": e.source_id,
                "target": e.target_id,
                "relation": e.relation,
                "explanation": e.explanation,
                "investigation_id": e.investigation_id,
            }
            for e in edges
        ],
        "investigations": [{"id": i.id, "ref": i.ref, "name": i.name} for i in investigations],
    }
