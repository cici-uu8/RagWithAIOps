"""SQL result verifier for sandbox safe_select outputs."""

from __future__ import annotations

from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.verifiers.base import BaseVerifier
from app.enterprise.verifiers.models import (
    VerificationFinding,
    VerificationResult,
    VerificationStatus,
)


class SqlResultVerifier(BaseVerifier):
    name = "SqlResultVerifier"

    def verify(self, context: RequestContext, payload: dict[str, Any]) -> VerificationResult:
        del context
        result = payload.get("result") or {}
        authorized_columns = {_normalize(item) for item in payload.get("authorized_columns", [])}
        columns = [_normalize(item) for item in result.get("columns", [])]
        findings: list[VerificationFinding] = []

        if result.get("safe_sql_verified") is not True:
            findings.append(
                self._finding(
                    "sql_result_not_safe_sql_verified",
                    "SQL 结果缺少 SafeSqlKernel 验证来源。",
                )
            )

        if not columns:
            findings.append(
                self._finding(
                    "sql_result_columns_missing",
                    "SQL 结果缺少列清单，无法执行列级权限自检。",
                )
            )
        elif authorized_columns:
            denied_columns = [column for column in columns if column not in authorized_columns]
            if denied_columns:
                findings.append(
                    self._finding(
                        "sql_result_column_not_authorized",
                        "SQL 结果包含未授权列。",
                        metadata={
                            "denied_columns": denied_columns,
                            "authorized_columns": sorted(authorized_columns),
                        },
                    )
                )

        if findings:
            return self._result(
                VerificationStatus.FAILED,
                findings,
                metadata={"column_count": len(columns)},
            )
        return self._result(
            VerificationStatus.PASSED,
            metadata={"column_count": len(columns)},
        )


def _normalize(value: Any) -> str:
    return str(value).strip().strip('"`[]').lower()
