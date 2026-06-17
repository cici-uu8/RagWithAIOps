"""Structured Q-SQL examples for the door-access sandbox."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QSqlExample:
    example_id: str
    question: str
    sql: str
    table_name: str
    database_id: str
    explanation: str
    tags: tuple[str, ...]


class QSqlExampleRegistry:
    def __init__(self, examples: list[QSqlExample] | None = None):
        self.examples = examples or _default_examples()

    def search(self, query: str, *, limit: int = 3) -> list[QSqlExample]:
        normalized_query = _normalize(query)
        scored: list[tuple[int, int, QSqlExample]] = []
        for index, example in enumerate(self.examples):
            score = self._score(example, normalized_query)
            if score > 0:
                scored.append((score, -index, example))
        scored.sort(reverse=True)
        return [example for _score, _index, example in scored[:limit]]

    def _score(self, example: QSqlExample, normalized_query: str) -> int:
        score = 0
        for tag in example.tags:
            if _normalize(tag) in normalized_query:
                score += 3
        for keyword in _keywords(example.question):
            if keyword in normalized_query:
                score += 2
        for keyword in _keywords(example.explanation):
            if keyword in normalized_query:
                score += 1
        return score


def _default_examples() -> list[QSqlExample]:
    return [
        QSqlExample(
            example_id="F01",
            question="查询最近 10 次进厂记录",
            sql=(
                "select event_id, employee_id, employee_name, department_name, gate_name, event_time "
                "from factory_access_events where direction = 'entry' order by event_time desc limit 10"
            ),
            table_name="factory_access_events",
            database_id="sandbox_sales",
            explanation="进厂事件明细，employee_name 会按 name mask 脱敏。",
            tags=("factory", "进厂", "entry", "recent", "最近", "厂门"),
        ),
        QSqlExample(
            example_id="F02",
            question="查询最近 10 次出厂记录",
            sql=(
                "select event_id, employee_id, employee_name, department_name, gate_name, event_time "
                "from factory_access_events where direction = 'exit' order by event_time desc limit 10"
            ),
            table_name="factory_access_events",
            database_id="sandbox_sales",
            explanation="出厂事件明细，不使用聚合函数。",
            tags=("factory", "出厂", "exit", "recent", "最近", "厂门"),
        ),
        QSqlExample(
            example_id="F03",
            question="查询东门的进出厂记录",
            sql=(
                "select event_id, employee_id, employee_name, department_name, direction, gate_name, event_time "
                "from factory_access_events where gate_name = '东门' order by event_time desc limit 20"
            ),
            table_name="factory_access_events",
            database_id="sandbox_sales",
            explanation="厂门维度明细筛选。",
            tags=("factory", "东门", "gate", "厂门", "进出厂"),
        ),
        QSqlExample(
            example_id="F04",
            question="查询研发部员工的进出厂记录",
            sql=(
                "select event_id, employee_id, employee_name, direction, gate_name, event_time "
                "from factory_access_events where department_name = '研发部' order by event_time desc limit 20"
            ),
            table_name="factory_access_events",
            database_id="sandbox_sales",
            explanation="部门维度进出厂明细。",
            tags=("factory", "研发部", "department", "部门", "进出厂"),
        ),
        QSqlExample(
            example_id="F05",
            question="查询 2026-06-17 22:00 后的进出厂记录",
            sql=(
                "select event_id, employee_id, employee_name, department_name, direction, gate_name, event_time "
                "from factory_access_events where event_time >= '2026-06-17 22:00:00' "
                "order by event_time desc limit 20"
            ),
            table_name="factory_access_events",
            database_id="sandbox_sales",
            explanation="夜间访问候选明细，时间判断不使用函数。",
            tags=("factory", "夜间", "凌晨", "22:00", "event_time", "异常", "候选"),
        ),
        QSqlExample(
            example_id="F06",
            question="查询北门的进出厂记录",
            sql=(
                "select event_id, employee_id, employee_name, department_name, direction, gate_name, event_time "
                "from factory_access_events where gate_name = '北门' order by event_time desc limit 20"
            ),
            table_name="factory_access_events",
            database_id="sandbox_sales",
            explanation="北门进出厂明细。",
            tags=("factory", "北门", "gate", "厂门", "进出厂"),
        ),
        QSqlExample(
            example_id="F07",
            question="查询员工 E001 的进出厂轨迹",
            sql=(
                "select event_id, employee_id, employee_name, department_name, direction, gate_name, event_time "
                "from factory_access_events where employee_id = 'E001' order by event_time desc limit 10"
            ),
            table_name="factory_access_events",
            database_id="sandbox_sales",
            explanation="员工维度进出厂轨迹。",
            tags=("factory", "员工", "employee", "E001", "轨迹", "进出厂"),
        ),
        QSqlExample(
            example_id="F08",
            question="查询员工 E001 的门禁卡号脱敏展示",
            sql=(
                "select event_id, employee_id, employee_name, badge_id, gate_name, event_time "
                "from factory_access_events where employee_id = 'E001' order by event_time desc limit 10"
            ),
            table_name="factory_access_events",
            database_id="sandbox_sales",
            explanation="badge_id 会按 badge mask 脱敏。",
            tags=("factory", "员工", "employee", "E001", "badge", "门禁卡", "脱敏"),
        ),
        QSqlExample(
            example_id="B01",
            question="查询流数楼的进出楼记录",
            sql=(
                "select event_id, employee_id, employee_name, department_name, floor_name, access_point_name, event_time "
                "from building_access_events where building_name = '流数楼' order by event_time desc limit 20"
            ),
            table_name="building_access_events",
            database_id="sandbox_sales",
            explanation="楼栋维度进出楼明细。",
            tags=("building", "流数楼", "进楼", "出楼", "楼栋", "floor"),
        ),
        QSqlExample(
            example_id="B02",
            question="查询数据中心 B1 门禁记录",
            sql=(
                "select event_id, employee_id, employee_name, department_name, building_name, floor_name, "
                "direction, access_point_name, event_time from building_access_events "
                "where building_name = '数据中心' order by event_time desc limit 20"
            ),
            table_name="building_access_events",
            database_id="sandbox_sales",
            explanation="数据中心楼栋门禁明细。",
            tags=("building", "数据中心", "B1", "楼栋", "设备", "门禁"),
        ),
        QSqlExample(
            example_id="B03",
            question="查询运营楼凌晨门禁记录的明细候选",
            sql=(
                "select event_id, employee_id, employee_name, department_name, building_name, floor_name, "
                "direction, access_point_name, event_time from building_access_events "
                "where building_name = '运营楼' order by event_time desc limit 20"
            ),
            table_name="building_access_events",
            database_id="sandbox_sales",
            explanation="凌晨门禁候选明细。",
            tags=("building", "运营楼", "凌晨", "夜间", "候选", "门禁"),
        ),
        QSqlExample(
            example_id="B04",
            question="查询研发部员工在楼栋内的门禁记录",
            sql=(
                "select event_id, employee_id, employee_name, department_name, building_name, floor_name, "
                "direction, event_time from building_access_events "
                "where department_name = '研发部' order by event_time desc limit 20"
            ),
            table_name="building_access_events",
            database_id="sandbox_sales",
            explanation="部门维度楼栋门禁明细。",
            tags=("building", "研发部", "department", "部门", "楼栋", "门禁"),
        ),
        QSqlExample(
            example_id="B05",
            question="查询员工 E005 的楼栋门禁轨迹",
            sql=(
                "select event_id, employee_id, employee_name, building_name, floor_name, direction, "
                "access_point_name, event_time from building_access_events "
                "where employee_id = 'E005' order by event_time desc limit 10"
            ),
            table_name="building_access_events",
            database_id="sandbox_sales",
            explanation="员工维度楼栋门禁轨迹。",
            tags=("building", "员工", "employee", "E005", "轨迹", "楼栋"),
        ),
        QSqlExample(
            example_id="B06",
            question="查询 5F 实验室门禁点记录",
            sql=(
                "select event_id, employee_id, employee_name, building_name, floor_name, direction, "
                "access_point_name, event_time from building_access_events "
                "where access_point_name = '5F实验室' order by event_time desc limit 20"
            ),
            table_name="building_access_events",
            database_id="sandbox_sales",
            explanation="门禁点维度明细。",
            tags=("building", "5F", "实验室", "access_point", "门禁点"),
        ),
        QSqlExample(
            example_id="B07",
            question="查询数据中心设备字段脱敏展示",
            sql=(
                "select event_id, employee_id, employee_name, building_name, device_id, event_time "
                "from building_access_events where building_name = '数据中心' order by event_time desc limit 10"
            ),
            table_name="building_access_events",
            database_id="sandbox_sales",
            explanation="device_id 会按 redact mask 脱敏。",
            tags=("building", "数据中心", "device", "设备", "脱敏"),
        ),
    ]


def _normalize(value: str) -> str:
    return value.strip().lower()


def _keywords(value: str) -> list[str]:
    normalized = _normalize(value)
    chunks = normalized.replace("，", " ").replace("。", " ").replace(",", " ").split()
    keywords = [chunk for chunk in chunks if chunk]
    for token in ("进厂", "出厂", "进出厂", "门禁", "轨迹", "夜间", "凌晨", "员工", "部门"):
        if token in normalized:
            keywords.append(token)
    return keywords
