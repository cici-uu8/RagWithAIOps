### Result
{"generated_at":"2026-06-18T04:53:20.864Z","base_url":"http://127.0.0.1:9900","checks":{"title":"智能OnCall助手","home_input_visible":true,"login_visible_user":true,"user_menu_text":"个人资料 我的权限 文件管理 数据库能力\n执行看板\n退出登录","user_menu_has_file_manager":true,"file_manager_visible":true,"loading_state_visible_during_chat":true,"chat_answer_visible":true,"loading_state_cleaned_after_chat":true,"error_card_visible":true,"error_trace_visible":true,"trace_header_on_auth_or_chat":true,"no_failed_requests_except_favicon":true,"no_unexpected_console_error":true},"request_headers":[{"url":"http://127.0.0.1:9900/api/auth/me","method":"GET","x_trace_id":"fe-cj1ux0w9-1781758401540-mym0vux","x_request_id":"req-cj1ux0w9-1781758401540-cjwi1gg"},{"url":"http://127.0.0.1:9900/api/chat/sessions","method":"GET","x_trace_id":"fe-cj1ux0w9-1781758401624-nktr5ex","x_request_id":"req-cj1ux0w9-1781758401624-gjnmtld"},{"url":"http://127.0.0.1:9900/api/chat","method":"POST","x_trace_id":"fe-cj1ux0w9-1781758403729-8zu42qo","x_request_id":"req-cj1ux0w9-1781758403729-95ucrcm"},{"url":"http://127.0.0.1:9900/api/chat","method":"POST","x_trace_id":"fe-cj1ux0w9-1781758405444-l07zva0","x_request_id":"req-cj1ux0w9-1781758405444-q5xvqpb"}],"console":[{"type":"log","text":"Markdown 渲染库初始化成功"},{"type":"log","text":"[fe-cj1ux0w9-1781758401524-jkajtu7] POST /api/auth/login"},{"type":"log","text":"[fe-cj1ux0w9-1781758401524-jkajtu7] Response 200"},{"type":"log","text":"[fe-cj1ux0w9-1781758401540-mym0vux] GET /api/auth/me"},{"type":"log","text":"[fe-cj1ux0w9-1781758401540-mym0vux] Response 200"},{"type":"log","text":"[fe-cj1ux0w9-1781758401541-4tam63u] GET /api/me/profile"},{"type":"log","text":"[fe-cj1ux0w9-1781758401541-4tam63u] Response 200"},{"type":"log","text":"[fe-cj1ux0w9-1781758401624-nktr5ex] GET /api/chat/sessions"},{"type":"log","text":"[fe-cj1ux0w9-1781758401624-nktr5ex] Response 200"},{"type":"log","text":"[fe-cj1ux0w9-1781758402841-vgi5mlz] GET /api/me/profile"},{"type":"log","text":"[fe-cj1ux0w9-1781758402841-vgi5mlz] Response 200"},{"type":"log","text":"[fe-cj1ux0w9-1781758402913-q3p0sse] GET /api/documents?page=1&limit=20"},{"type":"log","text":"[fe-cj1ux0w9-1781758402913-q3p0sse] Response 200"},{"type":"log","text":"[fe-cj1ux0w9-1781758403729-8zu42qo] POST /api/chat"},{"type":"log","text":"[fe-cj1ux0w9-1781758403729-8zu42qo] Response 200"},{"type":"log","text":"[sendQuickMessage] 响应数据: {\"code\":200,\"message\":\"ok\",\"data\":{\"success\":true,\"answer\":\"浏览器 smoke mock answer\",\"sources\":[],\"trace_id\":\"trace-browser-success\"}}"},{"type":"log","text":"[fe-cj1ux0w9-1781758405444-l07zva0] POST /api/chat"},{"type":"error","text":"Failed to load resource: the server responded with a status of 500 (Internal Server Error)"},{"type":"log","text":"[fe-cj1ux0w9-1781758405444-l07zva0] Response 500"},{"type":"error","text":"发送消息失败: Error: 后端处理失败\n    at SuperBizAgentApp.normalizeError (http://127.0.0.1:9900/static/app.js?v=20260613-file-manager:425:27)\n    at SuperBizAgentApp.apiRequest (http://127.0.0.1:9900/static/app.js?v=20260613-file-manager:369:28)\n    at async SuperBizAgentApp.sendQuickMessage (http://127.0.0.1:9900/static/app.js?v=20260613-file-manager:2061:30)\n    at async SuperBizAgentApp.sendMessage (http://127.0.0.1:9900/static/app.js?v=20260613-file-manager:2031:17)"}],"failed_requests":[],"unexpected_console_errors":[]}
### Ran Playwright code
```js
await (async page => {
const outDir = 'output/playwright/month1_week1_day5_smoke';
const result = {
  generated_at: new Date().toISOString(),
  base_url: 'http://127.0.0.1:9900',
  checks: {},
  request_headers: [],
  console: [],
  failed_requests: []
};
page.on('console', msg => result.console.push({ type: msg.type(), text: msg.text() }));
page.on('requestfailed', req => result.failed_requests.push({ url: req.url(), failure: req.failure()?.errorText || '' }));
page.on('request', req => {
  if (req.url().includes('/api/chat') || req.url().includes('/api/auth/me')) {
    const h = req.headers();
    result.request_headers.push({
      url: req.url(),
      method: req.method(),
      x_trace_id: h['x-trace-id'] || '',
      x_request_id: h['x-request-id'] || ''
    });
  }
});

await page.context().clearCookies();
await page.goto('http://127.0.0.1:9900/?week1_day5_fix=20260618', { waitUntil: 'domcontentloaded' });
await page.setViewportSize({ width: 1440, height: 960 });
result.checks.title = await page.title();
result.checks.home_input_visible = await page.getByPlaceholder('问问智能OnCall助手').isVisible().catch(() => false);
await page.screenshot({ path: `${outDir}/01_home.png`, fullPage: true });

await page.getByRole('button', { name: /未登录|未 未登录/ }).click();
await page.getByRole('button', { name: '登录', exact: true }).click();
await page.getByRole('textbox', { name: '用户名' }).fill('demo_user_dept1');
await page.getByRole('textbox', { name: '密码' }).fill('Demo123!');
await page.getByRole('button', { name: '登录', exact: true }).click();
await page.waitForTimeout(1200);
result.checks.login_visible_user = await page.getByText('demo_user_dept1').first().isVisible().catch(() => false);
await page.screenshot({ path: `${outDir}/02_logged_in.png`, fullPage: true });

await page.getByRole('button', { name: /demo_user_dept1/ }).click();
result.checks.user_menu_text = await page.locator('#userAccountMenu').innerText().catch(e => `ERR:${e.message}`);
result.checks.user_menu_has_file_manager = result.checks.user_menu_text.includes('文件管理');
await page.getByRole('button', { name: '文件管理' }).click();
await page.waitForTimeout(800);
result.checks.file_manager_visible = (await page.locator('#profileModal').innerText().catch(() => '')).includes('文件管理');
await page.screenshot({ path: `${outDir}/03_file_manager.png`, fullPage: true });
await page.getByRole('button', { name: '×' }).click();

await page.route('**/api/chat', async route => {
  await page.waitForTimeout(900);
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      code: 200,
      message: 'ok',
      data: { success: true, answer: '浏览器 smoke mock answer', sources: [], trace_id: 'trace-browser-success' }
    })
  });
});
await page.getByPlaceholder('问问智能OnCall助手').fill('浏览器 smoke loading 检查');
await page.keyboard.press('Enter');
await page.waitForTimeout(250);
result.checks.loading_state_visible_during_chat = await page.locator('.loading-state-card, .loading-progress-bar').first().isVisible().catch(() => false);
await page.waitForTimeout(1400);
const bodyAfterChat = await page.locator('body').innerText();
result.checks.chat_answer_visible = bodyAfterChat.includes('浏览器 smoke mock answer');
result.checks.loading_state_cleaned_after_chat = !(await page.locator('.loading-state-card, .loading-progress-bar').first().isVisible().catch(() => false));
await page.screenshot({ path: `${outDir}/04_chat_loading_success.png`, fullPage: true });
await page.unroute('**/api/chat');

await page.route('**/api/chat', async route => {
  await route.fulfill({
    status: 500,
    contentType: 'application/json',
    body: JSON.stringify({ code: 500, message: '后端处理失败', data: { trace_id: 'trace-browser-error' } })
  });
});
await page.getByPlaceholder('问问智能OnCall助手').fill('浏览器 smoke error 检查');
await page.keyboard.press('Enter');
await page.waitForTimeout(1000);
const bodyAfterError = await page.locator('body').innerText();
result.checks.error_card_visible = await page.locator('.error-card').first().isVisible().catch(() => false);
result.checks.error_trace_visible = bodyAfterError.includes('trace-browser-error');
await page.screenshot({ path: `${outDir}/05_error_trace.png`, fullPage: true });
await page.unroute('**/api/chat');

const unexpectedConsoleErrors = result.console.filter((entry) => (
  entry.type === 'error'
  && !entry.text.includes('500')
  && !entry.text.includes('发送消息失败')
));
result.checks.trace_header_on_auth_or_chat = result.request_headers.some(h => h.x_trace_id && h.x_request_id);
result.checks.no_failed_requests_except_favicon = result.failed_requests.every(r => r.url.includes('/favicon.ico'));
result.checks.no_unexpected_console_error = unexpectedConsoleErrors.length === 0;
result.unexpected_console_errors = unexpectedConsoleErrors;
return result;
})(page);
```
### Page
- Page URL: http://127.0.0.1:9900/?week1_day5_fix=20260618
- Page Title: 智能OnCall助手
- Console: 2 errors, 0 warnings
### Events
- New console entries: .playwright-cli/console-2026-06-18T04-53-19-193Z.log#L3-L26
