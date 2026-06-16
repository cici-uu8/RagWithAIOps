# 里程碑验收证据模板

**里程碑名称**: ____________  
**完成日期**: ____________  
**负责人**: ____________  

---

## 1. 代码变更证据

### PR链接
- PR #__: ____________
- 状态: Merged / Open / Closed
- Review者: ____________
- Review状态: Approved / Changes Requested

### Git Commit
```bash
# 主要commit列表
git log --oneline --since="YYYY-MM-DD" --until="YYYY-MM-DD"

# 示例输出:
# abcd1234 feat(frontend): 完成错误提示分级系统
# efgh5678 feat(frontend): 添加trace_id全局追踪
# ijkl9012 test(frontend): 添加error-handler单元测试
```

**关键commit SHA**:
- Commit 1: ________ - ____________
- Commit 2: ________ - ____________
- Commit 3: ________ - ____________

### 变更文件统计
```bash
git diff --stat feature/production-grade-development~10..feature/production-grade-development

# 示例输出:
# static/js/error-handler.js        | 150 ++++++++++
# static/styles_error.css           | 80 +++++
# static/index.html                 | 5 +
# 3 files changed, 235 insertions(+)
```

**变更文件清单**（≤20个）:
- [ ] File 1: ____________ (+__/-__ lines)
- [ ] File 2: ____________ (+__/-__ lines)
- [ ] ...

### 代码审查清单
参考 `docs/code_review_checklist.md`

- [ ] 功能性: 实现了所有需求点
- [ ] 代码质量: 函数职责单一，命名清晰
- [ ] 测试: 单元测试覆盖新增代码
- [ ] 文档: 复杂逻辑有注释

**Review结论**: Approved / Changes Requested / Rejected

---

## 2. 功能验证证据

### 2.1 手动测试

**测试场景清单**:
- [ ] 场景1: ____________
  - 输入: ____________
  - 预期输出: ____________
  - 实际输出: ____________
  - 结果: ✅ Pass / ❌ Fail

- [ ] 场景2: ____________
  - 同上

- [ ] 场景3: ____________
  - 同上

### 2.2 自动化测试

**单元测试**:
```bash
pytest tests/test_xxx.py -v

# 示例输出:
# test_error_handler.py::test_classify_network_error PASSED
# test_error_handler.py::test_classify_auth_error PASSED
# test_error_handler.py::test_render_error_card PASSED
# ===== 3 passed in 0.5s =====
```

**测试结果**:
- 总测试数: __
- 通过: __
- 失败: __
- 覆盖率: __%

**E2E测试**:
```bash
pytest tests/e2e/test_core_flow.py

# 结果:
# test_login_chat_flow PASSED
# test_aiops_diagnosis_flow PASSED
```

### 2.3 浏览器兼容性测试

**测试矩阵**:
| 浏览器 | 版本 | 桌面 | 移动 | 结果 |
|--------|------|------|------|------|
| Chrome | 120+ | ✅ | ✅ | Pass |
| Safari | 17+ | ✅ | ✅ | Pass |
| Firefox | 120+ | ✅ | ❌ | Pass |

**截图证据**:
- 截图1: `docs/screenshots/milestone_X_chrome.png`
- 截图2: `docs/screenshots/milestone_X_safari.png`

### 2.4 性能测试（如适用）

**Lighthouse报告**:
```bash
lighthouse http://localhost:3003 --output html --output-path report.html

# 结果:
# Performance: __/100
# Accessibility: __/100
# Best Practices: __/100
# SEO: __/100
```

**压测结果**（如适用）:
```bash
locust -f tests/performance/locustfile.py --users 10 --run-time 5m

# P50延迟: __s
# P95延迟: __s
# P99延迟: __s
# 错误率: __%
```

---

## 3. 回归测试证据

### 3.1 现有测试套件

```bash
# 运行全量测试
pytest

# 结果:
===== test session starts =====
collected 138 items

tests/test_auth.py ........................... [ 18%]
tests/test_rag.py ............................. [ 38%]
tests/test_aiops.py ........................... [ 58%]
tests/test_database.py ........................ [ 78%]
tests/smoke/test_all.py ....................... [100%]

===== 138 passed in 45.2s =====
```

**测试通过率**: __/__ (100%)

### 3.2 前端Smoke测试

**21个场景清单**:
- [ ] 1. 登录功能
- [ ] 2. 聊天功能
- [ ] 3. 文件上传
- [ ] 4. AIOps诊断
- [ ] 5. 数据库查询
- [ ] 6. 用户菜单
- [ ] 7. 权限管理
- [ ] ... (列出所有21个)
- [ ] 21. 退出登录

**结果**: __/21 Pass

### 3.3 RAG Baseline验证（如适用）

```bash
python -m evals.rag_layer.run_suite

# 结果:
Retrieval Accuracy: __%
Answer Accuracy: __%
Baseline变化: __ → __ (Δ__%)
```

**门禁检查**:
- [ ] Baseline未下降>3% ✅
- [ ] 新文档命中率≥50% ✅

---

## 4. 文档同步证据

### 4.1 更新的文档清单

- [ ] `DEVELOPMENT_LOG.md` 已更新
  - 添加日期: ____________
  - 记录内容: ____________

- [ ] `PROJECT_STATE.md` 已更新（如适用）
  - 更新内容: ____________

- [ ] 技术文档已更新（如适用）
  - [ ] `docs/frontend_architecture.md`
  - [ ] `docs/api_reference.md`
  - [ ] ...

### 4.2 milestone_evidence归档

- [ ] 本证据文件已保存到: `docs/milestones/weekX_evidence.md`
- [ ] 截图已保存到: `docs/screenshots/`
- [ ] 测试报告已保存到: `docs/test_reports/`

---

## 5. 风险与遗留问题

### 5.1 已知问题

**问题1**: ____________
- 影响范围: ____________
- 严重程度: P0 / P1 / P2
- 计划修复时间: ____________

**问题2**: ____________
- 同上

### 5.2 技术债务

**债务1**: ____________
- 描述: ____________
- 后续计划: ____________

### 5.3 依赖外部项

**依赖1**: ____________
- 状态: 已完成 / 进行中 / 阻塞
- 预计完成: ____________

---

## 6. 验收决策

### 里程碑验收标准

**功能完整性**:
- [ ] 所有计划功能已实现
- [ ] 关键用户场景已验证
- [ ] 边界条件已测试

**质量标准**:
- [ ] 测试覆盖率达标
- [ ] 代码审查通过
- [ ] 性能指标达标（如适用）

**文档标准**:
- [ ] 代码有注释
- [ ] 技术文档已更新
- [ ] 用户文档已更新（如适用）

### 最终决策

**验收结果**: ✅ 通过 / ❌ 不通过 / ⚠️ 有条件通过

**签字**:
- 开发者: ____________ 日期: ____________
- 审查者: ____________ 日期: ____________（如有）

**备注**:
____________

---

## 附录

### A. 相关链接
- PR: ____________
- Issue: ____________
- 设计文档: ____________

### B. 参考截图
- 截图1: ____________
- 截图2: ____________

### C. 测试数据
- 测试数据集: ____________
- 测试环境: ____________
