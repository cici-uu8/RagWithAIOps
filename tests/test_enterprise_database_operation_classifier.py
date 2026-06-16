import unittest

from app.enterprise.database.operation_classifier import classify_sql_operation


class EnterpriseDatabaseOperationClassifierTests(unittest.TestCase):
    def classify(self, sql: str):
        return classify_sql_operation(
            sql,
            database_id="sandbox_sales",
            dialect="mysql",
        )

    def assert_classification(
        self,
        sql: str,
        *,
        operation_level: str,
        operation_type: str,
        requires_confirmation: bool,
        is_delete_like: bool = False,
        denied_reason: str | None = None,
    ):
        result = self.classify(sql)

        self.assertEqual(result.database_id, "sandbox_sales")
        self.assertEqual(result.operation_level, operation_level)
        self.assertEqual(result.operation_type, operation_type)
        self.assertEqual(result.requires_confirmation, requires_confirmation)
        self.assertEqual(result.is_delete_like, is_delete_like)
        self.assertEqual(result.denied_reason, denied_reason)

    def test_classifies_read_and_metadata_operations(self):
        result = self.classify("select order_id from orders where total_amount > 10")

        self.assertEqual(result.operation_level, "L1")
        self.assertEqual(result.operation_type, "select")
        self.assertEqual(result.tables, ["orders"])
        self.assertEqual(result.columns, ["order_id", "total_amount"])
        self.assertFalse(result.requires_confirmation)
        self.assertFalse(result.is_delete_like)

        self.assert_classification(
            "explain select order_id from orders",
            operation_level="L2",
            operation_type="metadata",
            requires_confirmation=False,
        )

    def test_classifies_show_and_describe_as_metadata_operations(self):
        self.assert_classification(
            "show tables",
            operation_level="L2",
            operation_type="metadata",
            requires_confirmation=False,
        )

        result = self.classify("show columns from orders")
        self.assertEqual(result.operation_level, "L2")
        self.assertEqual(result.operation_type, "metadata")
        self.assertEqual(result.tables, ["orders"])
        self.assertFalse(result.requires_confirmation)

        result = self.classify("describe orders")
        self.assertEqual(result.operation_level, "L2")
        self.assertEqual(result.operation_type, "metadata")
        self.assertEqual(result.tables, ["orders"])
        self.assertFalse(result.requires_confirmation)

    def test_classifies_write_operations_as_l3_direct_operations(self):
        result = self.classify(
            "insert into orders (order_id, total_amount) values (1001, 10)",
        )
        self.assertEqual(result.operation_level, "L3")
        self.assertEqual(result.operation_type, "insert")
        self.assertFalse(result.requires_confirmation)
        self.assertEqual(result.columns, ["order_id", "total_amount"])

        self.assert_classification(
            "update orders set total_amount = 0 where order_id = 1001",
            operation_level="L3",
            operation_type="update",
            requires_confirmation=False,
        )

    def test_classifies_delete_like_operations_as_l4_confirmation_required(self):
        cases = [
            ("delete from orders where order_id = 1001", "delete"),
            ("truncate table orders", "truncate"),
            ("drop table orders", "drop_table"),
            ("alter table orders drop column internal_note", "alter_table_drop_column"),
        ]

        for sql, operation_type in cases:
            with self.subTest(sql=sql):
                self.assert_classification(
                    sql,
                    operation_level="L4",
                    operation_type=operation_type,
                    requires_confirmation=True,
                    is_delete_like=True,
                )

    def test_classifies_non_delete_ddl_as_l5_direct_operations(self):
        result = self.classify("create table archived_orders (order_id bigint)")
        self.assertEqual(result.operation_level, "L5")
        self.assertEqual(result.operation_type, "create_table")
        self.assertFalse(result.requires_confirmation)
        self.assertEqual(result.columns, ["order_id"])

        result = self.classify("alter table orders add column status varchar(20)")
        self.assertEqual(result.operation_level, "L5")
        self.assertEqual(result.operation_type, "alter_table")
        self.assertFalse(result.requires_confirmation)
        self.assertEqual(result.columns, ["status"])
        self.assert_classification(
            "create index idx_orders_total on orders (total_amount)",
            operation_level="L5",
            operation_type="create_index",
            requires_confirmation=False,
        )
        self.assert_classification(
            "drop index idx_orders_total on orders",
            operation_level="L5",
            operation_type="drop_index",
            requires_confirmation=False,
        )
        self.assert_classification(
            "alter table orders rename column status to state",
            operation_level="L5",
            operation_type="alter_table",
            requires_confirmation=False,
        )
        result = self.classify("alter table orders modify column status varchar(40)")
        self.assertEqual(result.operation_level, "L5")
        self.assertEqual(result.operation_type, "alter_table")
        self.assertFalse(result.requires_confirmation)
        self.assertEqual(result.columns, ["status"])
        self.assert_classification(
            "rename table orders to archived_orders",
            operation_level="L5",
            operation_type="rename_table",
            requires_confirmation=False,
        )

    def test_classifies_permission_management_sql_outside_database_confirmation_flow(self):
        for sql, operation_type in [
            ("grant select on sales.orders to readonly_user", "grant"),
            ("revoke select on sales.orders from readonly_user", "revoke"),
        ]:
            with self.subTest(sql=sql):
                self.assert_classification(
                    sql,
                    operation_level="M1",
                    operation_type=operation_type,
                    requires_confirmation=False,
                    denied_reason="permission_management_not_database_operation",
                )

    def test_parse_failures_and_multi_statement_sql_are_denied(self):
        self.assert_classification(
            "select from",
            operation_level="unknown",
            operation_type="unknown",
            requires_confirmation=False,
            denied_reason="parse_failed",
        )
        self.assert_classification(
            "select order_id from orders; delete from orders",
            operation_level="unknown",
            operation_type="unknown",
            requires_confirmation=False,
            denied_reason="multi_statement_not_allowed",
        )
