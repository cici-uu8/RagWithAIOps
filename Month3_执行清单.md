# Month 3 执行清单（Week 9-12）

**目标**: 技术债清理 + 运维化  
**周期**: 4周  
**验收**: Milestone 3通过标准全部达成，可交付生产环境  

---

## Week 9: 前端代码质量重构（6000行→模块化）

### Day 1-2: 拆分规划

#### Day 1: 分析当前代码结构
```bash
# 分析app.js
wc -l static/app.js  # 3043行

# 识别职责模块
grep -n "class\|function" static/app.js
```

**规划拆分结构**:
```
static/
├─ app.js (保留，作为入口，≤200行)
├─ js/
│  ├─ core/
│  │  ├─ SuperBizAgentApp.js (主类，≤300行)
│  │  ├─ EventBus.js (事件总线)
│  │  └─ StateManager.js (状态管理)
│  ├─ modules/
│  │  ├─ ChatManager.js (聊天功能)
│  │  ├─ AIOpsController.js (AIOps诊断)
│  │  ├─ FileManager.js (文件管理)
│  │  ├─ DatabaseViewer.js (数据库查看)
│  │  └─ UserMenuController.js (用户菜单)
│  ├─ components/
│  │  ├─ MessageRenderer.js (消息渲染)
│  │  ├─ LoadingIndicator.js (加载指示器)
│  │  └─ ErrorDisplay.js (错误显示)
│  └─ utils/
│     ├─ error-handler.js (已存在)
│     ├─ loading-states.js (已存在)
│     ├─ trace-utils.js (已存在)
│     └─ api-client.js (API封装)
```

**任务清单**:
- [ ] 拆分计划已确定
- [ ] 模块边界已设计
- [ ] 依赖关系已梳理

#### Day 2: 创建模块骨架
```bash
mkdir -p static/js/{core,modules,components,utils}

# 创建空文件
touch static/js/core/SuperBizAgentApp.js
touch static/js/modules/ChatManager.js
# ... 其他文件
```

**任务清单**:
- [ ] 目录结构已创建
- [ ] 所有文件骨架已创建

### Day 3-4: 逐步拆分

#### Day 3: 拆分核心模块
**创建 static/js/core/SuperBizAgentApp.js**:
```javascript
class SuperBizAgentApp {
    constructor() {
        this.chatManager = null;
        this.aiopController = null;
        this.fileManager = null;
        this.eventBus = new EventBus();
        this.state = new StateManager();
    }
    
    async init() {
        await this.loadModules();
        this.setupEventListeners();
        await this.checkAuth();
    }
    
    async loadModules() {
        this.chatManager = new ChatManager(this.eventBus, this.state);
        this.aiopController = new AIOpsController(this.eventBus, this.state);
        this.fileManager = new FileManager(this.eventBus, this.state);
    }
    
    setupEventListeners() {
        this.eventBus.on('chat:send', (data) => this.chatManager.send(data));
        this.eventBus.on('aiops:diagnose', (data) => this.aiopController.diagnose(data));
    }
}

export default SuperBizAgentApp;
```

**创建 static/js/modules/ChatManager.js**:
```javascript
class ChatManager {
    constructor(eventBus, state) {
        this.eventBus = eventBus;
        this.state = state;
        this.messageRenderer = new MessageRenderer();
    }
    
    async send(message) {
        // 从app.js中提取聊天逻辑
        const loadingState = window.loadingStateManager.start('chat', 'chat-messages');
        
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });
            
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            await this.handleStreamResponse(response);
        } catch (error) {
            window.errorHandler.show(error, 'chat-error', error.traceId);
        } finally {
            loadingState.stop();
        }
    }
    
    async handleStreamResponse(response) {
        // SSE流式处理逻辑
    }
}

export default ChatManager;
```

**任务清单**:
- [ ] SuperBizAgentApp.js已实现
- [ ] ChatManager.js已实现
- [ ] EventBus.js已实现
- [ ] StateManager.js已实现
- [ ] 最大单文件≤500行

#### Day 4: 拆分其他模块
- [ ] AIOpsController.js已实现
- [ ] FileManager.js已实现
- [ ] DatabaseViewer.js已实现
- [ ] UserMenuController.js已实现

### Day 5: 集成测试 + 回归测试

