# 数据库门禁场景 Q-SQL 示例

日期: 2026-06-16

状态: 数据库能力升级 v2 Stage 2 文档版已完成。本文件只提供门禁场景自然语言问题到安全 SQL 的示例，不新增代码、不新增 route、不改变 `SafeSqlKernel` / `ToolGateway` / `DatabasePermissionFilter` 边界。

## 使用边界

当前默认数据库仍为 `sandbox_sales`，可用表来自 Stage 1:

- `factory_access_events`: 员工进出厂门记录。
- `building_access_events`: 员工进出楼栋、楼层、门禁点记录。

当前安全 SQL 约束:

- 只能执行单表 `SELECT`。
- 必须显式列出字段，禁止 `SELECT *`。
- 禁止 JOIN、子查询、函数和聚合函数，包括 `COUNT`、`SUM`、`AVG`、`strftime`。
- 查询必须只引用 allowlist 字段。
- 建议显式写 `LIMIT`，且不得超过当前上限。
- `employee_name`、`badge_id`、`device_id` 等敏感字段会按 registry policy 脱敏。
- `raw_device_payload` 为禁止列，不应出现在 SQL 中。

因此，"统计员工进出次数"、"按部门汇总"、"计算异常比例" 这类问题在当前阶段应先查询明细，再由应用层或人工 review 做统计；不要在 SQL 中使用聚合函数。

## 示例总览

| 编号 | 用户问题 | 表 | 模式 | 可执行验证 |
|---|---|---|---|---|
| F01 | 查询最近 10 次进厂记录 | `factory_access_events` | 方向筛选 | 已通过 `SafeSqlKernel.safe_select` |
| F02 | 查询最近 10 次出厂记录 | `factory_access_events` | 方向筛选 | 已通过 |
| F03 | 查询东门的进出厂记录 | `factory_access_events` | 厂门筛选 | 已通过 |
| F04 | 查询研发部员工的进出厂记录 | `factory_access_events` | 部门筛选 | 已通过 |
| F05 | 查询 2026-06-17 22:00 后的进出厂记录 | `factory_access_events` | 夜间候选 | 已通过 |
| F06 | 查询北门的进出厂记录 | `factory_access_events` | 厂门筛选 | 已通过 |
| F07 | 查询员工 E001 的进出厂轨迹 | `factory_access_events` | 员工筛选 | 已通过 |
| F08 | 查询员工 E001 的门禁卡脱敏展示 | `factory_access_events` | 敏感字段脱敏 | 已通过 |
| B01 | 查询流数楼的进出楼记录 | `building_access_events` | 楼栋筛选 | 已通过 |
| B02 | 查询数据中心 B1 门禁记录 | `building_access_events` | 楼栋/设备场景 | 已通过 |
| B03 | 查询运营楼凌晨门禁记录的明细候选 | `building_access_events` | 楼栋筛选 | 已通过 |
| B04 | 查询研发部员工在楼栋内的门禁记录 | `building_access_events` | 部门筛选 | 已通过 |
| B05 | 查询员工 E005 的楼栋门禁轨迹 | `building_access_events` | 员工筛选 | 已通过 |
| B06 | 查询 5F 实验室门禁点记录 | `building_access_events` | 门禁点筛选 | 已通过 |
| B07 | 查询数据中心设备字段脱敏展示 | `building_access_events` | 敏感字段脱敏 | 已通过 |

## Factory Access Examples

### F01. 最近进厂记录

用户问题:

> 查询最近 10 次进厂记录

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, gate_name, event_time
from factory_access_events
where direction = 'entry'
order by event_time desc
limit 10
```

说明: `employee_name` 会按 `name` mask 脱敏。该查询适合作为进厂事件明细列表，统计数量应在应用层完成。

### F02. 最近出厂记录

用户问题:

> 查询最近 10 次出厂记录

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, gate_name, event_time
from factory_access_events
where direction = 'exit'
order by event_time desc
limit 10
```

说明: 用于查看出厂明细，不使用 `COUNT(*)`。

### F03. 东门进出厂记录

用户问题:

> 查询东门的进出厂记录

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, direction, gate_name, event_time
from factory_access_events
where gate_name = '东门'
order by event_time desc
limit 20
```

说明: 当前示例只筛选一个字段。若后续要表达"东门 + 今天 + 出厂"，应由 Stage 3 context 工具或应用层拆解，不能在当前示例里直接假设多条件查询已稳定支持。

### F04. 研发部进出厂记录

用户问题:

> 查询研发部员工的进出厂记录

安全 SQL:

```sql
select event_id, employee_id, employee_name, direction, gate_name, event_time
from factory_access_events
where department_name = '研发部'
order by event_time desc
limit 20
```

说明: 适合部门级 review。部门粒度统计同样应基于返回明细在应用层完成。

### F05. 夜间进出厂候选

用户问题:

> 查询 2026-06-17 22:00 后的进出厂记录，作为夜间访问候选

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, direction, gate_name, event_time
from factory_access_events
where event_time >= '2026-06-17 22:00:00'
order by event_time desc
limit 20
```

