import json
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import PlainTextResponse

app = FastAPI(title="AIOps Lab Service")

SERVICE_NAME = os.getenv("SERVICE_NAME", "data-sync-service")
INSTANCE_ID = os.getenv("INSTANCE_ID", f"{SERVICE_NAME}-1")
LOGS_DIR = Path(os.getenv("LOGS_DIR", "/app/logs"))

_state_lock = threading.Lock()
_fault_state: dict[str, Any] = {
    "cpu_high_until": 0.0,
    "db_slow_until": 0.0,
    "redis_backlog_size": 0,
    "redis_backlog_until": 0.0,
    "cache_miss_until": 0.0,
    "error_rate": 0.0,
    "error_rate_until": 0.0,
}


def _now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat()


def _parse_duration_seconds(duration: str | int | float) -> int:
    if isinstance(duration, (int, float)):
        return max(1, int(duration))
    normalized = str(duration).strip().lower()
    if normalized.endswith("ms"):
        return max(1, int(float(normalized[:-2]) / 1000))
    if normalized.endswith("s"):
        return max(1, int(float(normalized[:-1])))
    if normalized.endswith("m"):
        return max(1, int(float(normalized[:-1]) * 60))
    if normalized.endswith("h"):
        return max(1, int(float(normalized[:-1]) * 3600))
    return max(1, int(float(normalized)))


def _is_active(key: str) -> bool:
    return float(_fault_state.get(key, 0.0)) > time.time()


def _write_log(level: str, event_type: str, message: str, **metadata: Any) -> dict[str, Any]:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": _now_iso(),
        "service_name": SERVICE_NAME,
        "instance_id": INSTANCE_ID,
        "level": level,
        "trace_id": metadata.pop("trace_id", f"trace-{uuid.uuid4().hex[:12]}"),
        "event_type": event_type,
        "message": message,
        **metadata,
    }
    with (LOGS_DIR / f"{SERVICE_NAME}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _current_metrics() -> dict[str, float]:
    with _state_lock:
        cpu = 92.0 if _is_active("cpu_high_until") else 12.0
        latency = 3.4 if _is_active("db_slow_until") else 0.12
        queue_length = (
            float(_fault_state["redis_backlog_size"])
            if _is_active("redis_backlog_until")
            else 0.0
        )
        cache_miss_ratio = 0.95 if _is_active("cache_miss_until") else 0.05
        error_rate = (
            float(_fault_state["error_rate"])
            if _is_active("error_rate_until")
            else 0.0
        )
    return {
        "service_cpu_percent": cpu,
        "mysql_query_latency_seconds": latency,
        "redis_queue_length": queue_length,
        "cache_miss_ratio": cache_miss_ratio,
        "service_error_rate": error_rate,
    }


def _metrics_text() -> str:
    labels = f'service_name="{SERVICE_NAME}",instance_id="{INSTANCE_ID}"'
    lines = [
        "# HELP service_cpu_percent Simulated service CPU usage percent.",
        "# TYPE service_cpu_percent gauge",
        f"service_cpu_percent{{{labels}}} {_current_metrics()['service_cpu_percent']}",
        "# HELP mysql_query_latency_seconds Simulated MySQL query latency.",
        "# TYPE mysql_query_latency_seconds gauge",
        f"mysql_query_latency_seconds{{{labels}}} {_current_metrics()['mysql_query_latency_seconds']}",
        "# HELP redis_queue_length Simulated Redis queue length.",
        "# TYPE redis_queue_length gauge",
        f"redis_queue_length{{{labels}}} {_current_metrics()['redis_queue_length']}",
        "# HELP cache_miss_ratio Simulated cache miss ratio.",
        "# TYPE cache_miss_ratio gauge",
        f"cache_miss_ratio{{{labels}}} {_current_metrics()['cache_miss_ratio']}",
        "# HELP service_error_rate Simulated service error rate.",
        "# TYPE service_error_rate gauge",
        f"service_error_rate{{{labels}}} {_current_metrics()['service_error_rate']}",
    ]
    return "\n".join(lines) + "\n"


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "service_name": SERVICE_NAME,
        "instance_id": INSTANCE_ID,
        "status": "ok",
        "metrics": _current_metrics(),
    }


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return _metrics_text()


