from dataclasses import dataclass

from app.config import get_settings
from app.reasoning.deterministic import DeterministicProvider
from app.reasoning.meta import MetaClient, MetaProvider

CONTRIBUTOR_SUFFIX = "-contributor"


@dataclass
class ProviderChoice:
    provider: object
    mode: str
    note: str


def model_blocker(model: str) -> str | None:
    settings = get_settings()
    if not settings.model_api_key:
        return "MODEL_API_KEY is not set on the server."
    if not model:
        return "No model is selected."
    if model.endswith(CONTRIBUTOR_SUFFIX) and not settings.null_allow_contributor_models:
        return (
            f"{model} is a Contributor model, whose inputs may be used to train Meta's models. It is blocked for "
            "evidence data unless NULL_ALLOW_CONTRIBUTOR_MODELS is true."
        )
    return None


def choose_provider(ai_settings: dict) -> ProviderChoice:
    settings = get_settings()
    requested = ai_settings.get("reasoning_mode", "auto")
    model = ai_settings.get("model_id") or settings.meta_model_id
    if requested == "deterministic":
        return ProviderChoice(DeterministicProvider(), "deterministic", "Deterministic reasoning selected in Settings.")
    blocker = model_blocker(model)
    if blocker:
        return ProviderChoice(
            DeterministicProvider(), "deterministic", f"Meta model not used: {blocker} Rule-based roles ran instead."
        )
    client = MetaClient(settings.model_api_key, settings.meta_api_base)
    provider = MetaProvider(client, model, ai_settings.get("reasoning_effort") or settings.meta_reasoning_effort)
    return ProviderChoice(provider, f"meta:{model}", f"Explorer, Worldbuilder and Challenger ran on {model}.")
