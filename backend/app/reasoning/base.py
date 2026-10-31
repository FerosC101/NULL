"""Reasoning roles share one blackboard. Providers propose; the deterministic core decides."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.analysis.claims import CompiledClaim
from app.analysis.templates import Reality


@dataclass
class Blackboard:
    """Shared investigation state every role reads from and adds to."""

    claim_text: str
    compiled: dict
    scope: dict
    observables: dict[str, dict] = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    realities: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)
    explorer_notes: list[dict] = field(default_factory=list)


class ToolHost(Protocol):
    """Backend tools a role may call. Implemented by the orchestrator so each call is recorded."""

    def call(self, role: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...

    def definitions(self, role: str) -> list[dict[str, Any]]: ...


class ReasoningProvider(Protocol):
    name: str
    model: str | None

    def compile_claim(self, text: str, fallback: CompiledClaim) -> CompiledClaim: ...

    def explore(self, board: Blackboard, tools: ToolHost) -> list[dict]: ...

    def worldbuild(self, board: Blackboard, tools: ToolHost) -> list[Reality]: ...

    def challenge(self, board: Blackboard, tools: ToolHost) -> dict[str, str]: ...


class ReasoningFailure(Exception):
    """A model call could not produce a usable result."""
