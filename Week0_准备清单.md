# Week 0: 执行准备清单

**目标**: 在开始Month 1之前，建立执行保障机制  
**周期**: 5个工作日  
**验收**: 清单末尾所有检查项全部打勾  

---

## Day 1: 外部依赖零信任验证

### 任务1.1: 语料来源验证
```bash
# 创建依赖验证记录文件
touch docs/external_dependencies.md
```

**验证清单**:
- [ ] 联系数字化部门
  - 负责人姓名: ____________
  - 联系方式: ____________
  - 能否提供runbook: 是 / 否
  - 预计数量: ____ 个文档
  - 交付时间: ____________
  - 格式: Markdown / PDF / Word

- [ ] 联系工艺部门
  - 同上信息

- [ ] 公开技术文档license确认
  - [ ] Redis运维文档: MIT协议 ✅
  - [ ] MySQL troubleshooting: Apache 2.0 ✅
  - [ ] K8s运维指南: CC BY 4.0 ✅

- [ ] Fallback方案确认
  ```
  如果内部语料<30个，启用Fallback:
  - 公开文档: 40个
  - Synthetic docs（自己写）: 20个
  - 总计能达到60个（高于50个目标）
  ```

### 任务1.2: API依赖验证
```bash
# 测试DashScope API
curl -X POST https://dashscope.aliyuncs.com/api/v1/services/rerank \
  -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gte-rerank-hybrid",
    "query": "CPU使用率高怎么办",
    "documents": ["文档1", "文档2"]
  }'
```

**验证清单**:
- [ ] API密钥已申请
  - 申请时间: ____________
  - 到期时间: ____________
- [ ] 测试调用成功
  - 响应时间: ____ ms (目标<500ms)
  - 成功率: 100% ✅
- [ ] 费用预算审批
  - 月预估调用量: 50,000次
  - 月费用: ¥25
  - 审批状态: 已批准 / 待审批
- [ ] Fallback方案
  ```python
  # 如果API失败，降级到local_lexical
  if dashscope_api_error:
      use_local_lexical_rerank()
  ```

### 任务1.3: MCP工具清单确认
- [ ] 已实现工具清单（10个）:
  - [ ] Monitor (监控数据查询)
  - [ ] CLS (日志查询)
  - [ ] Database (数据库查询)
  - [ ] ... (补充其他7个)

- [ ] 待实现工具清单（5个）:
  - [ ] 工具1: _______, 工作量: __ 天
  - [ ] 工具2: _______, 工作量: __ 天
  - [ ] 工具3: _______, 工作量: __ 天
  - [ ] 工具4: _______, 工作量: __ 天
  - [ ] 工具5: _______, 工作量: __ 天
  - [ ] 总工作量: ____ 天

- [ ] Fallback方案
  ```
  如果15个工具做不完，优先做8个高频工具
  ```

---

## Day 2: 搭建状态外化仪表盘

### 任务2.1: GitHub Projects看板
```bash
# 在GitHub上创建项目看板
# 项目名: SuperBizAgent生产级开发
# 列: Backlog | This Week | In Progress | Review | Done
```

**验收清单**:
- [ ] GitHub Projects看板已创建
- [ ] 已添加P0任务卡片（7个）
- [ ] 已添加P1任务卡片（12个）
- [ ] 已添加P2任务卡片（8个）
- [ ] 每个卡片有标签（frontend/backend/devops）

### 任务2.2: 自动化进度报告脚本
```bash
# 创建脚本
mkdir -p scripts
cat > scripts/weekly_review.py << 'EOF'
#!/usr/bin/env python3
"""
每周自动生成进度报告
"""
import json
from datetime import datetime

def generate_weekly_report():
    # 读取测试覆盖率
    # 读取RAG baseline
    # 生成Markdown报告
    pass

if __name__ == "__main__":
    generate_weekly_report()
EOF

chmod +x scripts/weekly_review.py
```

**验收清单**:
- [ ] scripts/weekly_review.py已创建
- [ ] 脚本能跑通（python scripts/weekly_review.py）
- [ ] 生成的报告包含：
  - [ ] P0/P1/P2任务完成度
  - [ ] RAG baseline趋势
  - [ ] 测试覆盖率
  - [ ] 风险指标（红线/黄线触发状态）

---

## Day 3: 定义证据链模板

### 任务3.1: 创建里程碑模板
```bash
mkdir -p docs/milestones
cp docs/milestone_evidence_template.md docs/milestones/
```

