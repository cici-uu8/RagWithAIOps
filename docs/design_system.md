# SuperBizAgent 视觉设计规范

**版本**: v1.0  
**创建日期**: 2026-06-17  
**适用范围**: 前端所有页面和组件  

---

## 1. 颜色规范

### 1.1 主色调

```css
/* 主色（蓝色） */
--color-primary: #3B82F6;
--color-primary-hover: #2563EB;
--color-primary-active: #1D4ED8;
--color-primary-light: #EFF6FF;
--color-primary-dark: #1E40AF;
```

**使用场景**:
- 主要操作按钮（发送、提交、确认）
- 链接
- 进度条
- 选中状态

### 1.2 状态色

```css
/* 成功（绿色） */
--color-success: #10B981;
--color-success-light: #F0FDF4;
--color-success-dark: #059669;

/* 警告（橙色） */
--color-warning: #F59E0B;
--color-warning-light: #FFFBEB;
--color-warning-dark: #D97706;

/* 错误（红色） */
--color-error: #EF4444;
--color-error-light: #FEF2F2;
--color-error-dark: #DC2626;

/* 信息（蓝色） */
--color-info: #3B82F6;
--color-info-light: #EFF6FF;
--color-info-dark: #2563EB;
```

**使用场景**:
- 成功: 已授权权限、操作成功提示、完成状态
- 警告: 可申请权限、重要提示、进行中状态
- 错误: 禁止操作、错误提示、失败状态
- 信息: 普通提示、待处理状态

### 1.3 灰阶

```css
--color-gray-50: #F9FAFB;
--color-gray-100: #F3F4F6;
--color-gray-200: #E5E7EB;
--color-gray-300: #D1D5DB;
--color-gray-400: #9CA3AF;
--color-gray-500: #6B7280;
--color-gray-600: #4B5563;
--color-gray-700: #374151;
--color-gray-800: #1F2937;
--color-gray-900: #111827;
```

**使用场景**:
- 50-100: 背景色
- 200-300: 边框、分割线
- 400-500: 辅助文字、图标
- 600-700: 次要文字
- 800-900: 主要文字、标题

### 1.4 语义色

```css
/* 权限三色 */
--color-permission-granted: var(--color-success);     /* 已授权 */
--color-permission-requestable: var(--color-warning); /* 可申请 */
--color-permission-forbidden: var(--color-error);     /* 禁止 */

/* AIOps状态 */
--color-aiops-pending: var(--color-gray-400);    /* 等待 */
--color-aiops-running: var(--color-primary);     /* 进行中 */
--color-aiops-completed: var(--color-success);   /* 完成 */
--color-aiops-failed: var(--color-error);        /* 失败 */
```

---

## 2. 字体规范

### 2.1 字体族

```css
--font-family-base: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
--font-family-mono: "Monaco", "Consolas", "Courier New", monospace;
```

### 2.2 字体大小

```css
--font-size-xs: 12px;    /* 辅助文字、时间戳 */
--font-size-sm: 14px;    /* 正文、表单 */
--font-size-base: 16px;  /* 基础文字 */
--font-size-lg: 18px;    /* 小标题 */
--font-size-xl: 20px;    /* 标题 */
--font-size-2xl: 24px;   /* 大标题 */
```

### 2.3 字重

```css
--font-weight-normal: 400;
--font-weight-medium: 500;
--font-weight-semibold: 600;
--font-weight-bold: 700;
```

**使用规则**:
- 正文: 400
- 次要标题、强调: 500
- 主要标题、按钮: 600
- 特别强调: 700

### 2.4 行高

```css
--line-height-tight: 1.25;   /* 标题 */
--line-height-normal: 1.5;   /* 正文 */
--line-height-relaxed: 1.75; /* 长文本 */
```

---

## 3. 间距规范

### 3.1 间距系统（8px基准）

```css
--spacing-1: 4px;
--spacing-2: 8px;
--spacing-3: 12px;
--spacing-4: 16px;
--spacing-5: 20px;
--spacing-6: 24px;
--spacing-8: 32px;
--spacing-10: 40px;
--spacing-12: 48px;
```

