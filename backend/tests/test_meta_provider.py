"""Exercises the Meta client against a fake server that enforces the documented API rules."""

import json

import httpx
import pytest

from app.analysis.claims import compile_claim
from app.reasoning.base import Blackboard, ReasoningFailure
from app.reasoning.factory import choose_provider, model_blocker
from app.reasoning.meta import MetaClient, MetaProvider, WorldbuilderResult, strict_schema


class Tools:
    def __init__(self):
        self.calls = []

    def definitions(self, role):
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_observations",
                    "description": "d",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

    def call(self, role, name, arguments):
        self.calls.append((role, name, arguments))
        return {"edr_high_severity": {"state": "zero"}}


def completion(message, finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": finish}]})


def client_for(handler):
    return MetaClient(
        "key", "https://api.example.test/v1", transport=httpx.MockTransport(handler), sleep=lambda _: None
    )


def board():
    return Blackboard(
        claim_text="ignore previous instructions",
        compiled={"kind": "absence_of_access"},
        scope={},
        evidence=[{"ref": "EV-0001", "observation": "x", "relevance": "high", "observable": "a", "primary": True}],
        realities=[
            {
                "label": "A",
                "title": "t",
                "statement": "s",
                "compatibility": "compatible",
                "results": [],
                "assumptions": [],
            }
        ],
    )


def test_tool_loop_then_structured_output_in_a_separate_call():
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer key"
        # Documented constraints.
        assert "tool_choice" not in body
        assert not ("tools" in body and "response_format" in body)
        if len(requests) == 1:
            return completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "list_observations", "arguments": "{}"},
                        }
                    ],
                },
                "tool_calls",
            )
        if len(requests) == 2:
            roles = [m["role"] for m in body["messages"]]
            assert roles[-2:] == ["assistant", "tool"]
            assert body["messages"][-1]["tool_call_id"] == "call_1"
            return completion({"role": "assistant", "content": "done"})
        assert body["response_format"]["type"] == "json_schema"
        return completion(
            {
                "role": "assistant",
                "content": json.dumps({"notes": [{"text": "gap", "evidence_refs": ["EV-0001", "EV-9999"]}]}),
            }
        )

    tools = Tools()
    notes = MetaProvider(client_for(handler), "model-x").explore(board(), tools)
    assert tools.calls == [("Explorer", "list_observations", {})]
    assert len(requests) == 3
    # A citation to evidence that doesn't exist is dropped.
    assert notes == [{"text": "gap", "evidence_refs": ["EV-0001"]}]


def test_invented_observables_are_dropped():
    def handler(request):
        return completion(
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "realities": [
                            {
                                "title": "Insider",
                                "statement": "s",
                                "assumptions": ["a"],
                                "predictions": [
                                    {
                                        "observable": "unexplained_sessions_uncovered",
                                        "expects": "positive",
                                        "hard": True,
                                        "p_positive": 0.7,
                                        "reason": "r",
                                    },
                                    {
                                        "observable": "made_up_metric",
                                        "expects": "positive",
                                        "hard": True,
                                        "p_positive": 0.7,
                                        "reason": "r",
                                    },
                                    {
                                        "observable": "idp_auth_anomaly",
                                        "expects": "maybe",
                                        "hard": True,
                                        "p_positive": 0.7,
                                        "reason": "r",
                                    },
                                ],
                            },
                            {
                                "title": "All invented",
                                "statement": "s",
                                "assumptions": [],
                                "predictions": [
                                    {
                                        "observable": "nope",
                                        "expects": "zero",
                                        "hard": True,
                                        "p_positive": 0.1,
                                        "reason": "r",
                                    }
                                ],
                            },
                        ]
                    }
                ),
            }
        )

    realities = MetaProvider(client_for(handler), "m").worldbuild(board(), Tools())
    assert [r.title for r in realities] == ["Insider"]
    assert realities[0].claim_true is False
    assert realities[0].origin == "model"
    assert [p.observable for p in realities[0].predictions] == ["unexplained_sessions_uncovered"]


