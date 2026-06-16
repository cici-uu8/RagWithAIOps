"""Guardrail orchestration for RequestGateway."""

from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.models import GatewayRequest, GuardrailDecision


class GuardrailService:
    def __init__(self, providers=None):
        self.providers = list(providers or [NoOpGuardrailProvider()])

    async def evaluate(self, request: GatewayRequest) -> GuardrailDecision:
        for provider in self.providers:
            decision = await provider.evaluate(request)
            if not decision.allowed:
                return decision
        return GuardrailDecision()
