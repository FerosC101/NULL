"""One-command check of the live Meta Model API: `make smoke-meta`.

Sends only made-up text. Run it once after adding MODEL_API_KEY and META_MODEL_ID.
"""

import sys

from app.analysis.claims import compile_claim
from app.config import get_settings
from app.reasoning.base import Blackboard, ReasoningFailure
from app.reasoning.factory import model_blocker
from app.reasoning.meta import MetaClient, MetaProvider


class EchoTools:
    calls = 0

    def definitions(self, role):
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_observations",
                    "description": "List every observation made so far.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ]

    def call(self, role, name, arguments):
        EchoTools.calls += 1
        return {"edr_high_severity": {"state": "zero", "summary": "0 high severity detections."}}


def main() -> int:
    settings = get_settings()
    blocker = model_blocker(settings.meta_model_id)
    if blocker:
        print(f"Cannot run: {blocker}")
        return 1
    client = MetaClient(settings.model_api_key, settings.meta_api_base)
    provider = MetaProvider(client, settings.meta_model_id, settings.meta_reasoning_effort)
    board = Blackboard(
        claim_text="No unauthorized access occurred.",
        compiled={"kind": "absence_of_access"},
        scope={},
        evidence=[
            {
                "ref": "EV-0001",
                "observation": "0 high severity detections.",
                "relevance": "high",
                "observable": "edr_high_severity",
                "primary": True,
            }
        ],
    )
    steps = [
        ("GET /models", lambda: f"{len(client.list_models())} models"),
        (
            "Structured output",
            lambda: (
                provider.compile_claim(
                    "No unauthorized access occurred.", compile_claim("No unauthorized access occurred.")
                ).kind
            ),
        ),
        ("Role with tools", lambda: f"{len(provider.explore(board, EchoTools()))} notes, {EchoTools.calls} tool calls"),
    ]
    failed = False
    for name, step in steps:
        try:
            print(f"PASS  {name}: {step()}")
        except ReasoningFailure as exc:
            failed = True
            print(f"FAIL  {name}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