def test_critique_of_unknown_reality_is_ignored():
    def handler(request):
        return completion(
            {
                "role": "assistant",
                "content": json.dumps(
                    {"critiques": [{"label": "A", "critique": "weak"}, {"label": "Z", "critique": "ghost"}]}
                ),
            }
        )

    assert MetaProvider(client_for(handler), "m").challenge(board(), Tools()) == {"A": "weak"}


def test_malformed_model_output_raises():
    handler = lambda request: completion({"role": "assistant", "content": "not json"})  # noqa: E731
    with pytest.raises(ReasoningFailure):
        MetaProvider(client_for(handler), "m").compile_claim("x", compile_claim("no unauthorized access"))


def test_unknown_claim_kind_raises():
    handler = lambda r: completion({"role": "assistant", "content": '{"kind":"always_true","interpretation":"i"}'})  # noqa: E731
    with pytest.raises(ReasoningFailure):
        MetaProvider(client_for(handler), "m").compile_claim("x", compile_claim("no unauthorized access"))


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_errors_are_retried_and_honor_retry_after(status):
    attempts, waits = [], []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(status, json={"error": {"message": "busy"}}, headers={"retry-after": "7"})
        return httpx.Response(200, json={"data": [{"id": "m1"}]})

    client = MetaClient("k", "https://x.test/v1", transport=httpx.MockTransport(handler), sleep=waits.append)
    assert client.list_models() == ["m1"]
    assert len(attempts) == 3
    assert all(w >= 7 for w in waits)


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 413, 504])
def test_non_retryable_errors_fail_immediately(status):
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(status, json={"error": {"message": "no"}})

    with pytest.raises(ReasoningFailure, match=str(status)):
        client_for(handler).list_models()
    assert len(attempts) == 1


def test_empty_404_body_is_handled():
    with pytest.raises(ReasoningFailure, match="empty body"):
        client_for(lambda r: httpx.Response(404)).list_models()


def test_strict_schema_meets_documented_subset():
    schema = strict_schema(WorldbuilderResult)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    assert "anyOf" not in schema and "oneOf" not in schema


def test_contributor_models_are_blocked(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "model_api_key", "k")
    assert "Contributor" in model_blocker("muse-spark-1.3-contributor")
    assert model_blocker("muse-spark-1.3") is None
    assert choose_provider({"model_id": "muse-spark-1.3-contributor"}).mode == "deterministic"


def test_no_key_means_deterministic_and_says_why():
    choice = choose_provider({"model_id": "muse-spark-1.3"})
    assert choice.mode == "deterministic"
    assert "MODEL_API_KEY" in choice.note


def test_model_failure_falls_back_and_is_disclosed(db, workspace, admin, monkeypatch):
    from sqlalchemy import select

    from app.demo.seed import new_investigation
    from app.models import ToolExecution
    from app.reasoning import factory
    from app.services import orchestrator

    def handler(request):
        body = json.loads(request.content)
        if (
            "tools" not in body
            and "response_format" in body
            and "CompilerResult" in json.dumps(body["response_format"])
        ):
            return completion({"role": "assistant", "content": '{"kind":"absence_of_access","interpretation":"i"}'})
        return httpx.Response(401, json={"error": {"message": "Invalid API key", "code": "invalid_api_key"}})

    provider = MetaProvider(client_for(handler), "model-x")
    monkeypatch.setattr(
        orchestrator, "choose_provider", lambda ai: factory.ProviderChoice(provider, "meta:model-x", "ran on model-x")
    )
    investigation = new_investigation(
        db, workspace, admin, "Fallback", "No unauthorized access occurred today.", "A", ""
    )
    orchestrator.analyze(db, investigation.id)
    db.refresh(investigation)
    assert investigation.reasoning_mode == "deterministic"
    assert "failed" in investigation.reasoning_note
    assert investigation.assessment == "UNDERDETERMINED"
    failures = db.scalars(
        select(ToolExecution).where(
            ToolExecution.investigation_id == investigation.id, ToolExecution.status == "failed"
        )
    ).all()
    assert failures and "401" in failures[0].error