说明: 这是夜间异常候选的明细入口。当前 `SafeSqlKernel` 不应使用 `strftime()` 或复合时间窗口函数。

### F06. 北门进出厂记录

用户问题:

> 查询北门的进出厂记录

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, direction, gate_name, event_time
from factory_access_events
where gate_name = '北门'
order by event_time desc
limit 20
```

说明: 可用于厂门维度的明细巡检。

### F07. 员工 E001 进出厂轨迹

用户问题:

> 查询员工 E001 的进出厂轨迹

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, direction, gate_name, event_time
from factory_access_events
where employee_id = 'E001'
order by event_time desc
limit 10
```

说明: 员工编号不是敏感 mask 字段，但姓名仍会脱敏。

### F08. 门禁卡号脱敏展示

用户问题:

> 查询员工 E001 的门禁卡号脱敏展示

安全 SQL:

```sql
select event_id, employee_id, employee_name, badge_id, gate_name, event_time
from factory_access_events
where employee_id = 'E001'
order by event_time desc
limit 10
```

说明: `badge_id` 允许查询但会按 `badge` mask 脱敏；不要查询 `raw_device_payload`。

## Building Access Examples

### B01. 流数楼门禁记录

用户问题:

> 查询流数楼的进出楼记录

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, floor_name, access_point_name, event_time
from building_access_events
where building_name = '流数楼'
order by event_time desc
limit 20
```

说明: 返回流数楼相关明细。若需要"流数楼 3F + entry"，后续应通过 context tool 或 UI 参数约束生成安全 SQL。

### B02. 数据中心门禁记录

用户问题:

> 查询数据中心 B1 门禁记录

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, building_name, floor_name, direction, access_point_name, event_time
from building_access_events
where building_name = '数据中心'
order by event_time desc
limit 20
```

说明: 当前示例用楼栋筛选，返回数据中心门禁明细。

### B03. 运营楼凌晨门禁候选

用户问题:

> 查询运营楼凌晨门禁记录的明细候选

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, building_name, floor_name, direction, access_point_name, event_time
from building_access_events
where building_name = '运营楼'
order by event_time desc
limit 20
```

说明: 当前安全 SQL 示例不使用多条件时间窗口；凌晨判断由应用层根据 `event_time` 明细完成。

### B04. 研发部楼栋门禁记录

用户问题:

> 查询研发部员工在楼栋内的门禁记录

安全 SQL:

```sql
select event_id, employee_id, employee_name, department_name, building_name, floor_name, direction, event_time
from building_access_events
where department_name = '研发部'
order by event_time desc
limit 20
```

说明: 可用于部门维度的楼栋访问 review。

### B05. 员工 E005 楼栋门禁轨迹

用户问题:

> 查询员工 E005 的楼栋门禁轨迹

安全 SQL:

```sql
select event_id, employee_id, employee_name, building_name, floor_name, direction, access_point_name, event_time
from building_access_events
where employee_id = 'E005'
order by event_time desc
limit 10
```

说明: 适合单员工轨迹核查。

### B06. 5F 实验室门禁点记录

用户问题:

> 查询 5F 实验室门禁点记录

安全 SQL:

```sql
select event_id, employee_id, employee_name, building_name, floor_name, direction, access_point_name, event_time
from building_access_events
where access_point_name = '5F-实验室'
order by event_time desc
limit 10
```

说明: 门禁点名称是 allowlist 字段，可用于局部门禁点巡检。

### B07. 设备字段脱敏展示

用户问题:

> 查询数据中心设备字段脱敏展示

安全 SQL:

```sql
select event_id, employee_id, employee_name, device_id, access_point_name, event_time
from building_access_events
where building_name = '数据中心'
order by event_time desc
limit 10
```

说明: `device_id` 会按 `redact` mask 全打码；`raw_device_payload` 仍禁止查询。

## 不应生成的 SQL

以下写法是反例，不应作为 Q-SQL 示例或 Agent 生成目标:

```sql
-- 禁止: SELECT *
select * from factory_access_events limit 10

-- 禁止: 聚合函数
select department_name, count(*) from factory_access_events group by department_name

-- 禁止: JOIN
select f.event_id, b.event_id
from factory_access_events f
join building_access_events b on f.employee_id = b.employee_id

-- 禁止: 原始设备载荷
select event_id, raw_device_payload from building_access_events limit 10
```

如果用户问题需要统计、跨表关联或多条件精确筛选，当前推荐做法是先用安全明细查询拿到 allowlist 字段，再由应用层、operator 或后续 Stage 3 context 工具进行解释和聚合。

## 验证记录

上述 15 条正向示例已用当前代码中的 `create_sandbox_database(...)`、`build_default_sandbox_registry()` 和 `SafeSqlKernel.safe_select(...)` 做本地验证，均能在 deterministic sandbox seed 上执行并返回结果。验证不新增项目代码，也不改变数据库权限、审计或执行边界。
