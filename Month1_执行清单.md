# Month 1 执行清单（Week 1-4）

**目标**: 紧急止血 + 核心强化  
**周期**: 4周  
**验收**: Milestone 1通过标准全部达成  

---

## Week 1: 用户体验修复（P0优先级）

### Day 1: 后端P0任务

#### 上午 9:00-12:00: 启用Hybrid检索模式
```bash
# 1. 修改配置
vim config/rag.py

# 添加或修改以下配置
RAG_DEFAULT_RETRIEVAL_MODE = "hybrid"
RAG_HYBRID_DENSE_WEIGHT = 0.5
RAG_HYBRID_SPARSE_WEIGHT = 0.5
```

**任务清单**:
- [ ] 修改config/rag.py
- [ ] 测试Hybrid模式
  ```bash
  python -m evals.rag_layer.run_single_sample S4M-E-010
  # 预期: Retrieval=100%, Answer≥60%
  ```
- [ ] 记录baseline
  ```bash
  echo "Baseline before: 83.3%" >> DEVELOPMENT_LOG.md
  echo "Baseline after Hybrid: __%" >> DEVELOPMENT_LOG.md
  ```

#### 下午 14:00-18:00: 测试覆盖率 + CI/CD
```bash
# 1. 跑测试覆盖率
pytest --cov=app --cov-report=html --cov-report=term

# 2. 记录baseline
echo "测试覆盖率 baseline: __%" >> DEVELOPMENT_LOG.md

# 3. 配置CI/CD
mkdir -p .github/workflows
```

**创建 .github/workflows/ci.yml**:
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e .
      - name: Run tests
        run: pytest --cov=app --cov-report=xml
      - name: Check coverage
        run: |
          coverage=$(python -c "import xml.etree.ElementTree as ET; print(ET.parse('coverage.xml').getroot().attrib['line-rate'])")
          if (( $(echo "$coverage < 0.5" | bc -l) )); then
            echo "Coverage $coverage < 50%"
            exit 1
          fi
```

**任务清单**:
- [ ] 测试覆盖率报告已生成
- [ ] baseline已记录: __%
- [ ] .github/workflows/ci.yml已创建
- [ ] CI推送测试（git push触发GitHub Actions）
- [ ] CI运行成功 ✅

**Day 1 验收**:
- [ ] Hybrid模式启用 ✅
- [ ] S4M-E-010测试通过 ✅
- [ ] Coverage baseline记录 ✅
- [ ] CI/CD跑通 ✅

---

### Day 2: 前端Phase 0 - 错误提示分级系统

#### 上午 9:00-12:00: 创建错误处理器
```bash
mkdir -p static/js
```

**创建 static/js/error-handler.js**（参考前端优化方案.md）:
```javascript
class ErrorHandler {
    constructor() {
        this.errorMap = {
            'Failed to fetch': {
                type: 'network',
                severity: 'critical',
                title: '无法连接后端服务',
                message: '请确认"启动企业助手.command"窗口仍在运行',
                actions: [
                    { label: '重试', action: 'retry' }
                ],
                color: 'red'
            },
            'Invalid credentials': {
                type: 'auth',
                severity: 'high',
                title: '登录失败',
                message: '用户名或密码错误',
                actions: [
                    { label: '重新输入', action: 'clearForm' }
                ],
                color: 'red'
            }
            // ... 更多错误类型
        };
    }
    
    classifyError(error) {
        // 实现分类逻辑
    }
    
    renderError(error, traceId = null) {
        // 实现渲染逻辑
    }
    
    show(error, containerId, traceId) {
        // 实现显示逻辑
    }
}

window.errorHandler = new ErrorHandler();
```

**任务清单**:
- [ ] static/js/error-handler.js已创建
- [ ] 实现ErrorHandler类（参考前端优化方案.md完整代码）
- [ ] 测试错误分类逻辑

#### 下午 14:00-18:00: 创建错误样式
**创建 static/styles_error.css**:
```css
.error-card {
    border-radius: 8px;
    margin: 16px 0;
    padding: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    animation: error-slide-in 0.3s ease-out;
}

.error-red {
    background: #FEF2F2;
    border-left: 4px solid #EF4444;
}

/* ... 更多样式（参考前端优化方案.md） */
```

**集成到 static/index.html**:
```html
<!-- 在<head>中添加 -->
<link rel="stylesheet" href="/static/styles_error.css">
<script src="/static/js/error-handler.js"></script>
```

**任务清单**:
- [ ] static/styles_error.css已创建
- [ ] 样式已集成到index.html
- [ ] 浏览器测试错误卡片显示正常

**Day 2 验收**:
- [ ] 错误处理器已实现 ✅
- [ ] 错误样式已完成 ✅
- [ ] 集成到index.html ✅
- [ ] 浏览器测试通过 ✅

---

### Day 3: 前端Phase 0 - 加载状态优化

#### 全天任务
**创建 static/js/loading-states.js**:
```javascript
class LoadingStateManager {
    constructor() {
        this.states = {
            chat: [
                { text: '🔍 正在检索知识库...', progress: 30, duration: 2000 },
                { text: '📄 正在分析相关文档...', progress: 60, duration: 3000 },
                { text: '✍️ 正在生成回答...', progress: 90, duration: 5000 }
            ],
            // ... 更多状态
        };
    }
    
    start(type, containerId) {
        // 实现逻辑
    }
}