@app.post("/inject/cpu-high")
def inject_cpu_high(duration: str = Query("90s")) -> dict[str, Any]:
    seconds = _parse_duration_seconds(duration)
    with _state_lock:
        _fault_state["cpu_high_until"] = time.time() + seconds
    log = _write_log(
        "ERROR",
        "cpu_high",
        "service CPU usage exceeded threshold",
        fault_type="CPUHigh",
        duration_seconds=seconds,
        cpu_percent=92.0,
    )
    return {"service_name": SERVICE_NAME, "fault_type": "CPUHigh", "duration_seconds": seconds, "log": log}


@app.post("/inject/db-slow")
def inject_db_slow(duration: str = Query("90s")) -> dict[str, Any]:
    seconds = _parse_duration_seconds(duration)
    with _state_lock:
        _fault_state["db_slow_until"] = time.time() + seconds
    log = _write_log(
        "ERROR",
        "db_slow_query",
        "metadata sync query exceeded latency threshold",
        fault_type="DBSlowQuery",
        duration_seconds=seconds,
        latency_ms=3400,
    )
    return {"service_name": SERVICE_NAME, "fault_type": "DBSlowQuery", "duration_seconds": seconds, "log": log}


@app.post("/inject/redis-queue-backlog")
def inject_redis_queue_backlog(size: int = Query(200), duration: str = Query("90s")) -> dict[str, Any]:
    seconds = _parse_duration_seconds(duration)
    safe_size = max(0, size)
    with _state_lock:
        _fault_state["redis_backlog_size"] = safe_size
        _fault_state["redis_backlog_until"] = time.time() + seconds
    log = _write_log(
        "WARN",
        "redis_backlog",
        "redis queue backlog exceeded threshold",
        fault_type="RedisQueueBacklog",
        duration_seconds=seconds,
        queue_length=safe_size,
    )
    return {
        "service_name": SERVICE_NAME,
        "fault_type": "RedisQueueBacklog",
        "duration_seconds": seconds,
        "queue_length": safe_size,
        "log": log,
    }


@app.post("/inject/cache-miss")
def inject_cache_miss(duration: str = Query("90s")) -> dict[str, Any]:
    seconds = _parse_duration_seconds(duration)
    with _state_lock:
        _fault_state["cache_miss_until"] = time.time() + seconds
    log = _write_log(
        "WARN",
        "cache_miss",
        "cache miss ratio exceeded baseline",
        fault_type="CacheMiss",
        duration_seconds=seconds,
        cache_miss_ratio=0.95,
    )
    return {"service_name": SERVICE_NAME, "fault_type": "CacheMiss", "duration_seconds": seconds, "log": log}


@app.post("/inject/error-rate")
def inject_error_rate(rate: float = Query(0.3), duration: str = Query("90s")) -> dict[str, Any]:
    seconds = _parse_duration_seconds(duration)
    safe_rate = min(1.0, max(0.0, rate))
    with _state_lock:
        _fault_state["error_rate"] = safe_rate
        _fault_state["error_rate_until"] = time.time() + seconds
    log = _write_log(
        "ERROR",
        "error_rate",
        "service error rate exceeded baseline",
        fault_type="ErrorRate",
        duration_seconds=seconds,
        error_rate=safe_rate,
    )
    return {"service_name": SERVICE_NAME, "fault_type": "ErrorRate", "duration_seconds": seconds, "log": log}


@app.post("/inject/reset")
def reset_faults() -> dict[str, Any]:
    with _state_lock:
        _fault_state.update(
            {
                "cpu_high_until": 0.0,
                "db_slow_until": 0.0,
                "redis_backlog_size": 0,
                "redis_backlog_until": 0.0,
                "cache_miss_until": 0.0,
                "error_rate": 0.0,
                "error_rate_until": 0.0,
            }
        )
    log = _write_log("INFO", "fault_reset", "all injected faults reset")
    return {"service_name": SERVICE_NAME, "status": "reset", "log": log}