**验收清单**:
- [ ] docs/milestone_evidence_template.md已创建
- [ ] 模板包含4个部分：
  - [ ] 代码变更（PR链接、commit SHA）
  - [ ] 功能验证（截图、日志）
  - [ ] 回归测试（测试结果）
  - [ ] 文档同步（文档链接）

### 任务3.2: 定义Code Review规范
```bash
cat > docs/code_review_checklist.md << 'EOF'
# Code Review检查清单

## 功能性
- [ ] 实现了需求文档中的所有功能点
- [ ] 边界条件处理正确
- [ ] 错误处理完整

## 代码质量
- [ ] 函数职责单一
- [ ] 变量命名清晰
- [ ] 无重复代码

## 测试
- [ ] 单元测试覆盖新增代码
- [ ] 回归测试通过

## 文档
- [ ] 代码注释完整
- [ ] 复杂逻辑有说明
EOF
```

**验收清单**:
- [ ] Code Review检查清单已创建
- [ ] 已定义Reviewer角色（谁来Review）
  - 选项1: 自己Review（严格按清单）
  - 选项2: 找同事Review
  - 我选择: ____________

---

## Day 4: 设置纠偏触发器

### 任务4.1: 配置Weekly Review机制
```bash
# 在日历中设置提醒
# 每周五下午3点：Weekly Review
```

**验收清单**:
- [ ] 日历提醒已设置
- [ ] Weekly Review流程已记录：
  ```
  1. 运行scripts/weekly_review.py
  2. 检查红线触发器
  3. 填写milestone_evidence
  4. 决策下周是否继续
  ```

### 任务4.2: 定义触发器阈值
```bash
cat > docs/risk_triggers.md << 'EOF'
# 风险触发器

## 🔴 红线（立即停止）
- Baseline下降>5%且连续2周无恢复
- P95延迟上升>50%
- 测试覆盖率持续下降

## 🟡 黄线（评估调整）
- Baseline提升停滞（连续2批无提升）
- 外部依赖获取困难
- 单个任务耗时超估算2倍
EOF
```

**验收清单**:
- [ ] docs/risk_triggers.md已创建
- [ ] 红线/黄线阈值已明确
- [ ] 触发后的操作流程已定义

---

## Day 5: Kickoff准备

### 任务5.1: 打印工作计划
```bash
# 打印或导出为PDF
# 1. 开发主控文档.md
# 2. Month1_执行清单.md
# 贴在墙上或放在显眼位置
```

### 任务5.2: 环境准备
```bash
# 确认开发环境就绪
python --version  # Python 3.11+
node --version    # Node 16+
git --version
docker --version

# 确认依赖已安装
pip list | grep pytest
pip list | grep ruff
```

**验收清单**:
- [ ] Python 3.11+ ✅
- [ ] Node 16+ ✅
- [ ] Docker ✅
- [ ] 所有依赖已安装
- [ ] 测试能跑通: pytest tests/

### 任务5.3: 个人Kickoff
```bash
# 回顾整个12周计划
# 在DEVELOPMENT_LOG.md记录启动宣言
echo "## Week 0完成" >> DEVELOPMENT_LOG.md
echo "我准备好开始3个月的生产级开发了" >> DEVELOPMENT_LOG.md
echo "目标: 2026-09-17交付生产级SuperBizAgent" >> DEVELOPMENT_LOG.md
```

---

## Week 0 最终验收

### 外部依赖验收
- [ ] 语料来源已确认（内部/公开/Fallback）
- [ ] API密钥已获取且测试通过
- [ ] MCP工具清单已明确

### 仪表盘验收
- [ ] GitHub Projects看板就绪
- [ ] weekly_review.py脚本能跑
- [ ] 进度报告能自动生成

### 文档验收
- [ ] milestone_evidence_template.md ✅
- [ ] code_review_checklist.md ✅
- [ ] risk_triggers.md ✅
- [ ] external_dependencies.md ✅

### 流程验收
- [ ] Weekly Review机制已建立
- [ ] 红线/黄线触发器已定义
- [ ] Code Review流程已明确

### 环境验收
- [ ] 开发环境就绪
- [ ] 依赖全部安装
- [ ] 测试能跑通

---

## ✅ Week 0 通过标准

**以上所有检查项必须全部打勾，才能开始Month 1**

**如果有任何一项未完成**:
- 延长Week 0时间，直到全部完成
- 不要着急开始Month 1

**通过后执行**:
```bash
git add .
git commit -m "docs: Week 0准备清单完成"
echo "✅ Week 0完成，准备开始Month 1 Week 1" >> DEVELOPMENT_LOG.md
```

**下一步**: 打开 `Month1_执行清单.md`，开始Week 1 Day 1任务
