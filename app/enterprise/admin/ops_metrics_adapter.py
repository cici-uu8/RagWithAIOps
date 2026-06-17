"""Adapter boundary for admin ops metrics APIs."""

from __future__ import annotations

from app.enterprise.context import RequestContext

from .ops_metrics_service import OpsMetricsService, ops_metrics_service

ALLOWED_TIME_RANGES = {"1h", "24h", "7d", "30d"}
ALLOWED_BUCKETS = {"1h", "1d"}
MAX_FAILURE_LIMIT = 100


class OpsMetricsAdapter:
    def __init__(self, *, service: OpsMetricsService | None = None):
        self.service = service or ops_metrics_service

    async def get_summary(self, context: RequestContext, time_range: str) -> dict:
        self._require_admin(context)
        normalized_range = self._validate_time_range(time_range)
        return self.service.get_summary(context, normalized_range)

    async def get_timeline(
        self,
        context: RequestContext,
        time_range: str,
        bucket: str,
    ) -> list[dict]:
        self._require_admin(context)
        normalized_range = self._validate_time_range(time_range)
        normalized_bucket = self._validate_bucket(bucket)
        return self.service.get_timeline(context, normalized_range, normalized_bucket)

    async def get_failures(
        self,
        context: RequestContext,
        time_range: str,
        limit: int,
    ) -> list[dict]:
        self._require_admin(context)
        normalized_range = self._validate_time_range(time_range)
        normalized_limit = self._validate_limit(limit)
        return self.service.get_failures(context, normalized_range, normalized_limit)

    def _require_admin(self, context: RequestContext) -> None:
        if "admin" not in context.roles:
            raise PermissionError("Admin role required")

    def _validate_time_range(self, time_range: str) -> str:
        normalized = (time_range or "").strip()
        if normalized not in ALLOWED_TIME_RANGES:
            raise ValueError("time_range must be one of 1h, 24h, 7d, 30d")
        return normalized

    def _validate_bucket(self, bucket: str) -> str:
        normalized = (bucket or "").strip()
        if normalized not in ALLOWED_BUCKETS:
            raise ValueError("bucket must be one of 1h, 1d")
        return normalized

    def _validate_limit(self, limit: int) -> int:
        if limit < 1 or limit > MAX_FAILURE_LIMIT:
            raise ValueError("limit must be between 1 and 100")
        return limit


ops_metrics_adapter = OpsMetricsAdapter()