#### 修改 static/index.html
```html
<!-- 改为模块化加载 -->
<script type="module">
    import SuperBizAgentApp from '/static/js/core/SuperBizAgentApp.js';
    
    document.addEventListener('DOMContentLoaded', async () => {
        const app = new SuperBizAgentApp();
        await app.init();
        window.app = app;
    });
</script>
```

#### 回归测试
```bash
# 1. E2E测试
pytest tests/e2e/

# 2. 手动smoke测试21个场景
# 确保所有功能正常
```

**任务清单**:
- [ ] 模块化加载成功
- [ ] E2E测试全部通过
- [ ] 手动smoke测试21/21 PASS
- [ ] Console无错误

**Week 9 验收**:
- [ ] 代码已拆分成20+个模块 ✅
- [ ] 最大单文件≤500行 ✅
- [ ] 所有功能无退化 ✅
- [ ] week9_evidence.md已填写 ✅

---

## Week 10: 性能与可观测性

### Day 1-2: Locust性能基准测试

#### Day 1: 编写压测脚本
**创建 tests/performance/locustfile.py**:
```python
from locust import HttpUser, task, between

class SuperBizAgentUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        # 登录
        self.client.post("/api/auth/login", json={
            "username": "test_user",
            "password": "password"
        })
    
    @task(3)
    def rag_query(self):
        """RAG查询（高频）"""
        self.client.post("/api/chat", json={
            "message": "CPU使用率高怎么办",
            "mode": "rag"
        })
    
    @task(1)
    def aiops_diagnose(self):
        """AIOps诊断（低频）"""
        self.client.post("/api/aiops/diagnose", json={
            "scenario": "cpu_high"
        })
```

**任务清单**:
- [ ] locustfile.py已创建
- [ ] 测试场景已覆盖核心功能

#### Day 2: 执行压测
```bash
# 10并发用户
locust -f tests/performance/locustfile.py --users 10 --spawn-rate 2 --run-time 5m --html report_10users.html

# 50并发用户
locust -f tests/performance/locustfile.py --users 50 --spawn-rate 10 --run-time 5m --html report_50users.html

# 100并发用户
locust -f tests/performance/locustfile.py --users 100 --spawn-rate 20 --run-time 5m --html report_100users.html
```

**记录基线**:
```bash
cat > docs/performance_baseline.md << 'EOF'
# 性能基线报告

## 10并发用户
- RAG查询 P50: __s, P95: __s, P99: __s
- AIOps诊断 P50: __s, P95: __s, P99: __s
- 错误率: __%

## 50并发用户
- RAG查询 P50: __s, P95: __s, P99: __s
- AIOps诊断 P50: __s, P95: __s, P99: __s
- 错误率: __%

## 100并发用户
- RAG查询 P50: __s, P95: __s, P99: __s
- AIOps诊断 P50: __s, P95: __s, P99: __s
- 错误率: __%

## 瓶颈分析
- 主要瓶颈: ____________
- 优化建议: ____________
EOF
```

**任务清单**:
- [ ] 压测已执行
- [ ] 基线已记录
- [ ] 瓶颈已识别

### Day 3-4: 监控Dashboard配置

#### Day 3: Prometheus配置
**创建 config/prometheus.yml**:
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'superbiz-agent'
    static_configs:
      - targets: ['localhost:3004']
```

**在代码中添加metrics**:
```python
# app/api/routes/chat.py
from prometheus_client import Histogram

rag_query_duration = Histogram(
    'rag_query_duration_seconds',
    'RAG查询延迟',
    buckets=[0.1, 0.5, 1, 2, 5, 10]
)

@router.post("/chat")
async def chat(request: ChatRequest):
    with rag_query_duration.time():
        # 处理逻辑
        pass
```

**任务清单**:
- [ ] Prometheus已配置
- [ ] 业务metrics已添加
- [ ] metrics可访问（/metrics端点）

#### Day 4: Grafana Dashboard
**导入Dashboard模板**:
```bash
# 1. 启动Grafana
docker run -d -p 3000:3000 grafana/grafana