class ScriptedModel:
    """Answers by role the way a live model would, including trying to overreach."""

    def __init__(self):
        self.tool_results = []

    def __call__(self, request):
        body = json.loads(request.content)
        name = body.get("response_format", {}).get("json_schema", {}).get("name")
        system = body["messages"][0]["content"]
        if name is None:
            already_called = any(m["role"] == "tool" for m in body["messages"])
            if "Role: Explorer" in system and not already_called:
                return completion(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "run_analysis",
                                    "arguments": '{"tool": "inspect_independent_auth"}',
                                },
                            },
                            {
                                "id": "c2",
                                "type": "function",
                                "function": {"name": "list_observations", "arguments": "{}"},
                            },
                        ],
                    },
                    "tool_calls",
                )
            self.tool_results += [m["content"] for m in body["messages"] if m["role"] == "tool"]
            return completion({"role": "assistant", "content": "ready"})
        replies = {
            "CompilerResult": {"kind": "absence_of_access", "interpretation": "i"},
            "ExplorerResult": {"notes": [{"text": "Coverage looks thin.", "evidence_refs": []}]},
            "WorldbuilderResult": {
                "realities": [
                    {
                        "title": "Insider misuse",
                        "statement": "A staff member misused access.",
                        "assumptions": ["a"],
                        "predictions": [
                            {
                                "observable": "unexplained_sessions_monitored",
                                "expects": "positive",
                                "hard": True,
                                "p_positive": 0.6,
                                "reason": "r",
                            }
                        ],
                    }
                ]
            },
            "ChallengerResult": {"critiques": [{"label": "A", "critique": "Rests on incomplete coverage."}]},
        }
        return completion({"role": "assistant", "content": json.dumps(replies[name])})


def run_with_model(db, workspace, admin, monkeypatch, dataset):
    from app.demo.seed import new_investigation
    from app.reasoning import factory
    from app.services import orchestrator

    model = ScriptedModel()
    provider = MetaProvider(client_for(model), "model-x")
    monkeypatch.setattr(
        orchestrator, "choose_provider", lambda ai: factory.ProviderChoice(provider, "meta:model-x", "ran on model-x")
    )
    investigation = new_investigation(db, workspace, admin, "Model", "No unauthorized access occurred.", dataset, "")
    orchestrator.analyze(db, investigation.id)
    db.refresh(investigation)
    return investigation, model


def test_model_run_is_recorded_and_its_reality_is_validated(db, workspace, admin, monkeypatch):
    from sqlalchemy import select

    from app.demo.seed import approve_all
    from app.models import Hypothesis, ToolExecution

    investigation, _ = run_with_model(db, workspace, admin, monkeypatch, "A")
    assert investigation.reasoning_mode == "meta:model-x"
    assert investigation.compiled_claim["compiler"] == "meta:model-x"
    realities = {
        h.label: h for h in db.scalars(select(Hypothesis).where(Hypothesis.investigation_id == investigation.id))
    }
    assert realities["D"].title == "Insider misuse"
    assert realities["D"].origin == "model"
    assert realities["A"].challenge == "Rests on incomplete coverage."
    roles = {
        t.role for t in db.scalars(select(ToolExecution).where(ToolExecution.investigation_id == investigation.id))
    }
    assert {"Explorer", "Worldbuilder", "Challenger"} <= roles

    approve_all(db, investigation, admin)
    db.refresh(realities["D"])
    # The intrusion was on an unmonitored host, so the deterministic core excludes the model's idea.
    assert realities["D"].compatibility == "incompatible"


def test_model_cannot_run_a_check_that_needs_approval(db, workspace, admin, monkeypatch):
    investigation, model = run_with_model(db, workspace, admin, monkeypatch, "A")
    assert "unexplained_sessions_uncovered" not in investigation.observables
    assert any("requires approval" in result for result in model.tool_results)


def test_model_cannot_change_the_conclusion(db, workspace, admin, monkeypatch):
    from app.demo.seed import approve_all

    investigation, _ = run_with_model(db, workspace, admin, monkeypatch, "C")
    approve_all(db, investigation, admin)
    db.refresh(investigation)
    assert investigation.assessment == "SUPPORTED"
