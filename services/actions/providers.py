"""Provider capabilities are explicit; a UI feature does not prove an API route."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapabilities:
    name: str
    actions: frozenset[str]


METRICFLOW = ProviderCapabilities("metricflow", frozenset({"pause", "enable", "budget_set"}))
# Reserved integration, deliberately has no executable capabilities yet.
META = ProviderCapabilities("meta", frozenset())
PROVIDERS = {provider.name: provider for provider in (METRICFLOW, META)}


def supports(provider: str, action: str) -> bool:
    capability = PROVIDERS.get(provider)
    return bool(capability and action in capability.actions)
