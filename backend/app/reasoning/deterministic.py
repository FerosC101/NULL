"""Rule-based roles, used when no model is configured or a model call fails.

These add no reasoning beyond what the templates and observations contain, and the interface
labels investigations that ran this way.
"""

from app.analysis.claims import CompiledClaim
from app.analysis.observables import OBSERVABLE_LABELS
from app.analysis.templates import Reality
from app.reasoning.base import Blackboard, ToolHost


class DeterministicProvider:
    name = "deterministic"
    model = None

    def compile_claim(self, text: str, fallback: CompiledClaim) -> CompiledClaim:
        return fallback

    def explore(self, board: Blackboard, tools: ToolHost) -> list[dict]:
        notes = []
        for key, item in board.observables.items():
            if item["state"] == "unavailable":
                notes.append({"text": f"{OBSERVABLE_LABELS.get(key, key)} could not be observed.", "evidence_refs": []})
        ordered = sorted(
            (i for i in board.evidence if i.get("primary")),
            key=lambda i: ("critical", "high", "medium", "low").index(i["relevance"]),
        )
        for item in ordered[:4]:
            notes.append({"text": item["observation"], "evidence_refs": [item["ref"]]})
        return notes

    def worldbuild(self, board: Blackboard, tools: ToolHost) -> list[Reality]:
        return []

    def challenge(self, board: Blackboard, tools: ToolHost) -> dict[str, str]:
        critiques = {}
        for reality in board.realities:
            conflicts = [r for r in reality["results"] if r["outcome"] == "violated"]
            untested = [r for r in reality["results"] if r["outcome"] == "untested" and r["hard"]]
            if conflicts:
                names = ", ".join(OBSERVABLE_LABELS.get(r["observable"], r["observable"]) for r in conflicts)
                critiques[reality["label"]] = f"Conflicts with observed results for: {names}."
            elif untested:
                names = ", ".join(OBSERVABLE_LABELS.get(r["observable"], r["observable"]) for r in untested)
                critiques[reality["label"]] = f"Not yet exposed to a test. Depends on: {names}."
            else:
                critiques[reality["label"]] = "Survived every test made so far."
        return critiques
