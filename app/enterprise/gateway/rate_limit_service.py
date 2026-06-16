"""Rate-limit interface for E2. The first provider is intentionally no-op."""

from app.enterprise.gateway.models import GatewayRequest, RateLimitDecision


class NoOpRateLimitService:
    async def check(self, _request: GatewayRequest) -> RateLimitDecision:
        return RateLimitDecision()
