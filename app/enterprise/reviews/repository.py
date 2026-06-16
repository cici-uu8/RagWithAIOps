"""Human review repositories for Enterprise 2.0 F6."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol

from app.config import config
from app.enterprise.reviews.models import HumanReviewRequest, ReviewStatus


class HumanReviewRepository(Protocol):
    def create(self, review: HumanReviewRequest) -> HumanReviewRequest:
        ...

    def get(self, review_id: str) -> HumanReviewRequest | None:
        ...

    def get_by_task(self, task_id: str) -> HumanReviewRequest | None:
        ...

    def list_pending(self) -> list[HumanReviewRequest]:
        ...

    def update(self, review: HumanReviewRequest) -> HumanReviewRequest:
        ...


class InMemoryHumanReviewRepository:
    def __init__(self):
        self._reviews: dict[str, HumanReviewRequest] = {}

    def create(self, review: HumanReviewRequest) -> HumanReviewRequest:
        self._reviews[review.review_id] = review
        return review

    def get(self, review_id: str) -> HumanReviewRequest | None:
        return self._reviews.get(review_id)

    def get_by_task(self, task_id: str) -> HumanReviewRequest | None:
        matches = [
            review
            for review in self._reviews.values()
            if review.task_id == task_id
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda review: review.created_at)[-1]

    def list_pending(self) -> list[HumanReviewRequest]:
        return sorted(
            [
                review
                for review in self._reviews.values()
                if review.status == ReviewStatus.PENDING
            ],
            key=lambda review: review.created_at,
        )

    def update(self, review: HumanReviewRequest) -> HumanReviewRequest:
        self._reviews[review.review_id] = review
        return review


class SQLiteHumanReviewRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or config.enterprise_human_review_sqlite_path)
        self._initialized = False

    def create(self, review: HumanReviewRequest) -> HumanReviewRequest:
        return self.update(review)

    def get(self, review_id: str) -> HumanReviewRequest | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            row = connection.execute(
                """
                SELECT review_json
                FROM enterprise_human_reviews
                WHERE review_id = ?
                """,
                (review_id,),
            ).fetchone()
        if row is None:
            return None
        return HumanReviewRequest.model_validate(json.loads(row[0]))

    def get_by_task(self, task_id: str) -> HumanReviewRequest | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            row = connection.execute(
                """
                SELECT review_json
                FROM enterprise_human_reviews
                WHERE task_id = ?
                ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()
        if not row:
            return None
        return HumanReviewRequest.model_validate(json.loads(row[-1][0]))

    def list_pending(self) -> list[HumanReviewRequest]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            rows = connection.execute(
                """
                SELECT review_json
                FROM enterprise_human_reviews
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (ReviewStatus.PENDING.value,),
            ).fetchall()
        return [HumanReviewRequest.model_validate(json.loads(row[0])) for row in rows]

    def update(self, review: HumanReviewRequest) -> HumanReviewRequest:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO enterprise_human_reviews (
                        review_id, task_id, trace_id, user_id, status, created_at, review_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review.review_id,
                        review.task_id,
                        review.trace_id,
                        review.user_id,
                        review.status.value,
                        review.created_at.isoformat(),
                        review.model_dump_json(),
                    ),
                )
        return review

    def _init_schema(self, connection: sqlite3.Connection) -> None:
        if self._initialized:
            return
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS enterprise_human_reviews (
                review_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                review_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enterprise_human_reviews_task
            ON enterprise_human_reviews(task_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enterprise_human_reviews_status
            ON enterprise_human_reviews(status)
            """
        )
        self._initialized = True
