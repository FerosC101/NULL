"""The deterministic core: evaluate realities against observations and decide the assessment.

Nothing here accepts model output as truth. Model-proposed realities arrive as predictions over
known observables and are judged by the same rules as NULL's own.
"""

import math
from dataclasses import dataclass
from itertools import product

SUPPORTED = "SUPPORTED"
CONTRADICTED = "CONTRADICTED"
PARTIALLY_IDENTIFIED = "PARTIALLY IDENTIFIED"
UNDERDETERMINED = "UNDERDETERMINED"
UNVERIFIED = "UNVERIFIED"

UNAVAILABLE = "unavailable"


@dataclass
class HypothesisView:
    label: str
    claim_true: bool
    predictions: list[dict]


def evaluate_prediction(prediction: dict, observable: dict | None) -> str:
    """Return matched, violated, inconclusive, untested, or indifferent."""
    if prediction["expects"] == "any":
        return "indifferent"
    if observable is None or observable["state"] == UNAVAILABLE:
        return "untested"
    state = observable["state"]
    if state == "partial":
        return "inconclusive"
    return "matched" if state == prediction["expects"] else "violated"


def evaluate_hypothesis(hypothesis: HypothesisView, observables: dict[str, dict]) -> tuple[str, list[dict]]:
    results = []
    for prediction in hypothesis.predictions:
        outcome = evaluate_prediction(prediction, observables.get(prediction["observable"]))
        results.append({**prediction, "outcome": outcome})
    hard = [r for r in results if r["hard"]]
    if any(r["outcome"] == "violated" for r in hard):
        return "incompatible", results
    if any(r["outcome"] == "violated" for r in results):
        return "strained", results
    decisive = [r for r in hard if r["expects"] == "positive"]
    if decisive and all(r["outcome"] == "matched" for r in decisive) and len(hard) == len(decisive):
        return "corroborated", results
    if hard and all(r["outcome"] == "matched" for r in hard):
        return "consistent", results
    tested = [r for r in results if r["outcome"] in ("matched", "inconclusive")]
    return ("compatible" if tested else "untested"), results


def assess(hypotheses: dict[str, tuple[bool, str, list[dict]]], any_observation: bool) -> str:
    """Decide the assessment from (claim_true, compatibility, results) per reality."""
    if not any_observation or not hypotheses:
        return UNVERIFIED
    claim = [v for v in hypotheses.values() if v[0]]
    alternatives = [v for v in hypotheses.values() if not v[0]]
    if not claim:
        return UNVERIFIED
    _, claim_status, claim_results = claim[0]
    if claim_status == "incompatible":
        return CONTRADICTED
    surviving = [v for v in alternatives if v[1] != "incompatible"]
    if not surviving:
        hard = [r for r in claim_results if r["hard"]]
        if claim_status == "consistent" and all(r["outcome"] == "matched" for r in hard):
            return SUPPORTED
        return PARTIALLY_IDENTIFIED
    narrowed = any(r["outcome"] == "inconclusive" for r in claim_results)
    excluded_some = len(surviving) < len(alternatives)
    # Identification needs part of the scope settled. A strained claim alone has settled nothing.
    if narrowed and excluded_some:
        return PARTIALLY_IDENTIFIED
    return UNDERDETERMINED


def entropy(probabilities: list[float]) -> float:
    return -sum(p * math.log2(p) for p in probabilities if p > 0)


def expected_information_gain(likelihoods: dict[str, list[float]]) -> float:
    """Mutual information in bits between the reality and a check's joint binary outcomes.

    `likelihoods` maps each surviving reality to P(positive) per observable the check would
    produce. Priors are uniform on purpose: NULL has no base rates for this environment, and
    outcomes are treated as conditionally independent given the reality.
    """
    labels = list(likelihoods)
    if len(labels) < 2:
        return 0.0
    observable_count = len(next(iter(likelihoods.values())))
    prior = 1 / len(labels)
    gain = entropy([prior] * len(labels))
    for outcome in product([0, 1], repeat=observable_count):
        joint = []
        for label in labels:
            p = prior
            for index, positive in enumerate(outcome):
                q = likelihoods[label][index]
                p *= q if positive else 1 - q
            joint.append(p)
        total = sum(joint)
        if total > 0:
            gain -= total * entropy([p / total for p in joint])
    return round(max(gain, 0.0), 3)


def distinguishing_labels(hypotheses: dict[str, list[dict]], observables: list[str]) -> list[str]:
    """Realities whose predictions differ on at least one of these observables."""
    labels = set()
    for observable in observables:
        expected = {}
        for label, predictions in hypotheses.items():
            for prediction in predictions:
                if prediction["observable"] == observable and prediction["expects"] != "any":
                    expected[label] = prediction["expects"]
        if len(set(expected.values())) > 1 or (expected and len(expected) < len(hypotheses)):
            labels.update(expected)
    return sorted(labels)