window.loadingStateManager = new LoadingStateManager();
```

**创建 static/styles_loading.css**（参考前端优化方案.md）

**任务清单**:
- [ ] static/js/loading-states.js已创建
- [ ] static/styles_loading.css已创建
- [ ] 集成到index.html
- [ ] 在app.js中替换加载消息
- [ ] 测试：聊天加载显示3个阶段

**Day 3 验收**:
- [ ] 加载状态管理器已实现 ✅
- [ ] 样式已完成 ✅
- [ ] 集成完成 ✅
- [ ] 测试通过 ✅

---

### Day 4: 前端Phase 0 - trace_id全局追踪

#### 全天任务
**创建 static/js/trace-utils.js**:
```javascript
class TraceManager {
    constructor() {
        this.prefix = 'fe';
        this.sessionId = this.generateSessionId();
    }
    
    generateTraceId() {
        const timestamp = Date.now();
        const random = Math.random().toString(36).substr(2, 9);
        return `${this.prefix}-${this.sessionId}-${timestamp}-${random}`;
    }
    
    wrapFetch(originalFetch) {
        return async (url, options = {}) => {
            const traceId = this.generateTraceId();
            options.headers = {
                ...options.headers,
                'X-Trace-Id': traceId
            };
            
            console.log(`[${traceId}] ${options.method || 'GET'} ${url}`);
            
            try {
                const response = await originalFetch(url, options);
                console.log(`[${traceId}] Response ${response.status}`);
                if (!response.ok) {
                    const error = new Error(`HTTP ${response.status}`);
                    error.traceId = traceId;
                    throw error;
                }
                return response;
            } catch (error) {
                console.error(`[${traceId}] Error:`, error);
                error.traceId = error.traceId || traceId;
                throw error;
            }
        };
    }
    
    install() {
        const originalFetch = window.fetch;
        window.fetch = this.wrapFetch(originalFetch).bind(this);
    }
}

window.traceManager = new TraceManager();
window.traceManager.install();
```

**修改 app.js 的错误处理**:
```javascript
// 修改前
catch (error) {
    console.error('Error:', error);
}

// 修改后
catch (error) {
    window.errorHandler.show(error, 'error-container', error.traceId);
}
```

**任务清单**:
- [ ] static/js/trace-utils.js已创建
- [ ] 在index.html中最先引入（所有脚本之前）
- [ ] app.js中所有catch块已更新
- [ ] 测试：Console显示trace_id
- [ ] 测试：错误卡片显示trace_id

**Day 4 验收**:
- [ ] trace_id追踪已实现 ✅
- [ ] 集成到app.js ✅
- [ ] Console测试通过 ✅
- [ ] 错误显示trace_id ✅

---

### Day 5: Week 1 验收测试

#### 上午: 回归测试
```bash
# 1. 运行所有测试
pytest

# 2. 前端smoke测试
# 手动测试21个场景
```

**测试清单**:
- [ ] 登录功能 ✅
- [ ] 聊天功能（检查加载状态） ✅
- [ ] 错误提示（故意触发错误，检查提示） ✅
- [ ] trace_id（Console检查） ✅
- [ ] 文件上传 ✅
- [ ] AIOps诊断 ✅
- [ ] 用户菜单 ✅

#### 下午: 填写里程碑证据
```bash
cp docs/milestone_evidence_template.md docs/milestones/week1_evidence.md
# 填写Week 1完成的证据
```

**Week 1 最终验收**:
- [ ] Hybrid模式启用 ✅
- [ ] CI/CD跑通 ✅
- [ ] 前端Phase 0完成（错误提示+加载状态+trace_id） ✅
- [ ] 所有测试通过 ✅
- [ ] week1_evidence.md已填写 ✅

**提交代码**:
```bash
git add .
git commit -m "feat: Week 1完成 - 用户体验修复P0"
git push origin feature/production-grade-development
```

---

## Week 2: 核心能力可视化

### Day 1-3: AIOps诊断流程可视化

**任务**: 实现AIOpsVisualizer组件（参考前端优化方案.md完整代码）

**Day 1**: 创建AIOpsVisualizer类
**Day 2**: 集成SSE事件监听
**Day 3**: 测试和样式调整

### Day 4: 权限状态三色可视化

**任务**: 实现PermissionViewer组件

### Day 5: Week 2验收

---

## Week 3: RAG质量提升第一波（30→50 docs）

### Day 1-2: 语料收集
### Day 3: 批量导入
### Day 4: 回归测试
### Day 5: Week 3验收

---

## Week 4: AIOps场景扩充第一波（3→6场景）

### Day 1-2: MemoryHigh场景
### Day 1.5-3: DiskFull场景
### Day 3.5-5: ServiceUnavailable场景

---

## Month 1 最终验收（Week 4 Friday）

### 功能验收
- [ ] 前端Phase 0+1完成
- [ ] RAG语料库50个文档
- [ ] AIOps场景6个
- [ ] CI/CD跑通

### 质量验收
- [ ] 测试覆盖率≥50%（后端）
- [ ] RAG baseline≥80%
- [ ] AIOps诊断成功率≥80%
- [ ] 前端smoke测试21/21 PASS

### 文档验收
- [ ] week1_evidence.md ✅
- [ ] week2_evidence.md ✅
- [ ] week3_evidence.md ✅
- [ ] week4_evidence.md ✅

**通过标准**: 以上全部打勾

**下一步**: 打开 `Month2_执行清单.md`