# 2. 创建数据源（Prometheus）
# 3. 导入Dashboard JSON
```

**Dashboard面板**:
- RAG查询延迟（P50/P95/P99）
- AIOps诊断延迟
- 错误率
- 并发请求数
- 数据库连接池状态

**任务清单**:
- [ ] Grafana Dashboard已创建
- [ ] 所有面板正常显示
- [ ] 截图保存到docs/

### Day 5: 告警规则配置

**创建 config/prometheus_alerts.yml**:
```yaml
groups:
  - name: superbiz_alerts
    interval: 30s
    rules:
      - alert: RAGHighLatency
        expr: histogram_quantile(0.95, rag_query_duration_seconds) > 5
        for: 5m
        annotations:
          summary: "RAG P95延迟超过5秒"
          description: "当前P95延迟: {{ $value }}秒"
      
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 2m
        annotations:
          summary: "错误率超过5%"
```

**配置告警通知**（钉钉/邮件）:
```yaml
# config/alertmanager.yml
route:
  receiver: 'dingtalk'

receivers:
  - name: 'dingtalk'
    webhook_configs:
      - url: 'https://oapi.dingtalk.com/robot/send?access_token=XXX'
```

**任务清单**:
- [ ] 告警规则已配置
- [ ] 告警通知已测试
- [ ] 手动触发告警验证通过

**Week 10 验收**:
- [ ] 性能基线已建立 ✅
- [ ] Grafana Dashboard就绪 ✅
- [ ] 告警规则已配置并验证 ✅
- [ ] week10_evidence.md已填写 ✅

---

## Week 11: 运维支柱补齐（参考运维支柱补充方案.md）

### Day 1: 数据备份策略

**创建 scripts/backup/backup_postgres.sh**:
```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backup/postgres"
mkdir -p $BACKUP_DIR

pg_dump superbiz_db > $BACKUP_DIR/postgres_$DATE.sql

# 只保留最近30天
find $BACKUP_DIR -name "postgres_*.sql" -mtime +30 -delete

echo "Backup completed: postgres_$DATE.sql"
```

**创建 scripts/backup/backup_vectors.sh**:
```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backup/vectors"
mkdir -p $BACKUP_DIR

tar -czf $BACKUP_DIR/vectors_$DATE.tar.gz /data/chroma

find $BACKUP_DIR -name "vectors_*.tar.gz" -mtime +30 -delete

