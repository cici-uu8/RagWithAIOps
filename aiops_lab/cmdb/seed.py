import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "aiops_context.db"
SCHEMA_PATH = ROOT / "schema.sql"


SERVICES = [
    (
        "data-sync-service",
        "platform-team",
        "alice",
        "lab",
        '["mysql", "redis", "metadata-store"]',
        "https://runbooks.local/data-sync-service",
    ),
    (
        "order-service",
        "order-team",
        "bob",
        "lab",
        '["mysql", "inventory-service"]',
        "https://runbooks.local/order-service",
    ),
    (
        "inventory-service",
        "supply-team",
        "carol",
        "lab",
        '["redis", "mysql"]',
        "https://runbooks.local/inventory-service",
    ),
]

DEPLOYMENTS = [
    (
        "dep-data-sync-001",
        "data-sync-service",
        "v1.2.3",
        "2026-06-02T09:30:00+08:00",
        "alice",
        "metadata sync worker concurrency tuning",
    ),
    (
        "dep-order-001",
        "order-service",
        "v2.4.0",
        "2026-06-02T08:20:00+08:00",
        "bob",
        "order query path release",
    ),
]

TICKETS = [
    (
        "inc-data-sync-cpu-001",
        "data-sync-service",
        "CPUHigh",
        "CPU-bound metadata sync loop after concurrency increase",
        "limit worker concurrency and restart data sync workers",
        "2026-05-20T10:00:00+08:00",
    ),
    (
        "inc-data-sync-db-001",
        "data-sync-service",
        "DBSlowQuery",
        "metadata sync query missed index on source_system",
        "add index and reduce sync batch size",
        "2026-05-22T14:00:00+08:00",
    ),
    (
        "inc-inventory-redis-001",
        "inventory-service",
        "RedisQueueBacklog",
        "cache rebuild job filled reservation queue faster than consumers",
        "pause rebuild job and increase consumer workers",
        "2026-05-24T11:30:00+08:00",
    ),
]


def seed(db_path: Path = DB_PATH) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.executemany("INSERT OR REPLACE INTO services VALUES (?, ?, ?, ?, ?, ?)", SERVICES)
        conn.executemany("INSERT OR REPLACE INTO deployments VALUES (?, ?, ?, ?, ?, ?)", DEPLOYMENTS)
        conn.executemany("INSERT OR REPLACE INTO tickets VALUES (?, ?, ?, ?, ?, ?)", TICKETS)
    return db_path


if __name__ == "__main__":
    print(seed())
