# Hybrid 模式验证方案 - 错误码场景分析

**目标**: 创建一个"错误码对照表"文件，验证 Hybrid 模式在精确术语匹配场景下的优势

---

## 背景分析

### 为什么需要错误码场景？

**当前问题**：
- 30 doc corpus，用户问的都是语义查询（"怎么办"）
- Dense 语义检索已经够用（81.8% 命中率）
- Hybrid 的优势没有显现出来

**Hybrid 擅长的场景**：
- 精确术语匹配：`ERROR_CODE_1234`
- 精确命令查找：`kubectl get pods`
- 专有名词定位：`InnoDB Buffer Pool`

**验证策略**：
- 创建一个包含 100+ 错误码的对照表
- 用精确错误码查询（例如："ERR_DB_001 怎么解决"）
- 对比 Dense vs Hybrid 的召回效果

---

## 方案设计

### 选项 1：查找现有错误码文件（推荐）

#### 可能的位置

**A. 已索引的文档中**
```bash
# 搜索当前 30 doc corpus
- 查找 runbook 文件中是否定义了错误码
- 查找 PDF 中是否有错误码表
```

**B. 未索引的原始文档中**
```bash
# 搜索原始文件目录
- 原始文件/06_网络获取文档/
- data/knowledge_assets/sample_dbs/
- 其他未跟踪的文档
```

**C. 代码/配置中**
```bash
# 应用代码中的错误定义
- app/models/ 中的错误码枚举
- aiops_lab/prometheus/alert_rules.yml (告警规则)
```

**优势**：
- ✅ 真实业务数据
- ✅ 符合公司实际场景
- ✅ 可以直接用于生产

---

### 选项 2：生成合成错误码表（备选）

#### 结构设计

**标准错误码表格式**：
```markdown
# 企业错误码对照表

## 数据库错误 (ERR_DB_xxx)

| 错误码 | 错误名称 | 描述 | 原因 | 解决方案 |
|---|---|---|---|---|
| ERR_DB_001 | Connection Timeout | 数据库连接超时 | 网络问题或数据库过载 | 1. 检查网络连接 2. 增加连接超时时间 |
| ERR_DB_002 | Deadlock Detected | 检测到死锁 | 多个事务互相等待 | 1. 分析死锁日志 2. 调整事务顺序 |
| ERR_DB_003 | Connection Pool Exhausted | 连接池耗尽 | 并发连接过多 | 1. 增加连接池大小 2. 检查连接泄漏 |
...

## Redis 错误 (ERR_REDIS_xxx)

| 错误码 | 错误名称 | 描述 | 原因 | 解决方案 |
|---|---|---|---|---|
| ERR_REDIS_001 | OOM Command Not Allowed | 内存不足拒绝命令 | Redis 内存达到上限 | 1. 清理过期 key 2. 增加内存 |
| ERR_REDIS_002 | Connection Refused | 连接被拒绝 | Redis 服务未启动或端口不对 | 1. 检查 Redis 状态 2. 确认端口配置 |
...

## 应用错误 (ERR_APP_xxx)

| 错误码 | 错误名称 | 描述 | 原因 | 解决方案 |
|---|---|---|---|---|
| ERR_APP_001 | Invalid Request Parameter | 请求参数无效 | 参数格式错误或缺失 | 1. 检查请求参数 2. 参考 API 文档 |
| ERR_APP_002 | Authentication Failed | 认证失败 | Token 过期或无效 | 1. 重新登录 2. 刷新 Token |
...
```

**覆盖范围**（100+ 错误码）：
- 数据库错误：30 个（MySQL、PostgreSQL、MongoDB）
- Redis 错误：20 个
- Kubernetes 错误：20 个（CrashLoopBackOff、ImagePullBackOff...）
- 应用错误：20 个（认证、授权、参数验证...）
- 网络错误：10 个（连接超时、DNS 解析失败...）

**优势**：
- ✅ 可以精确控制数量和格式
- ✅ 保证覆盖 Hybrid 优势场景
- ✅ 快速验证

**劣势**：
- ⚠️ 不是真实业务数据
- ⚠️ 需要人工生成

---

## 验证实验设计

### 步骤 1：准备错误码文档

**如果找到现有文件**：
- 检查错误码数量（目标 ≥100）
- 确认格式（Markdown table / JSON / CSV）
- Index 到知识库

**如果需要生成**：
- 生成 100+ 错误码
- 创建 Markdown 文件
- Index 到知识库

---

### 步骤 2：设计测试查询

**查询类型 A：精确错误码查询**
```
1. "ERR_DB_001 怎么解决"
2. "ERR_REDIS_005 是什么错误"
3. "ERR_APP_010 原因是什么"
4. "ERR_K8S_003 如何排查"
5. "Connection Pool Exhausted 错误怎么办"
```

**查询类型 B：错误描述查询（对照组）**
```
1. "数据库连接超时怎么办"
2. "Redis 内存不足怎么解决"
3. "应用认证失败怎么办"
```

**预期结果**：
- 类型 A：Hybrid 应该优于 Dense（精确匹配错误码）
- 类型 B：Dense 和 Hybrid 应该类似（语义查询）

---

### 步骤 3：运行对比测试

**执行**：
```python
# 类似之前的 hybrid_test.py
queries = [
    # 精确错误码查询
    ("ERR_DB_001 怎么解决", "精确错误码", "ERR_DB_001"),
    ("ERR_REDIS_005 是什么错误", "精确错误码", "ERR_REDIS_005"),
    # ... 10 个精确错误码查询

    # 错误描述查询（对照组）
    ("数据库连接超时怎么办", "语义查询", "Connection Timeout"),
    # ... 5 个语义查询
]

# 对比 dense_only vs hybrid
for query, query_type, expected in queries:
    dense_result = retrieve(query, mode="dense_only")
    hybrid_result = retrieve(query, mode="hybrid")
    # 比较结果
```

