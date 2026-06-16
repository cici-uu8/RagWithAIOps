# Redis 高内存使用告警处理手册

## 文档状态

- 候选编号：C6-SRC-MD-001
- 适用部门：process_digital_dept
- 适用场景：Redis high memory、缓存容量逼近上限、evicted keys 增长、热点 key 或大 key 导致内存压力
- Owner 批准：C6-P1b owner-approved runbook source, 2026-06-12
- 安全边界：本文只允许只读排查、容量缓解和变更申请；禁止直接执行 `FLUSHALL`、`FLUSHDB`、批量删除生产 key 或未审批的 `CONFIG SET`

## 告警定义

当 Redis 实例出现以下任一信号时，进入高内存告警处理流程：

- `redis_memory_used_ratio` 连续 5 分钟高于 85%
- `used_memory` 接近 `maxmemory`
- `evicted_keys` 持续增长
- `mem_fragmentation_ratio` 异常升高并伴随可用内存下降
- 业务侧出现缓存写入失败、缓存命中率下降或请求延迟升高

该告警通常影响缓存命中、会话存储、队列缓冲和热点数据读取。如果 Redis 被设置为 noeviction 策略，内存打满后写入请求可能直接失败；如果使用淘汰策略，可能出现热点数据被驱逐、数据库回源放大和接口响应变慢。

## 立即分级

### P1

满足任一条件时按 P1 处理：

- Redis 写入失败影响核心链路
- evicted keys 快速增长并引发数据库回源压力
- 多个业务实例同时出现缓存超时
- 高内存与接口 5xx、P99 延迟或队列积压同时出现

### P2

满足以下条件时按 P2 处理：

- 内存使用率高但没有用户可感知故障
- evicted keys 有增长但业务指标稳定
- 仅单个非核心实例出现容量压力

## 排查步骤

### 步骤 1：确认影响范围

先确认 Redis 实例、业务服务、环境和时间窗口，不要只看单点截图。

需要记录：

- Redis 实例名和 shard
- 所属业务服务
- 告警开始时间
- 是否有发布、导入、批处理或流量突增
- 受影响接口和错误率

### 步骤 2：查看只读内存指标

优先使用监控平台或只读 Redis 命令。

允许的只读命令示例：

```text
INFO memory
INFO stats
INFO keyspace
MEMORY STATS
SLOWLOG GET 20
CLIENT LIST
```

重点字段：

- `used_memory`
- `used_memory_rss`
- `maxmemory`
- `mem_fragmentation_ratio`
- `evicted_keys`
- `expired_keys`
- `connected_clients`
- `blocked_clients`
- `keyspace_hits`
- `keyspace_misses`

### 步骤 3：判断是否是大 key 或热点 key

大 key 会让内存快速膨胀，也会放大网络和序列化成本。热点 key 会造成局部 shard 压力。

允许的低风险方式：

- 通过采样任务查看 key 大小分布
- 使用只读巡检结果查看 top memory keys
- 在低峰期用 `SCAN` 做限速采样
- 通过业务日志定位异常增长的 key 前缀

禁止：

- 在线生产直接执行无节流的全量 `KEYS *`
- 未审批批量删除 key
- 未确认 owner 时清空业务前缀

### 步骤 4：检查 TTL 和淘汰策略

常见问题包括 TTL 缺失、TTL 过长、缓存预热写入过量、淘汰策略与业务不匹配。

需要确认：

- 主要 key 前缀是否设置 TTL
- `maxmemory_policy` 是否符合业务预期
- 是否存在大量 never-expire key
- 是否有批量导入或缓存预热任务刚运行

### 步骤 5：关联业务发布和流量

如果 Redis 内存从某个时间点开始持续上升，需要关联：

- 最近发布版本
- 新增缓存字段
- 缓存序列化格式变化
- 定时任务或数据同步任务
- 活动流量或异常请求

## 常见原因和处理

### 原因 1：TTL 缺失或过长

特征：

- key 数量持续上升
- `expired_keys` 增长很慢
- 大量业务 key 没有过期时间

处理：

- 由业务 owner 确认正确 TTL
- 对新写入逻辑补 TTL
- 对历史 key 做分批清理方案
- 清理必须走变更审批和灰度执行，不允许一次性删除全量 key

### 原因 2：大 key 写入

特征：

- 少数 key 占用大量内存
- 接口响应时间升高
- 网络出口或 Redis CPU 同时升高

处理：

- 将大 key 拆分为更小结构
- 对列表、集合、哈希增加长度上限
- 对历史大 key 做迁移或分批裁剪
- 必要时临时扩容 Redis 规格

### 原因 3：热点流量导致缓存膨胀

特征：

- 内存上升与 QPS 上升同步
- keyspace misses 上升
- 数据库回源压力变大

处理：

- 对热点接口限流或降级
- 增加本地缓存或多级缓存
- 缩短非核心缓存字段
- 扩容 shard 或实例

### 原因 4：淘汰策略不匹配

特征：

- `evicted_keys` 持续增长
- 命中率下降
- 业务频繁回源

处理：

- 评估 `volatile-lru`、`allkeys-lru`、`noeviction` 等策略是否匹配业务
- 修改策略必须提交变更单
- 修改后观察命中率、错误率和回源流量

## 应急措施

5 分钟内可执行：

- 通知业务 owner 和 on-call commander
- 限流高写入接口
- 暂停非核心缓存预热或批量导入任务
- 临时扩容 Redis 容量或增加 shard
- 如果写入失败影响核心链路，按应急变更流程切换降级策略

30 分钟内完成：

- 定位主要 key 前缀和增长来源
- 给出 TTL、拆分、扩容或清理方案
- 建立观察窗口，持续看 `used_memory`、`evicted_keys`、命中率和接口 P99

## 验证标准

处理完成后必须同时满足：

- `redis_memory_used_ratio` 回落到 70% 以下或进入稳定下降趋势
- `evicted_keys` 不再持续增长
- 业务接口错误率和 P99 恢复正常
- 数据库回源流量没有继续放大
- 已记录 owner、根因、处置动作和后续修复项

## 禁止动作

- 禁止直接执行 `FLUSHALL` 或 `FLUSHDB`
- 禁止在生产执行无节流 `KEYS *`
- 禁止未审批批量删除业务 key
- 禁止为了止血直接关闭核心缓存
- 禁止把 Redis 高内存简单归因为机器资源不足而不查 key 增长来源

## 关联场景

- API 5xx spike
- SlowResponse
- MySQL slow query
- Redis queue backlog
- Cache miss storm
