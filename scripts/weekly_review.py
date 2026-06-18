#!/usr/bin/env python3
"""Generate a lightweight weekly production-mainline review report.

The script intentionally avoids external dependencies so Week0 can verify the
review loop before broader infrastructure is in place.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


@dataclass(frozen=True)
class FileCheck:
    path: str
    required: bool = True


REQUIRED_FILES = [
    FileCheck("docs/plan_registry.md"),
    FileCheck("docs/plan_timeline_report.md"),
    FileCheck("docs/external_dependencies.md"),
    FileCheck("docs/external_blocked_registry.md"),
    FileCheck("docs/code_review_checklist.md"),
    FileCheck("docs/risk_triggers.md"),
    FileCheck("docs/scorecards/scorecard_template.md"),
    FileCheck("docs/baselines/baseline_template.md"),
    FileCheck("docs/compare-reports/compare_template.md"),
    FileCheck("docs/weekly_reviews/weekly_review_template.md"),
]

ACTIVE_PLANS = [
    "Week0_准备清单.md",
    "Month1_执行清单.md",
    "Month2_执行清单.md",
    "Month3_执行清单.md",
    "开发主控文档.md",
]


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            timeout=20,
        )
    except Exception as exc:  # pragma: no cover - defensive report path
        return f"error: {exc}"
    output = (completed.stdout or completed.stderr or "").strip()
    return output or f"exit={completed.returncode}"


def _checkbox_counts(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    total = 0
    done = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*-\s+\[( |x|X)\]", line)
        if not match:
            continue
        total += 1
        if match.group(1).lower() == "x":
            done += 1
    return done, total


def _file_status_table() -> list[str]:
    rows = ["| File | Status |", "|---|---|"]
    for item in REQUIRED_FILES:
        exists = (ROOT / item.path).exists()
        rows.append(f"| `{item.path}` | {'present' if exists else 'missing'} |")
    return rows


def _plan_progress_table() -> list[str]:
    rows = ["| Plan | Done | Total | Percent |", "|---|---:|---:|---:|"]
    for plan in ACTIVE_PLANS:
        done, total = _checkbox_counts(ROOT / plan)
        percent = f"{(done / total * 100):.1f}%" if total else "n/a"
        rows.append(f"| `{plan}` | {done} | {total} | {percent} |")
    return rows


def _artifact_inventory() -> list[str]:
    rows = ["| Artifact Type | Count | Latest Examples |", "|---|---:|---|"]
    for label, rel in [
        ("scorecards", "docs/scorecards"),
        ("baselines", "docs/baselines"),
        ("compare reports", "docs/compare-reports"),
        ("weekly reviews", "docs/weekly_reviews"),
        ("milestones", "docs/milestones"),
    ]:
        directory = ROOT / rel
        files = sorted(p for p in directory.glob("*.md")) if directory.exists() else []
        examples = ", ".join(f"`{p.name}`" for p in files[-3:]) if files else ""
        rows.append(f"| {label} | {len(files)} | {examples} |")
    return rows


def generate_weekly_report() -> Path:
    now = datetime.now()
    report_dir = DOCS / "weekly_reviews"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"weekly_review_auto_{now:%Y%m%d_%H%M%S}.md"

    git_status = _run(["git", "status", "--short", "--branch"])
    health = _run(["curl", "-fsS", "http://127.0.0.1:9900/health"])

    lines = [
        "# Weekly Review Auto Report",
        "",
        f"Generated: {now:%Y-%m-%d %H:%M:%S}",
        "",
        "## Governance Files",
        "",
        *_file_status_table(),
        "",
        "## Active Plan Checkbox Progress",
        "",
        *_plan_progress_table(),
        "",
        "## Evidence Artifact Inventory",
        "",
        *_artifact_inventory(),
        "",
        "## Local Runtime Snapshot",
        "",
        "```text",
        health,
        "```",
        "",
        "## Git Snapshot",
        "",
        "```text",
        git_status,
        "```",
        "",
        "## Gate Note",
        "",
        "This report is evidence only. Phase advancement still requires the active checklist gate and compare/scorecard decision.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(report_path.relative_to(ROOT))
    return report_path


if __name__ == "__main__":
    generate_weekly_report()
