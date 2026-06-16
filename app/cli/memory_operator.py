"""Local CLI for reviewing durable oncall memory candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from typing import Sequence

from app.models.memory_candidate import SessionHistoryMessage
from app.models.memory import MemoryStatus
from app.services.memory_candidate_service import MemoryCandidateService
from app.services.memory_review_service import MemoryReviewService
from app.services.memory_store import MemoryStore
from app.services.session_history_accessor import AIOpsGraphStateAccessor


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    store = MemoryStore(Path(args.store_path))
    review_service = MemoryReviewService(store=store)

    try:
        if args.command == "status":
            _print_json(store.get_validation_policy_status(owner_id=args.owner_id))
            return 0
        if args.command == "record-aiops-diagnosis":
            _print_json(
                store.record_aiops_diagnosis(
                    args.diagnosis_id,
                    owner_id=args.owner_id,
                    note=args.note,
                )
            )
            return 0
        if args.command == "preview-deprecate-owner-memories":
            _print_json(review_service.build_owner_deprecation_plan(owner_id=args.owner_id))
            return 0
        if args.command == "deprecate-owner-memories":
            if args.confirm_owner_id != args.owner_id:
                raise ValueError("confirm-owner-id must exactly match owner-id")
            records = review_service.deprecate_owner_memories(
                owner_id=args.owner_id,
                reviewer_id=args.reviewer_id,
                decision_note=args.note,
                decision_source="operator-cli",
            )
            _print_json(
                {
                    "owner_id": args.owner_id,
                    "rollback_action": "mark_memory_records_deprecated",
                    "destructive_delete": False,
                    "deprecated_count": len(records),
                    "records": [_queue_item(record) for record in records],
                    "p5_prompt_integration": "blocked_default_off",
                }
            )
            return 0
        if args.command == "list":
            statuses = _status_filter(args.status)
            records = review_service.list_review_queue(owner_id=args.owner_id, statuses=statuses)
            _print_json([_queue_item(record) for record in records])
            return 0
        if args.command == "show":
            record = store.get(args.memory_id)
            if record is None:
                raise ValueError(f"memory record not found: {args.memory_id}")
            _print_json(record.model_dump(mode="json"))
            return 0
        if args.command == "extract-rag-session":
            candidate_service = MemoryCandidateService(
                store=store,
                session_history_accessor=_JsonSessionHistoryAccessor(args.history_json),
            )
            result = candidate_service.extract_from_rag_session(args.session_id, owner_id=args.owner_id)
            _print_json(result.model_dump(mode="json"))
            return 0
        if args.command == "extract-aiops-session":
            candidate_service = MemoryCandidateService(
                store=store,
                aiops_state_accessor=_JsonAIOpsStateAccessor(args.state_json),
            )
            result = candidate_service.extract_from_aiops_session(args.session_id, owner_id=args.owner_id)
            _print_json(result.model_dump(mode="json"))
            return 0
        if args.command == "approve":
            record = review_service.approve_candidate(
                args.memory_id,
                reviewer_id=args.reviewer_id,
                decision_note=args.note,
                decision_source="operator-cli",
            )
            _print_json(record.model_dump(mode="json"))
            return 0
        if args.command == "reject":
            record = review_service.reject_candidate(
                args.memory_id,
                reviewer_id=args.reviewer_id,
                decision_note=args.note,
                decision_source="operator-cli",
            )
            _print_json(record.model_dump(mode="json"))
            return 0
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.memory_operator",
        description="Review sidecar durable memory candidates without exposing an admin API.",
    )
    parser.add_argument(
        "--store-path",
        default="./uploads/_metadata/oncall_memory.sqlite3",
        help="Path to the SQLite memory store.",
    )

    subparsers = parser.add_subparsers(dest="command")

    status_parser = subparsers.add_parser(
        "status",
        help="Show Gate A.2 validation milestone counters and blocked rollout state.",
    )
    status_parser.add_argument("--owner-id", default="default")

    record_diagnosis_parser = subparsers.add_parser(
        "record-aiops-diagnosis",
        help="Record one completed AIOps diagnosis toward the deprecate-if-not-validated milestone.",
    )
    record_diagnosis_parser.add_argument("diagnosis_id")
    record_diagnosis_parser.add_argument("--owner-id", default="default")
    record_diagnosis_parser.add_argument("--note", default="")

    preview_deprecate_parser = subparsers.add_parser(
        "preview-deprecate-owner-memories",
        help="Preview owner-scoped memory deprecation for a failed validation review.",
    )
    preview_deprecate_parser.add_argument("--owner-id", default="default")

    deprecate_parser = subparsers.add_parser(
        "deprecate-owner-memories",
        help="Mark all non-deprecated owner memories as deprecated after failed validation review.",
    )
    deprecate_parser.add_argument("--owner-id", default="default")
    deprecate_parser.add_argument("--confirm-owner-id", required=True)
    deprecate_parser.add_argument("--reviewer-id", required=True)
    deprecate_parser.add_argument("--note", required=True)

    list_parser = subparsers.add_parser("list", help="List candidate/conflict records awaiting review.")
    list_parser.add_argument("--owner-id", default="default")
    list_parser.add_argument(
        "--status",
        choices=["candidate", "conflict", "stale_suspect", "all"],
        default="all",
        help="Review queue status filter.",
    )

    show_parser = subparsers.add_parser("show", help="Show one memory record as JSON.")
    show_parser.add_argument("memory_id")

    extract_rag_parser = subparsers.add_parser(
        "extract-rag-session",
        help="Create a reviewed-later candidate summary from a normalized RAG session JSON snapshot.",
    )
    extract_rag_parser.add_argument("session_id")
    extract_rag_parser.add_argument("--owner-id", default="default")
    extract_rag_parser.add_argument(
        "--history-json",
        required=True,
        help="Path to a JSON file containing normalized RAG messages.",
    )

    extract_aiops_parser = subparsers.add_parser(
        "extract-aiops-session",
        help="Create a reviewed-later plan-template candidate from a normalized AIOps state JSON snapshot.",
    )
    extract_aiops_parser.add_argument("session_id")
    extract_aiops_parser.add_argument("--owner-id", default="default")
    extract_aiops_parser.add_argument(
        "--state-json",
        required=True,
        help="Path to a JSON file containing normalized AIOps graph-state values.",
    )

    approve_parser = subparsers.add_parser("approve", help="Promote a reviewed candidate to active.")
    _add_review_args(approve_parser)

    reject_parser = subparsers.add_parser("reject", help="Reject a candidate/conflict as deprecated.")
    _add_review_args(reject_parser)

    return parser


def _add_review_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("memory_id")
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--note", required=True)


def _status_filter(status: str) -> tuple[MemoryStatus, ...]:
    if status == "candidate":
        return (MemoryStatus.CANDIDATE,)
    if status == "conflict":
        return (MemoryStatus.CONFLICT,)
    if status == "stale_suspect":
        return (MemoryStatus.STALE_SUSPECT,)
    return (MemoryStatus.CANDIDATE, MemoryStatus.CONFLICT, MemoryStatus.STALE_SUSPECT)


def _queue_item(record) -> dict:
    return {
        "memory_id": record.memory_id,
        "owner_id": record.owner_id,
        "namespace": record.namespace,
        "memory_type": record.memory_type.value,
        "status": record.status.value,
        "summary": record.summary,
        "source": record.source,
        "updated_at": record.updated_at.isoformat(),
    }


def _print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))


class _JsonSessionHistoryAccessor:
    """Operator-supplied RAG history snapshot accessor for local extraction."""

    def __init__(self, path: str):
        self.path = Path(path)

    def get_history(self, session_id: str) -> list[SessionHistoryMessage]:
        del session_id
        payload = _read_json(self.path)
        messages = payload.get("messages", payload) if isinstance(payload, dict) else payload
        if not isinstance(messages, list):
            raise ValueError("history JSON must be a list or an object with a messages list")

        normalized: list[SessionHistoryMessage] = []
        for index, item in enumerate(messages):
            if not isinstance(item, dict):
                raise ValueError("history messages must be JSON objects")
            normalized.append(
                SessionHistoryMessage(
                    role=item.get("role"),
                    content=str(item.get("content", "")),
                    message_index=int(item.get("message_index", index)),
                    timestamp=item.get("timestamp"),
                )
            )
        return normalized


class _JsonAIOpsStateAccessor:
    """Operator-supplied AIOps graph-state snapshot accessor for local extraction."""

    def __init__(self, path: str):
        self.path = Path(path)

    def get_state(self, session_id: str):
        payload = _read_json(self.path)
        values = payload.get("values", payload) if isinstance(payload, dict) else None
        if not isinstance(values, dict):
            raise ValueError("AIOps state JSON must be an object or an object with a values field")
        return AIOpsGraphStateAccessor.from_values(session_id, values)


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise ValueError(f"JSON file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON file {path}: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