**判定标准**：
- Hybrid 提升案例 ≥3 个 → 证明 Hybrid 有用
- 特别关注"精确错误码查询"类型

---

### 步骤 4：分析结果

**如果 Hybrid 有提升**：
```
→ 证明：精确术语匹配场景，Hybrid 确实有用
→ 建议：对于包含大量错误码/命令/术语的文档，启用 Hybrid
→ 配置：可以根据 query 特征动态选择检索模式
```

**如果 Hybrid 仍无提升**：
```
→ 可能原因：
  1. BM25 参数需要调整
  2. Dense/Sparse 权重比例需要优化
  3. 错误码在文档中的分布不均匀
→ 下一步：调参优化
```

---

## 具体执行建议

### 第一步：搜索现有文件（今天，30 分钟）

**搜索范围**：

1. **当前 30 doc corpus**
```bash
# 检查 runbook 文件是否定义错误码
grep -r "ERR_" uploads/documents/process_digital_dept/
grep -r "ERROR_CODE" uploads/documents/process_digital_dept/
grep -r "错误码" uploads/documents/process_digital_dept/
```

2. **未索引的原始文档**
```bash
# 检查原始文件目录
ls -la "原始文件/06_网络获取文档/"
# 看是否有 API 文档、错误码表、故障手册
```

3. **代码中的错误定义**
```bash
# 检查应用代码
grep -r "class.*Error" app/
grep -r "ERROR_CODE" app/
# 检查告警规则
cat aiops_lab/prometheus/alert_rules.yml
```

**判定**：
- 如果找到 ≥100 个错误码 → 使用现有文件
- 如果找不到 → 生成合成错误码表

---

### 第二步：决定是否生成（如果需要）

**生成方案**：

**A. 基于现有 runbook 扩展**
```
- 当前有 CPU、磁盘、Redis、MySQL 等 runbook
- 为每个 runbook 补充"常见错误码"章节
- 例如：Redis runbook 添加 20 个 Redis 错误码
```

**B. 创建独立的错误码对照表**
```
- 创建 error_code_reference.md
- 包含 100+ 企业常见错误码
- 分类：数据库、缓存、K8s、应用、网络
```

**C. 创建 API 错误码文档**
```
- 模拟企业 API 文档
- HTTP 状态码 + 自定义错误码
- 例如：
  - 400 ERR_INVALID_PARAM：参数无效
  - 401 ERR_AUTH_FAILED：认证失败
  - 500 ERR_INTERNAL：内部错误
```

---

### 第三步：运行验证实验

**测试矩阵**：

| 查询类型 | 数量 | Dense 预期 | Hybrid 预期 |
|---|---:|---|---|
| 精确错误码 | 10 | 可能 50-60% | 应该 80-90% |
| 错误名称 | 5 | 应该 80%+ | 应该 80%+ |
| 语义描述 | 5 | 应该 80%+ | 应该 80%+ |

**成功标准**：
- Hybrid 在"精确错误码"类型中提升 ≥3 个案例
- Hybrid 在"错误名称"和"语义描述"类型中不退化

---

## 预期成果

### 如果验证成功

**证明**：
- ✅ Hybrid 在精确术语匹配场景确实有用
- ✅ 知识库内容类型影响检索模式选择
- ✅ 不是 Hybrid 不好，是之前的场景不匹配

**下一步**：
- 为包含大量术语的文档（错误码表、API 文档、命令手册）启用 Hybrid
- 考虑动态检索模式选择（检测 query 特征自动选择 dense/hybrid）
- 扩展到更多术语密集型文档

---

### 如果验证失败

**可能原因**：
1. BM25 参数不合适（k1/b 需要调整）
2. Dense/Sparse 权重比例不对
3. 错误码在文档中的密度不够（TF-IDF 权重低）

**下一步**：
- 调整 BM25 参数
- 调整 dense/sparse 权重（当前可能是 0.5/0.5）
- 增加错误码在文档中的出现频率

---

## 给小白的解释

**为什么要做这个实验？**

**之前的问题**：
- 用户问"CPU 高怎么办"（语义问题）
- Dense 语义搜索已经够用了
- Hybrid（语义+关键词）没显示出优势

**现在的想法**：
- 创建一个"错误码对照表"（例如：ERR_DB_001 = 数据库连接超时）
- 用户查"ERR_DB_001 怎么解决"（精确错误码）
- Dense：可能找到"数据库"或"连接"的文档（相关但不精确）
- Hybrid：应该精确找到"ERR_DB_001"这个错误码 ✅

**类比**：
- 之前：在 30 本书的图书馆找"关于 CPU 的书"（语义搜索够用）
- 现在：在图书馆找"书号 ISBN 978-3-16-148410-0"（需要精确匹配）

**预期**：
- 如果 Hybrid 在错误码查询上表现更好
- 证明：不是 Hybrid 不好，是之前的场景不适合
- 未来：对于包含大量术语的文档，应该用 Hybrid

---

## 当前建议

### 立即执行（不修改文件）

1. **搜索现有错误码文件**
   ```bash
   # 在 runbook 文件中搜索
   # 在原始文档中搜索
   # 在代码中搜索
   ```

2. **评估数量和质量**
   - 是否 ≥100 个错误码？
   - 格式是否清晰？
   - 是否可以用于测试？

3. **决定下一步**
   - 如果找到：直接用现有文件验证
   - 如果没找到：生成合成错误码表
   - 给出明确的执行建议

---

**先不修改任何文件，先分析现有资源，再决定最佳方案。**
