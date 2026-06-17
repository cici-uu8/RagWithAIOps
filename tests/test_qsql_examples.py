import unittest

from app.enterprise.database.qsql_examples import QSqlExampleRegistry


class QSqlExampleRegistryTests(unittest.TestCase):
    def test_loads_stage2_door_access_examples(self):
        registry = QSqlExampleRegistry()

        self.assertEqual(len(registry.examples), 15)
        self.assertEqual(registry.examples[0].example_id, "F01")
        self.assertEqual(registry.examples[-1].example_id, "B07")
        self.assertTrue(all(example.database_id == "sandbox_sales" for example in registry.examples))
        self.assertTrue(all("raw_device_payload" not in example.sql for example in registry.examples))

    def test_search_matches_factory_building_employee_and_night_queries(self):
        registry = QSqlExampleRegistry()

        factory_results = registry.search("查询最近进厂记录", limit=3)
        employee_results = registry.search("员工 E001 轨迹", limit=3)
        night_results = registry.search("夜间 门禁 候选", limit=3)

        self.assertIn("F01", [example.example_id for example in factory_results])
        self.assertIn("F07", [example.example_id for example in employee_results])
        self.assertIn("F05", [example.example_id for example in night_results])


if __name__ == "__main__":
    unittest.main()