echo "Backup completed: vectors_$DATE.tar.gz"
```

**配置crontab**:
```bash
# 每天凌晨2点备份
0 2 * * * /path/to/scripts/backup/backup_postgres.sh
0 2 * * * /path/to/scripts/backup/backup_vectors.sh
```

**任务清单**:
- [ ] 备份脚本已创建
- [ ] crontab已配置
- [ ] 测试：手动执行备份成功

### Day 2: 恢复演练

**创建 scripts/restore/restore_guide.md**（恢复SOP）

**执行恢复演练**:
```bash
# 1. 模拟故障
docker stop postgres
rm -rf /data/chroma/*

# 2. 执行恢复
docker start postgres
psql -U postgres -d superbiz_db < /backup/postgres/postgres_latest.sql
tar -xzf /backup/vectors/vectors_latest.tar.gz -C /data/

# 3. 验证完整性
psql -c "SELECT COUNT(*) FROM knowledge_base;"
python -c "from app.core.vector_store import get_collection; print(get_collection().count())"

# 4. 功能smoke测试
pytest tests/smoke/
```

**任务清单**:
- [ ] 恢复SOP已创建
- [ ] 恢复演练已执行
- [ ] 数据100%恢复
- [ ] smoke测试通过

### Day 3: 降级预案实现

**修改代码添加降级逻辑**（参考运维支柱补充方案.md）

**任务清单**:
- [ ] LLM降级逻辑已实现
- [ ] 向量库降级逻辑已实现
- [ ] MCP工具熔断器已实现
- [ ] 测试：模拟故障降级成功

### Day 4: 日志管理

**配置日志轮转 /etc/logrotate.d/superbiz**:
```
/var/log/superbiz/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
}
```

**添加日志脱敏**:
```python
# app/utils/logging.py
def desensitize_log(message: str) -> str:
    # 用户名脱敏
    message = re.sub(r'user_\d+', lambda m: f"user_***{m.group()[-3:]}", message)
    # IP脱敏
    message = re.sub(r'\d+\.\d+\.\d+\.\d+', 'xx.xx.xx.xx', message)
    return message
```

**任务清单**:
- [ ] 日志轮转已配置
- [ ] 日志脱敏已实现
- [ ] 测试：日志轮转正常

### Day 5: 资源限制配置

**修改 app/main.py**:
```python
# 文件上传限制
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_upload_size=50 * 1024 * 1024  # 50MB
)

# 任务超时
@timeout(300)  # 5分钟
async def run_diagnosis(scenario: str):
    pass
```

**Nginx限流配置**:
```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/m;

location /api/ {
    limit_req zone=api burst=5;
}
```

**任务清单**:
- [ ] 文件上传限制已配置
- [ ] 任务超时已配置
- [ ] 并发限流已配置
- [ ] 测试：触发限制正常

**Week 11 验收**:
- [ ] 备份恢复演练通过 ✅
- [ ] 降级预案已实现 ✅
- [ ] 日志管理已配置 ✅
- [ ] 资源限制已配置 ✅
- [ ] week11_evidence.md已填写 ✅

---

## Week 12: 最终验收与文档完善

### Day 1-2: 全量验收测试

#### Day 1: 功能验收
```bash
# RAG检索测试
python -m evals.rag_layer.run_suite --samples 50

# AIOps场景测试
for scenario in cpu_high memory_high disk_full service_unavailable slow_response network_latency pod_crash_loop; do
    python -m evals.aiops.test_scenario $scenario
done

# 前端smoke测试
pytest tests/e2e/test_all_flows.py
```

**验收清单** (参考开发主控文档.md Milestone 3):
- [ ] RAG baseline≥80% ✅
- [ ] AIOps 10个场景成功率≥85% ✅
- [ ] 前端模块化完成 ✅
- [ ] 管理后台功能完整 ✅

#### Day 2: 压力测试
```bash
# 50并发持续30分钟
locust -f tests/performance/locustfile.py \
  --users 50 \
  --spawn-rate 10 \
  --run-time 30m \
  --html final_stress_test.html
```

**验收清单**:
- [ ] 无内存泄漏 ✅
- [ ] 错误率<5% ✅
- [ ] 告警正常触发 ✅

### Day 3-4: 文档完善

#### Day 3: 部署运维手册
**创建 docs/deployment_guide.md**（50页）:
- 环境配置
- 启动流程
- 监控告警处理
- 故障恢复SOP
- 常见问题FAQ

#### Day 4: 用户使用手册 + 开发者文档
- docs/user_manual.md（30页）
- docs/developer_guide.md（80页）

**任务清单**:
- [ ] 部署运维手册完成
- [ ] 用户使用手册完成
- [ ] 开发者文档完成

### Day 5: 演示材料制作

**录制演示视频**（5-10分钟）:
1. 登录和基础功能
2. RAG知识库查询
3. AIOps完整诊断流程
4. 管理后台演示
5. 性能和监控展示

**生成架构图**:
- 系统架构图
- RAG检索流程图
- AIOps诊断流程图
- 数据流图

**任务清单**:
- [ ] 演示视频已录制
- [ ] 架构图已生成
- [ ] 关键页面截图已保存

---

## Month 3 最终验收（Week 12 Friday）

### Milestone 3 通过标准

**功能验收**:
- [ ] 前端代码模块化（最大单文件≤500行） ✅
- [ ] 性能基线建立（Locust压测报告） ✅
- [ ] 监控告警配置完成 ✅
- [ ] 数据备份恢复演练通过 ✅

**质量验收**:
- [ ] 全量回归测试通过 ✅
- [ ] 压力测试50并发30分钟无崩溃 ✅
- [ ] 安全扫描高危漏洞清零 ✅
- [ ] 代码审查清单全部通过 ✅

**文档验收**:
- [ ] 部署运维手册完成 ✅
- [ ] 用户使用手册完成 ✅
- [ ] 开发者文档完成 ✅
- [ ] 演示视频录制完成 ✅

---

## 🎉 生产级SuperBizAgent交付

**以上全部打勾 → 可交付生产环境！**

**最终提交**:
```bash
git add .
git commit -m "feat: 生产级开发完成 - 可交付生产环境"
git push origin feature/production-grade-development

# 创建交付标签
git tag -a v1.0.0-production -m "生产级版本 1.0.0"
git push origin v1.0.0-production
```

**庆祝 🎊**
