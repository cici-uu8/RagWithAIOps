"""Ops metrics aggregation for admin audit/trace dashboard."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent

REQUEST_EVENT_TYPES = {"request_completed", "request_failed"}
TOOL_EVENT_TYPES = {
    "tool_call",
    "tool_failure",
    "tool_blocked",
    "database_query",
}
TIME_RANGES = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
BUCKETS = {
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}


class OpsMetricsService:
    def __init__(
        self,
        *,
        audit_service: AuditService | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.audit_service = audit_service or AuditService()
        self.now_provider = now_provider or (lambda: datetime.now(UTC))

    def get_summary(self, context: RequestContext, time_range: str) -> dict[str, Any]:
        events = self._request_events(time_range)
        success_count = sum(1 for event in events if event.event_type == "request_completed")
        failed_count = sum(1 for event in events if event.event_type == "request_failed")
        latencies = sorted(
            float(event.latency_ms)
            for event in events
            if event.event_type == "request_completed" and event.latency_ms is not None
        )
        total_requests = len(events)
        return {
            "time_range": time_range,
            "total_requests": total_requests,
            "success_count": success_count,
            "failed_count": failed_count,
            "success_rate": round(success_count / total_requests, 4) if total_requests else 0.0,
            "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
            "p50_latency_ms": self._percentile(latencies, 50),
            "p95_latency_ms": self._percentile(latencies, 95),
            "top_users": self._top(events, field="user_id", output_key="user_id"),
            "top_routes": self._top(events, field="route", output_key="route"),
            "top_tools": self._top_tools(time_range),
        }

    def get_timeline(
        self,
        context: RequestContext,
        time_range: str,
        bucket: str,
    ) -> list[dict[str, Any]]:
        bucket_delta = BUCKETS.get(bucket, BUCKETS["1h"])
        grouped: dict[datetime, dict[str, int]] = {}
        for event in self._request_events(time_range):
            bucket_start = self._bucket_start(event.timestamp, bucket_delta)
            item = grouped.setdefault(bucket_start, {"total": 0, "success": 0, "failed": 0})
            item["total"] += 1
            if event.event_type == "request_completed":
                item["success"] += 1
            else:
                item["failed"] += 1

        return [
            {
                "time_bucket": bucket_start.isoformat(),
                "total": item["total"],
                "success": item["success"],
                "failed": item["failed"],
                "success_rate": round(item["success"] / item["total"], 4) if item["total"] else 0.0,
            }
            for bucket_start, item in sorted(grouped.items())
        ]

    def get_failures(
        self,
        context: RequestContext,
        time_range: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        failures = [
            event
            for event in self._request_events(time_range)
            if event.event_type == "request_failed"
        ]
        failures.sort(key=lambda event: event.timestamp)
        return [
            {
                "trace_id": event.trace_id,
                "request_id": event.request_id,
                "user_id": event.user_id,
                "route": event.route,
                "failure_semantics": self._failure_semantics(event),
                "recovered": bool((event.metadata or {}).get("recovered", False)),
                "timestamp": event.timestamp.isoformat(),
                "reason": event.reason,
                "error_class": event.error_class,
            }
            for event in failures[-limit:][::-1]
        ]

    def _request_events(self, time_range: str) -> list[AuditEvent]:
        events = self._events_since(time_range)
        return [event for event in events if event.event_type in REQUEST_EVENT_TYPES]

    def _events_since(self, time_range: str) -> list[AuditEvent]:
        start_time = self._start_time(time_range)
        return self.audit_service.query(start_time=start_time)

    def _start_time(self, time_range: str) -> datetime:
        delta = TIME_RANGES.get(time_range, TIME_RANGES["24h"])
        return self._normalize_datetime(self.now_provider()) - delta

    def _top(
        self,
        events: list[AuditEvent],
        *,
        field: str,
        output_key: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        counts = Counter(str(getattr(event, field) or "unknown") for event in events)
        return [{output_key: key, "count": count} for key, count in counts.most_common(limit)]

    def _top_tools(self, time_range: str, limit: int = 10) -> list[dict[str, Any]]:
        counts: Counter[str] = Counter()
        for event in self._events_since(time_range):
            if event.event_type not in TOOL_EVENT_TYPES:
                continue
            tool_name = (
                (event.metadata or {}).get("tool_id")
                or (event.metadata or {}).get("tool_name")
                or (event.metadata or {}).get("operation_type")
                or event.route
            )
            counts[str(tool_name)] += 1
        return [{"tool": key, "count": count} for key, count in counts.most_common(limit)]

    def _percentile(self, values: list[float], percentile: int) -> int:
        if not values:
            return 0
        if len(values) == 1:
            return round(values[0])
        index = max(0, min(len(values) - 1, ceil((percentile / 100) * len(values)) - 1))
        return round(values[index])

    def _bucket_start(self, timestamp: datetime, bucket_delta: timedelta) -> datetime:
        normalized = self._normalize_datetime(timestamp)
        seconds = int(bucket_delta.total_seconds())
        epoch_seconds = int(normalized.timestamp())
        bucket_epoch = (epoch_seconds // seconds) * seconds
        return datetime.fromtimestamp(bucket_epoch, tz=UTC)

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _failure_semantics(self, event: AuditEvent) -> str:
        metadata = event.metadata or {}
        return str(
            metadata.get("failure_semantics")
            or metadata.get("error_class")
            or event.error_class
            or event.reason
            or "unknown"
        )


ops_metrics_service = OpsMetricsService()
