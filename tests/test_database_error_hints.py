import unittest

from app.enterprise.database.error_hints import build_safe_sql_error_hint


class DatabaseErrorHintsTests(unittest.TestCase):
    def test_select_star_hint_points_to_context_tool_and_explicit_columns(self):
        hint = build_safe_sql_error_hint(
            "select_star_not_allowed",
            sql="select * from factory_access_events",
        )

        self.assertEqual(hint["reason"], "select_star_not_allowed")
        self.assertIn("禁止使用 SELECT *", hint["message"])
        self.assertIn("retrieve_database_context", hint["suggestion"])
        self.assertIn("显式列出", hint["suggestion"])
        self.assertEqual(hint["example_ids"], ["F01", "B01"])

    def test_permission_hint_uses_current_reason_names(self):
        database_hint = build_safe_sql_error_hint(
            "database_not_allowed",
            sql="select event_id from orders",
        )
        table_hint = build_safe_sql_error_hint(
            "database_table_denied",
            sql="select event_id from building_access_events",
        )
        column_hint = build_safe_sql_error_hint(
            "database_column_denied",
            sql="select event_id, badge_id from factory_access_events",
        )

        self.assertEqual(database_hint["reason"], "database_not_allowed")
        self.assertIn("不在受控 allowlist", database_hint["message"])
        self.assertIn("sandbox_sales / database_demo", database_hint["suggestion"])
        self.assertEqual(table_hint["reason"], "database_table_denied")
        self.assertIn("没有当前表的读取权限", table_hint["message"])
        self.assertIn("申请表级 read 权限", table_hint["suggestion"])
        self.assertEqual(column_hint["reason"], "database_column_denied")
        self.assertIn("没有当前字段的读取权限", column_hint["message"])
        self.assertIn("retrieve_database_context", column_hint["suggestion"])

    def test_all_current_safe_sql_reasons_have_hints(self):
        reasons = {
            "parse_failed",
            "multi_statement_not_allowed",
            "non_select_statement_not_allowed",
            "locking_select_not_allowed",
            "join_not_allowed",
            "subquery_not_allowed",
            "select_star_not_allowed",
            "function_not_allowed",
            "single_table_required",
            "unauthorized_table",
            "columns_required",
            "unauthorized_column",
            "limit_exceeds_max",
            "column_alias_not_allowed",
            "simple_column_select_required",
            "result_size_exceeds_max",
            "database_not_allowed",
            "database_table_denied",
            "database_column_denied",
            "sql_result_verification_failed",
        }

        for reason in sorted(reasons):
            with self.subTest(reason=reason):
                hint = build_safe_sql_error_hint(reason, sql="select * from factory_access_events")

                self.assertEqual(hint["reason"], reason)
                self.assertTrue(hint["message"])
                self.assertTrue(hint["suggestion"])


if __name__ == "__main__":
    unittest.main()