### 3.2 组件内边距

```css
/* 按钮 */
--padding-btn-sm: 6px 12px;
--padding-btn-base: 8px 16px;
--padding-btn-lg: 12px 24px;

/* 卡片 */
--padding-card: 16px;
--padding-card-lg: 24px;

/* 输入框 */
--padding-input: 8px 12px;
```

### 3.3 组件外边距

```css
/* 组件之间的间距 */
--margin-component: 16px;
--margin-section: 24px;
```

---

## 4. 圆角规范

```css
--border-radius-sm: 4px;    /* 按钮、标签 */
--border-radius-base: 6px;  /* 输入框、小卡片 */
--border-radius-md: 8px;    /* 卡片 */
--border-radius-lg: 12px;   /* 大卡片、模态框 */
--border-radius-full: 9999px; /* 圆形头像、徽章 */
```

---

## 5. 阴影规范

```css
/* 浮起 */
--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
--shadow-base: 0 1px 3px rgba(0, 0, 0, 0.1);

/* 悬浮 */
--shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
--shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);

/* 强调 */
--shadow-xl: 0 20px 25px rgba(0, 0, 0, 0.15);
```

**使用场景**:
- sm: 按钮默认状态
- base: 卡片
- md: 按钮hover、卡片hover
- lg: 下拉菜单、弹出框
- xl: 模态框

---

## 6. 动画规范

### 6.1 过渡时间

```css
--duration-fast: 150ms;      /* 按钮hover、小元素 */
--duration-base: 250ms;      /* 常规过渡 */
--duration-slow: 350ms;      /* 复杂动画 */
```

### 6.2 缓动函数

```css
--ease-in: cubic-bezier(0.4, 0, 1, 1);
--ease-out: cubic-bezier(0, 0, 0.2, 1);
--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
```

### 6.3 常用动画

```css
/* 淡入 */
@keyframes fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
}

/* 滑入 */
@keyframes slide-in {
    from {
        transform: translateY(-20px);
        opacity: 0;
    }
    to {
        transform: translateY(0);
        opacity: 1;
    }
}

/* 脉冲（加载中） */
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
```

---

## 7. 组件规范

### 7.1 按钮

```css
/* 主要按钮 */
.btn-primary {
    background: var(--color-primary);
    color: white;
    padding: var(--padding-btn-base);
    border-radius: var(--border-radius-base);
    border: none;
    font-weight: var(--font-weight-semibold);
    cursor: pointer;
    transition: all var(--duration-fast) var(--ease-out);
}

.btn-primary:hover {
    background: var(--color-primary-hover);
    box-shadow: var(--shadow-md);
}

.btn-primary:active {
    background: var(--color-primary-active);
    box-shadow: var(--shadow-sm);
}

/* 次要按钮 */
.btn-secondary {
    background: white;
    color: var(--color-gray-700);
    border: 1px solid var(--color-gray-300);
    /* 其他同btn-primary */
}

/* 危险按钮 */
.btn-danger {
    background: var(--color-error);
    color: white;
    /* 其他同btn-primary */
}
```

### 7.2 卡片

```css
.card {
    background: white;
    border-radius: var(--border-radius-md);
    padding: var(--padding-card);
    box-shadow: var(--shadow-base);
    border: 1px solid var(--color-gray-200);
    transition: all var(--duration-base) var(--ease-out);
}

.card:hover {
    box-shadow: var(--shadow-md);
    border-color: var(--color-gray-300);
}

.card-header {
    font-size: var(--font-size-lg);
    font-weight: var(--font-weight-semibold);
    color: var(--color-gray-900);
    margin-bottom: var(--spacing-4);
}

.card-body {
    font-size: var(--font-size-sm);
    color: var(--color-gray-700);
    line-height: var(--line-height-normal);
}
```

### 7.3 输入框

