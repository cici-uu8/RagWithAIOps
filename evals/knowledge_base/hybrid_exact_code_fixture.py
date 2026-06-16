"""Synthetic exact-code fixture for hybrid retrieval probes.

The fixture is intentionally not production corpus. It creates a controlled
error-code reference document and query set for testing whether lexical recall
helps exact identifier lookups such as ``ERR_DB_001``.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "hybrid_exact_code"
REFERENCE_FILE = FIXTURE_DIR / "enterprise_error_code_reference.md"
QUERY_FILE = FIXTURE_DIR / "hybrid_exact_code_queries.jsonl"


@dataclass(frozen=True)
class ErrorCodeEntry:
    code: str
    category: str
    prefix: str
    name_en: str
    name_zh: str
    description: str
    cause: str
    check_command: str
    fix: str


CASE_GROUPS: tuple[tuple[str, str, list[tuple[str, str, str, str, str]]], ...] = (
    (
        "数据库错误",
        "ERR_DB",
        [
            ("Connection Timeout", "数据库连接超时", "连接请求超过超时时间", "nc -vz <db_host> 3306", "检查网络并调整连接超时"),
            ("Deadlock Detected", "检测到死锁", "多个事务互相等待锁资源", "SHOW ENGINE INNODB STATUS", "分析死锁日志并调整事务顺序"),
            ("Connection Pool Exhausted", "连接池耗尽", "应用连接池无可用连接", "检查 active/idle/wait 指标", "扩大连接池或修复连接泄漏"),
            ("Lock Wait Timeout", "锁等待超时", "SQL 等待行锁或元数据锁过久", "SHOW PROCESSLIST", "定位持锁事务并缩短事务时间"),
            ("Replication Lag", "复制延迟", "从库落后主库过多", "SHOW SLAVE STATUS", "检查主从网络和慢 SQL"),
            ("Too Many Connections", "连接数过多", "数据库连接达到上限", "SHOW VARIABLES LIKE 'max_connections'", "释放空闲连接并调整上限"),
            ("Slow Query Surge", "慢查询激增", "慢 SQL 数量突然增加", "查看 slow query log", "增加索引并优化执行计划"),
            ("Disk Full", "数据库磁盘满", "数据目录或日志目录空间不足", "df -h /var/lib/mysql", "清理归档日志并扩容磁盘"),
            ("Rollback Storm", "事务回滚风暴", "大量事务失败回滚", "检查事务错误日志", "修复异常 SQL 和重试策略"),
            ("Schema Migration Failed", "表结构迁移失败", "DDL 执行失败或被锁阻塞", "查看 migration 日志", "回滚迁移并分批执行 DDL"),
            ("Index Missing", "索引缺失", "高频查询缺少有效索引", "EXPLAIN <sql>", "创建覆盖查询条件的索引"),
            ("Table Not Found", "表不存在", "查询访问了不存在的表", "SHOW TABLES LIKE '<table>'", "确认库表名和迁移状态"),
            ("Duplicate Key", "主键或唯一键冲突", "插入数据违反唯一约束", "查看 duplicate key 错误", "修正幂等键或去重数据"),
            ("Foreign Key Constraint", "外键约束失败", "子表引用不存在的父记录", "检查外键约束定义", "先写入父记录或调整约束"),
            ("Read Replica Unavailable", "只读副本不可用", "读副本宕机或落后过多", "检查 replica health", "切换可用副本或回退主库读"),
            ("Binlog Corruption", "binlog 损坏", "二进制日志不可读", "mysqlbinlog <file>", "从备份恢复并重建复制"),
            ("Backup Failed", "备份失败", "备份任务没有生成有效文件", "检查 backup job 日志", "重跑备份并校验备份权限"),
            ("Restore Failed", "恢复失败", "备份文件无法恢复", "校验备份 checksum", "换用最近可用备份并演练恢复"),
            ("Query Plan Regression", "执行计划退化", "优化器选择了更差计划", "EXPLAIN ANALYZE <sql>", "更新统计信息或固定索引"),
            ("Max Packet Exceeded", "数据包超过上限", "SQL 请求超过 max_allowed_packet", "SHOW VARIABLES LIKE 'max_allowed_packet'", "调大限制或拆分请求"),
            ("Charset Mismatch", "字符集不一致", "客户端和表字符集不匹配", "SHOW FULL COLUMNS FROM <table>", "统一连接和表字符集"),
            ("Permission Denied", "数据库权限不足", "账号缺少目标库表权限", "SHOW GRANTS FOR <user>", "按最小权限补充授权"),
            ("Vacuum Required", "表膨胀需要清理", "PostgreSQL 表膨胀影响查询", "VACUUM VERBOSE <table>", "执行 vacuum/analyze 并检查长事务"),
            ("Autovacuum Stuck", "自动清理卡住", "autovacuum 无法推进", "pg_stat_activity", "处理阻塞事务并调度 vacuum"),
            ("Connection Reset", "数据库连接被重置", "连接被中间网络或服务端断开", "查看客户端连接错误", "检查负载均衡和 keepalive"),
            ("Statement Timeout", "语句执行超时", "SQL 超过 statement_timeout", "查看超时 SQL", "优化 SQL 或调整超时"),
            ("Metadata Lock Blocked", "元数据锁阻塞", "DDL 或查询等待 MDL", "SHOW PROCESSLIST", "终止阻塞会话并错峰 DDL"),
            ("Temp Table Overflow", "临时表溢出", "排序或聚合生成大临时表", "查看 Created_tmp_disk_tables", "优化查询并增加临时空间"),
            ("Primary Key Hotspot", "主键热点", "集中写入同一热点范围", "查看写入分布", "引入分片键或打散写入"),
            ("Disk IO Saturation", "磁盘 IO 饱和", "数据库磁盘读写延迟升高", "iostat -x 1", "降低慢查询并扩容存储 IOPS"),
        ],
    ),
    (
        "Redis 错误",
        "ERR_REDIS",
        [
            ("OOM Command Not Allowed", "内存不足拒绝命令", "写命令因内存上限被拒绝", "redis-cli INFO memory", "清理 key 或调整 maxmemory 策略"),
            ("Connection Refused", "Redis 连接被拒绝", "Redis 服务未监听目标端口", "redis-cli -h <host> PING", "启动服务并确认端口"),
            ("Slow Command", "Redis 慢命令", "命令执行耗时过高", "redis-cli SLOWLOG GET 10", "优化大 key 或复杂命令"),
            ("Eviction Spike", "淘汰突增", "key 淘汰数量异常升高", "redis-cli INFO stats", "扩容内存并检查 TTL 策略"),
            ("Persistence Failure", "持久化失败", "RDB/AOF 写入失败", "redis-cli INFO persistence", "检查磁盘和持久化配置"),
            ("Replica Link Down", "主从链路断开", "副本无法连接主节点", "redis-cli INFO replication", "修复网络和复制认证"),
            ("Cluster Slot Migrating", "槽迁移异常", "Redis Cluster 槽迁移未完成", "redis-cli CLUSTER NODES", "完成槽迁移或回滚迁移"),
            ("Sentinel No Master", "Sentinel 找不到主节点", "哨兵无法达成主节点判断", "redis-cli SENTINEL masters", "检查 quorum 和网络"),
            ("Blocked Clients High", "阻塞客户端过多", "BLPOP 等阻塞命令积压", "redis-cli INFO clients", "排查阻塞队列和消费端"),
            ("Lua Script Timeout", "Lua 脚本超时", "脚本执行超过 lua-time-limit", "redis-cli SCRIPT KILL", "优化脚本或拆分逻辑"),
            ("AOF Rewrite Stuck", "AOF 重写卡住", "AOF rewrite 长时间未完成", "redis-cli INFO persistence", "检查磁盘吞吐并重启 rewrite"),
            ("Keyspace Miss Surge", "缓存未命中突增", "命中率下降导致后端压力升高", "redis-cli INFO stats", "预热热点 key 并检查 TTL"),
            ("Hot Key Overload", "热点 key 过载", "单个 key 访问量过高", "redis-cli --hotkeys", "拆分热点 key 或加本地缓存"),
            ("Big Key Detected", "检测到大 key", "单个 key 体积过大", "redis-cli --bigkeys", "拆分数据结构并限制大小"),
            ("Memory Fragmentation High", "内存碎片率过高", "allocator 碎片造成可用内存下降", "redis-cli INFO memory", "开启 active defrag 或重启窗口"),
            ("Auth Failed", "Redis 认证失败", "客户端密码或 ACL 错误", "查看 Redis ACL LOG", "更新凭据并同步配置"),
            ("Cluster Down", "集群不可用", "多数槽不可用或节点故障", "redis-cli CLUSTER INFO", "恢复故障节点并修复槽状态"),
            ("PubSub Backlog", "发布订阅积压", "订阅端消费慢导致缓冲增长", "redis-cli CLIENT LIST", "扩容订阅端或限流发布"),
            ("Latency Spike", "Redis 延迟尖刺", "命令或系统调用延迟升高", "redis-cli --latency-history", "定位慢命令和系统 IO"),
            ("Config Rewrite Failed", "配置重写失败", "CONFIG REWRITE 无法写文件", "redis-cli CONFIG REWRITE", "修复配置文件权限"),
        ],
    ),
    (
        "Kubernetes 错误",
        "ERR_K8S",
        [
            ("CrashLoopBackOff", "Pod 反复崩溃", "容器启动后不断退出", "kubectl logs <pod>", "修复启动异常或健康检查"),
            ("ImagePullBackOff", "镜像拉取失败", "节点无法拉取容器镜像", "kubectl describe pod <pod>", "修复镜像地址或 registry 凭据"),
            ("ErrImagePull", "镜像拉取错误", "首次拉取镜像失败", "kubectl get events", "确认 tag、网络和凭据"),
            ("Pod Pending", "Pod 一直 Pending", "调度器无法分配节点", "kubectl describe pod <pod>", "检查资源、亲和性和污点"),
            ("Node Not Ready", "节点不可用", "节点心跳或 kubelet 异常", "kubectl describe node <node>", "恢复 kubelet 或隔离节点"),
            ("OOMKilled", "容器被 OOM 杀死", "容器超过内存限制", "kubectl describe pod <pod>", "优化内存或调高 limit"),
            ("CPU Throttling High", "CPU 限流过高", "容器 CPU 被限制", "kubectl top pod", "优化资源请求和应用负载"),
            ("Readiness Probe Failed", "就绪探针失败", "服务未通过 readiness 检查", "kubectl describe pod <pod>", "修复健康接口或延长探针"),
            ("Liveness Probe Failed", "存活探针失败", "服务被 liveness 重启", "kubectl get events", "修复探针配置和启动时间"),
            ("PVC Pending", "PVC 未绑定", "存储声明没有可用 PV", "kubectl describe pvc <pvc>", "补充 StorageClass 或 PV"),
            ("PVC Filling Up", "PVC 快满", "持久卷可用空间不足", "kubectl exec <pod> -- df -h", "清理数据或扩容 PVC"),
            ("DNS Resolution Failed", "集群 DNS 解析失败", "Pod 无法解析服务域名", "kubectl exec <pod> -- nslookup", "检查 CoreDNS 和网络策略"),
            ("Service Endpoint Empty", "服务端点为空", "Service 没有关联可用 Pod", "kubectl get endpoints <svc>", "修复 selector 或 Pod readiness"),
            ("Ingress 502", "Ingress 返回 502", "入口无法转发到后端", "kubectl describe ingress", "检查后端服务和控制器日志"),
            ("NetworkPolicy Denied", "网络策略拒绝", "Pod 流量被策略阻断", "kubectl get networkpolicy", "调整入站或出站策略"),
            ("ConfigMap Missing", "ConfigMap 缺失", "Pod 引用了不存在的配置", "kubectl describe pod <pod>", "创建配置或修正引用"),
            ("Secret Missing", "Secret 缺失", "Pod 引用了不存在的密钥", "kubectl get secret", "创建 Secret 并滚动重启"),
            ("HPA Maxed Out", "HPA 达到上限", "自动扩缩容达到 maxReplicas", "kubectl describe hpa", "扩容上限或优化负载"),
            ("Quota Exceeded", "资源配额超限", "命名空间资源超过 quota", "kubectl describe quota", "释放资源或提高配额"),
            ("Certificate Expired", "证书过期", "组件 TLS 证书失效", "openssl x509 -in cert.pem -noout -dates", "轮换证书并重启组件"),
            ("API Server Unreachable", "API Server 不可达", "客户端无法访问 kube-apiserver", "kubectl cluster-info", "检查控制面和网络"),
            ("Scheduler Down", "调度器不可用", "新 Pod 无法被调度", "kubectl get pods -n kube-system", "恢复 scheduler 组件"),
            ("Controller Manager Down", "控制器不可用", "Deployment 等控制器不同步", "kubectl get pods -n kube-system", "恢复 controller-manager"),
            ("DaemonSet Unavailable", "DaemonSet 不可用", "守护进程未覆盖节点", "kubectl describe daemonset", "检查容忍度和节点状态"),
            ("Job Backoff Limit", "Job 达到重试上限", "批处理任务连续失败", "kubectl describe job <job>", "修复任务命令并重跑 Job"),
        ],
    ),
    (
        "应用错误",
        "ERR_APP",
        [
            ("Authentication Failed", "认证失败", "用户身份校验未通过", "查看 auth audit log", "刷新 token 或修复登录配置"),
            ("Authorization Denied", "授权拒绝", "用户缺少目标资源权限", "检查 permission grants", "按最小权限补充授权"),
            ("Invalid Request Parameter", "请求参数无效", "参数缺失或格式错误", "查看请求 payload", "修正参数并补充校验"),
            ("Rate Limit Exceeded", "超过限流", "请求超过限流阈值", "查看 gateway rate limit 日志", "降低请求频率或调整配额"),
            ("Dependency Timeout", "依赖服务超时", "下游服务未及时响应", "查看 tracing span", "隔离慢依赖并设置熔断"),
            ("Circuit Breaker Open", "熔断器打开", "错误率超过熔断阈值", "查看 circuit breaker 指标", "修复下游后半开恢复"),
            ("Payload Too Large", "请求体过大", "上传或请求超过大小限制", "检查 Content-Length", "压缩或拆分请求"),
            ("Unsupported Media Type", "媒体类型不支持", "Content-Type 不符合接口要求", "查看请求 header", "使用支持的 content type"),
            ("Validation Failed", "业务校验失败", "字段值不满足业务规则", "查看 validation errors", "修正字段或放宽规则"),
            ("Idempotency Conflict", "幂等冲突", "重复请求携带冲突幂等键", "查询 idempotency store", "复用原响应或换新幂等键"),
            ("Session Expired", "会话过期", "用户 session 已失效", "查看 session store", "重新登录并刷新会话"),
            ("Feature Flag Disabled", "功能开关关闭", "请求访问未启用功能", "查看 feature flag", "确认灰度范围后开启"),
            ("Schema Version Mismatch", "协议版本不匹配", "客户端和服务端 schema 不一致", "检查 API version", "升级客户端或兼容旧版本"),
            ("Message Queue Publish Failed", "消息发布失败", "应用无法写入消息队列", "查看 mq producer log", "恢复 broker 并重试发布"),
            ("Message Queue Consume Lag", "消息消费延迟", "消费者落后生产者", "查看 consumer lag", "扩容消费者或限流生产者"),
            ("File Upload Failed", "文件上传失败", "对象存储写入失败", "查看 object storage log", "修复凭据和网络"),
            ("File Download Failed", "文件下载失败", "对象存储读取失败", "curl -I <object_url>", "检查权限和对象存在性"),
            ("Cache Stampede", "缓存击穿", "热点 key 失效导致后端突增", "查看 cache miss rate", "加互斥锁和预热"),
            ("Serialization Failed", "序列化失败", "对象无法编码为响应格式", "查看 serialization error", "修正字段类型或编码器"),
            ("Deserialization Failed", "反序列化失败", "请求体无法解析为对象", "查看 parser error", "修正请求格式"),
            ("Background Job Failed", "后台任务失败", "异步任务执行异常", "查看 job log", "修复任务并重放失败任务"),
            ("Webhook Delivery Failed", "Webhook 投递失败", "外部回调无法送达", "查看 webhook delivery log", "重试投递并修复目标端"),
            ("Payment Gateway Error", "支付网关错误", "支付依赖返回失败", "查看 payment gateway response", "降级支付通道并人工核对"),
            ("Search Index Lag", "搜索索引延迟", "搜索结果落后主数据", "查看 indexer lag", "重建索引或扩容 indexer"),
            ("Audit Write Failed", "审计写入失败", "审计事件未持久化", "查看 audit sink log", "恢复审计 sink 并补写事件"),
        ],
    ),
    (
        "网络错误",
        "ERR_NET",
        [
            ("DNS Resolution Failed", "DNS 解析失败", "域名无法解析到地址", "dig <domain>", "修复 DNS 记录或解析链路"),
            ("TLS Handshake Failed", "TLS 握手失败", "客户端和服务端 TLS 协商失败", "openssl s_client -connect host:443", "更新证书和 TLS 配置"),
            ("Connection Refused", "连接被拒绝", "目标端口没有服务监听", "nc -vz <host> <port>", "启动服务或修正端口"),
            ("Connection Reset", "连接被重置", "连接被对端或中间设备关闭", "tcpdump host <ip>", "检查负载均衡和超时"),
            ("Packet Loss High", "丢包率高", "网络链路丢包升高", "mtr <host>", "切换链路或排查网络设备"),
            ("Latency High", "网络延迟高", "RTT 超出正常范围", "ping <host>", "定位跨区链路并就近接入"),
            ("Route Blackhole", "路由黑洞", "流量被错误路由丢弃", "traceroute <host>", "修复路由表和 ACL"),
            ("Load Balancer 503", "负载均衡 503", "LB 无可用后端", "查看 LB target health", "恢复后端健康检查"),
            ("Proxy Authentication Required", "代理认证失败", "代理要求认证但凭据无效", "curl -v --proxy <proxy>", "更新代理凭据"),
            ("Firewall Blocked", "防火墙阻断", "安全组或防火墙拒绝流量", "检查 security group", "开放最小必要端口"),
        ],
    ),
    (
        "系统错误",
        "ERR_SYS",
        [
            ("CPU Saturation", "CPU 饱和", "主机 CPU 长时间高位运行", "top -H", "定位高 CPU 进程并扩容"),
            ("Memory Pressure", "内存压力", "可用内存不足或 swap 升高", "free -m", "释放内存或扩容实例"),
            ("Disk Space Low", "磁盘空间不足", "文件系统可用空间过低", "df -h", "清理日志并扩容磁盘"),
            ("Disk Inode Exhausted", "inode 耗尽", "大量小文件耗尽 inode", "df -i", "清理小文件或重建文件系统"),
            ("File Descriptor Exhausted", "文件描述符耗尽", "进程打开文件数达到上限", "lsof -p <pid>", "关闭泄漏句柄或提高 ulimit"),
            ("Process Crash", "进程崩溃", "关键进程异常退出", "journalctl -u <service>", "修复崩溃原因并重启服务"),
            ("Clock Skew", "时钟偏移", "主机时间和标准时间偏差过大", "timedatectl status", "恢复 NTP 同步"),
            ("Kernel Panic", "内核崩溃", "系统发生 panic 重启", "journalctl -k", "检查内核日志并升级补丁"),
            ("Log Rotation Failed", "日志轮转失败", "日志文件未按期轮转", "logrotate -d <conf>", "修复 logrotate 配置"),
            ("Service Unit Failed", "systemd 服务失败", "服务单元进入 failed 状态", "systemctl status <service>", "查看失败原因并重启"),
        ],
    ),
)

EXACT_CODE_QUERY_CODES = (
    "ERR_DB_001",
    "ERR_DB_003",
    "ERR_DB_006",
    "ERR_DB_012",
    "ERR_DB_015",
    "ERR_DB_020",
    "ERR_DB_024",
    "ERR_DB_030",
    "ERR_REDIS_001",
    "ERR_REDIS_005",
    "ERR_REDIS_010",
    "ERR_REDIS_015",
    "ERR_REDIS_020",
    "ERR_K8S_001",
    "ERR_K8S_003",
    "ERR_K8S_008",
    "ERR_K8S_012",
    "ERR_K8S_018",
    "ERR_K8S_025",
    "ERR_APP_001",
    "ERR_APP_005",
    "ERR_APP_010",
    "ERR_APP_015",
    "ERR_APP_020",
    "ERR_APP_025",
    "ERR_NET_002",
    "ERR_NET_007",
    "ERR_SYS_001",
    "ERR_SYS_006",
    "ERR_SYS_010",
)

SEMANTIC_QUERIES = (
    ("Connection Timeout 错误怎么办", "ERR_DB_001"),
    ("CrashLoopBackOff 如何处理", "ERR_K8S_001"),
    ("OOM Command Not Allowed 解决方案", "ERR_REDIS_001"),
    ("Authentication Failed 原因", "ERR_APP_001"),
    ("DNS Resolution Failed 怎么排查", "ERR_NET_001"),
    ("Disk IO Saturation 怎么办", "ERR_DB_030"),
)


def build_error_code_entries() -> list[ErrorCodeEntry]:
    entries: list[ErrorCodeEntry] = []
    for category, prefix, cases in CASE_GROUPS:
        for index, (name_en, name_zh, description, check_command, fix) in enumerate(cases, start=1):
            entries.append(
                ErrorCodeEntry(
                    code=f"{prefix}_{index:03d}",
                    category=category,
                    prefix=prefix,
                    name_en=name_en,
                    name_zh=name_zh,
                    description=description,
                    cause=f"{name_zh} 通常来自配置、容量、权限或依赖状态异常。",
                    check_command=check_command,
                    fix=fix,
                )
            )
    return entries


def render_error_code_reference(entries: list[ErrorCodeEntry]) -> str:
    grouped: dict[str, list[ErrorCodeEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.category, []).append(entry)

    lines = [
        "---",
        "dataset_id: hybrid_exact_code_synthetic_v1",
        "synthetic: true",
        "synthetic=true",
        "production_corpus: false",
        "beta_baseline_impact: none",
        "purpose: controlled exact-code retrieval probe",
        "---",
        "",
        "# 企业错误码参考手册（Synthetic）",
        "",
        "> synthetic=true。本文件是受控检索实验数据，不是生产业务错误码手册，不计入 Beta 主语料成熟度。",
        "",
        f"- 错误码总数: {len(entries)}",
        "- 覆盖范围: 数据库、Redis、Kubernetes、应用、网络、系统",
        "- 允许结论: hybrid 是否适合 exact-code 文档类型",
        "- 禁止结论: 不能据此修改默认 retrieval mode，不能证明业务 corpus 成熟",
        "",
    ]
    for category_index, (category, category_entries) in enumerate(grouped.items(), start=1):
        prefix = category_entries[0].prefix
        lines.extend(
            [
                f"## {category_index}. {category} ({prefix}_xxx)",
                "",
            ]
        )
        for entry in category_entries:
            related = _related_codes(entry, category_entries)
            lines.extend(
                [
                    f"### {entry.code} - {entry.name_en}",
                    "",
                    "synthetic=true",
                    "",
                    f"**错误码**: `{entry.code}`",
                    f"**错误名称**: {entry.name_zh}",
                    f"**英文名称**: {entry.name_en}",
                    f"**错误类型**: {entry.category}",
                    f"**描述**: {entry.description}",
                    "",
                    "**常见原因**:",
                    f"- {entry.cause}",
                    "- 上游依赖、容量水位或配置变更需要同步检查。",
                    "",
                    "**排查步骤**:",
                    f"1. 精确定位错误码：`{entry.code}`。",
                    f"2. 执行检查命令：`{entry.check_command}`。",
                    "3. 查看最近 15 分钟日志、指标和变更记录。",
                    "",
                    "**解决方案**:",
                    f"- {entry.fix}。",
                    "- 处理后补充监控证据和回归验证记录。",
                    "",
                    f"**相关错误**: {', '.join(related)}",
                    "",
                    "---",
                    "",
                ]
            )
    return "\n".join(lines)


def build_query_rows(entries: list[ErrorCodeEntry]) -> list[dict[str, object]]:
    by_code = {entry.code: entry for entry in entries}
    rows: list[dict[str, object]] = []
    for index, code in enumerate(EXACT_CODE_QUERY_CODES, start=1):
        entry = by_code[code]
        action = ("怎么解决", "是什么错误", "如何排查", "原因是什么", "排查步骤")[(index - 1) % 5]
        rows.append(
            {
                "sample_id": f"HEX-A-{index:03d}",
                "query": f"{code} {action}",
                "query_type": "exact_code",
                "expected_error_code": code,
                "expected_category": entry.category,
                "expected_doc_id": "enterprise_error_code_reference_synthetic",
                "expected_chunk_id": code,
                "allowed_kb_ids": ["hybrid_exact_code_synthetic"],
                "top_k": 3,
                "synthetic": True,
            }
        )
    for index, (query, code) in enumerate(SEMANTIC_QUERIES, start=1):
        entry = by_code[code]
        rows.append(
            {
                "sample_id": f"HEX-B-{index:03d}",
                "query": query,
                "query_type": "semantic_name",
                "expected_error_code": code,
                "expected_category": entry.category,
                "expected_doc_id": "enterprise_error_code_reference_synthetic",
                "expected_chunk_id": code,
                "allowed_kb_ids": ["hybrid_exact_code_synthetic"],
                "top_k": 3,
                "synthetic": True,
            }
        )
    return rows


def write_fixture_files(output_dir: str | Path = FIXTURE_DIR) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = build_error_code_entries()
    reference_path = output_dir / "enterprise_error_code_reference.md"
    query_path = output_dir / "hybrid_exact_code_queries.jsonl"
    reference_path.write_text(render_error_code_reference(entries), encoding="utf-8")
    with query_path.open("w", encoding="utf-8") as handle:
        for row in build_query_rows(entries):
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")
    return reference_path, query_path


def _related_codes(entry: ErrorCodeEntry, category_entries: list[ErrorCodeEntry]) -> list[str]:
    codes = [item.code for item in category_entries]
    index = codes.index(entry.code)
    related = []
    if index > 0:
        related.append(codes[index - 1])
    if index + 1 < len(codes):
        related.append(codes[index + 1])
    if not related:
        related.append(codes[0])
    return related[:2]


def _load_jsonl(path: str | Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_fixture_files(reference_path: str | Path, query_path: str | Path) -> dict[str, object]:
    reference_text = Path(reference_path).read_text(encoding="utf-8")
    queries = _load_jsonl(query_path)
    entries = build_error_code_entries()
    exact_count = sum(1 for row in queries if row.get("query_type") == "exact_code")
    return {
        "synthetic_marker_present": "synthetic=true" in reference_text,
        "entry_count": len(entries),
        "rendered_entry_heading_count": reference_text.count("### ERR_"),
        "query_count": len(queries),
        "exact_code_query_count": exact_count,
        "semantic_query_count": len(queries) - exact_count,
        "valid": (
            "synthetic=true" in reference_text
            and len(entries) == 120
            and reference_text.count("### ERR_") == 120
            and len(queries) == 36
            and exact_count >= 25
        ),
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic exact-code hybrid fixture.")
    parser.add_argument("--output-dir", default=str(FIXTURE_DIR))
    args = parser.parse_args(list(argv) if argv is not None else None)
    reference_path, query_path = write_fixture_files(args.output_dir)
    validation = validate_fixture_files(reference_path, query_path)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