```css
.input {
    width: 100%;
    padding: var(--padding-input);
    border: 1px solid var(--color-gray-300);
    border-radius: var(--border-radius-base);
    font-size: var(--font-size-sm);
    line-height: var(--line-height-normal);
    transition: all var(--duration-fast) var(--ease-out);
}

.input:focus {
    outline: none;
    border-color: var(--color-primary);
    box-shadow: 0 0 0 3px var(--color-primary-light);
}

.input::placeholder {
    color: var(--color-gray-400);
}

.input:disabled {
    background: var(--color-gray-50);
    color: var(--color-gray-500);
    cursor: not-allowed;
}
```

### 7.4 标签

```css
.badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: var(--border-radius-full);
    font-size: var(--font-size-xs);
    font-weight: var(--font-weight-medium);
}

.badge-success {
    background: var(--color-success-light);
    color: var(--color-success-dark);
}

.badge-warning {
    background: var(--color-warning-light);
    color: var(--color-warning-dark);
}

.badge-error {
    background: var(--color-error-light);
    color: var(--color-error-dark);
}
```

---

## 8. 布局规范

### 8.1 容器宽度

```css
--container-xs: 480px;
--container-sm: 640px;
--container-md: 768px;
--container-lg: 1024px;
--container-xl: 1280px;
```

### 8.2 响应式断点

```css
/* 移动端 */
@media (max-width: 640px) { /* sm */ }

/* 平板 */
@media (max-width: 768px) { /* md */ }

/* 桌面 */
@media (max-width: 1024px) { /* lg */ }

/* 大屏 */
@media (max-width: 1280px) { /* xl */ }
```

---

## 9. 可访问性规范

### 9.1 对比度要求

- 正文文字：至少4.5:1（WCAG AA）
- 大文字（18px+）：至少3:1
- 交互元素：至少3:1

### 9.2 焦点可见性

```css
/* 键盘焦点 */
*:focus-visible {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
}
```

### 9.3 ARIA标签

```html
<!-- 错误提示 -->
<div role="alert" aria-live="assertive">
    错误信息
</div>

<!-- 进度条 -->
<div role="progressbar" 
     aria-valuenow="40" 
     aria-valuemin="0" 
     aria-valuemax="100"
     aria-label="诊断进度">
</div>

<!-- 按钮 -->
<button aria-label="发送消息">
    <span aria-hidden="true">→</span>
</button>
```

---

## 10. 暗色模式（Phase 4）

```css
[data-theme="dark"] {
    /* 主色调保持不变 */
    
    /* 灰阶反转 */
    --color-gray-50: #111827;
    --color-gray-100: #1F2937;
    --color-gray-200: #374151;
    --color-gray-300: #4B5563;
    --color-gray-400: #6B7280;
    --color-gray-500: #9CA3AF;
    --color-gray-600: #D1D5DB;
    --color-gray-700: #E5E7EB;
    --color-gray-800: #F3F4F6;
    --color-gray-900: #F9FAFB;
    
    /* 背景和文字 */
    --bg-primary: #1F2937;
    --text-primary: #F9FAFB;
    
    /* 卡片背景 */
    --bg-card: #374151;
}
```

---

## 11. 使用示例

### 完整的错误卡片

```html
<div class="card error-card error-red">
    <div class="card-header">
        <span class="error-icon">🔴</span>
        <span class="error-title">无法连接后端服务</span>
    </div>
    <div class="card-body">
        <p>请确认"启动企业助手.command"窗口仍在运行</p>
        <p class="text-sm text-gray-500">trace_id: <code>fe-xxx-xxx</code></p>
    </div>
    <div class="flex gap-2 mt-4">
        <button class="btn-primary">重试</button>
        <button class="btn-secondary">查看指南</button>
    </div>
</div>
```

---

## 12. 质量检查清单

**设计实现前**:
- [ ] 颜色符合规范（从CSS变量选择）
- [ ] 间距符合8px基准
- [ ] 字体大小符合规范
- [ ] 圆角符合规范

**实现后**:
- [ ] 对比度满足WCAG AA标准
- [ ] 键盘导航完整
- [ ] 有ARIA标签
- [ ] 响应式设计适配移动端
- [ ] 暗色模式兼容（Phase 4）

---

**本设计系统将在Week 0末尾创建，所有后续前端开发必须严格遵守**
