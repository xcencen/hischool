# M5.3 隔离端到端验收

本验收只使用可丢弃的合成校园数据，实际经过生产 Nginx 配置、校园 API、MySQL 持久队列、`worker.serve`、`RunExecutor`、LangGraph、可信 MCP 客户端、真实 MCP HTTP、MySQL、Redis 和 FAISS。API、worker 和 MCP 在同一测试容器的独立异步任务中运行；这不证明独立进程崩溃恢复，故障恢复另由 M5.4 验证。

模型与嵌入为明确的确定性替身：模型按正式评测夹具选择工具并展示实际返回证据，嵌入返回固定向量。六个工具的身份、查询、输出白名单、引用和计费链路仍执行真实业务代码。拒绝写入、他人身份、泄密与澄清场景验证约定的响应流转，**不能证明云模型的指令遵守、工具选择或语义质量**。手册夹具为一页合成 Markdown，固定向量也不能证明语义召回质量。云验收另见 `assistant-m5.md`，不得混算。

## 文件与隔离

- `compose.assistant-e2e.yaml`：叠加独立测试编排，仅 Nginx 绑定本机 `127.0.0.1:18765`，API/MCP/数据库没有宿主端口。Nginx 直接只读挂载 `frontend/nginx.conf` 和生产前端构建。
- `backend/tests/support/assistant_e2e_server.py`：专用测试入口，复用 `test_mcp_integration.World`，显式初始化 `my_campus_test`；复用既有注入接口，不添加生产开关或绕过鉴权的路由。存在知识文档时拒绝重复种子，因此重新启动必须先销毁测试栈。
- `scripts/verify_assistant_e2e.mjs`：真实 HTTP/SSE 和 Playwright/Edge；不拦截本地接口，阻断浏览器外部地址。使用真实登录表单、两轮提交与页面重载，并保存桌面及 390px 截图。

测试配置来自 `compose.assistant-test.yaml` 中固定的合成凭证；不加载 `.env.compose`、真实聊天/知识/MCP 配置，不执行云调用。`ready.json` 只有临时合成账号密码及测试事实，不保存 JWT。全部运行产物位于 `F:/my-campus-dev/temp/m5-e2e`，不纳入提交。独立项目名为 `my-campus-ai-m5-e2e`，与 `my-campus-ai-m5-test` 不共享网络、数据库或 Redis。

## 复现

在仓库根目录执行，Docker 和 Node 使用已有 F/E 盘程序，无新增 Python/npm 依赖。镜像 `my-campus-ai-m2-test-tests:latest` 为当前固定完整依赖测试镜像。

```powershell
$env:E2E_ARTIFACT_DIR='F:/my-campus-dev/temp/m5-e2e'
$env:E2E_DIST_DIR='F:/my-campus-dev/temp/m5-ui/dist'
New-Item -ItemType Directory -Force $env:E2E_ARTIFACT_DIR | Out-Null
$m5Docker='F:/my-campus-dev/docker/app/resources/bin/docker.exe'
& $m5Docker compose -p my-campus-ai-m5-e2e -f compose.assistant-test.yaml -f compose.assistant-e2e.yaml up -d --wait test-mysql checkpoint-mysql test-redis api e2e-proxy
& 'E:/Program Files/nodejs/node.exe' scripts/verify_assistant_e2e.mjs --artifacts F:/my-campus-dev/temp/m5-e2e --playwright C:/Users/Stephen/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright --browser 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
& $m5Docker compose -p my-campus-ai-m5-e2e -f compose.assistant-test.yaml -f compose.assistant-e2e.yaml down
```

须先完成最新前端构建并放入上述 dist 目录。API 健康检查等待种子、FAISS、API 与 MCP 完成后的 `ready.json`；仅容器 Running 不能算链路已启动。重做完整干净验收先执行上述独立项目的 `down`，tmpfs 数据库随之销毁；不对其他项目运行清理命令。

## 验证内容

正式 `assistant_cases.json` 的 12 项经过真实提交与 SSE 完成：六个只读工具、今天/明天/本周课表、多轮服务端上下文、拒绝/澄清。检查实际本人课程与位置、他人课程不出现、通知/活动来源、本人报名状态、手册合成原文与文档/版本/页码/chunk/相对链接。每次运行重复原 request_key，确认只创建一个运行；完成后重新订阅，确认模型调用数与消费不变。

逐运行核对模型/工具次数、usage 数量、预留归零、usage 费用合计等于运行费用；知识嵌入按未知用量上界结算，不能记成免费。核对 24 条真实历史消息及用户日费用增量；另一合成用户读取该会话返回 404。浏览器真实登录后在新会话完成两轮，再刷新读取持久历史；桌面及移动宽度截图用于人工核对。

结果写入 `results.json`，记录每项首个 SSE 事件与完成延时。首事件是状态事件，正文为运行提交后的分段；不把它称为云模型首 Token 延时。实际通过结果由执行完成后追加。

## 本轮发现与修正

实际 MySQL 返回的 Decimal 零为 `0E-8`，原公共 DTO 使用 `str()` 后将科学计数金额传给浏览器；浏览器固定小数金额契约拒绝该运行。这是此前合成 HTTP 页面夹具没有覆盖的真实边界。新增 `test_assistant_money.py` 的 7 项测试先全部失败，覆盖 `0E-8`/`1E-8` 的运行、usage、告警和空预算输出。随后仅将公共金额投影改为 `format(value, 'f')`，保留 Decimal 计算和严格前端校验；并新增真实 MySQL/HTTP 四类 DTO 往返检查。

RED 命令为在 `backend` 使用 F 盘既有环境运行 `python -B -m pytest -q -p no:cacheprovider tests/test_assistant_money.py`，结果 **7 failed**。修正后运行该文件及 `test_assistant_conversations.py`、`test_assistant_budget.py`，结果 **37 passed**，1 项既有 Starlette/AnyIO 弃用警告。Docker 集成及最终链路结果另行追加。

验收脚本保留正式提交限流：只有明确的运行提交 HTTP 429 才以原 request_key 有界重试，最多 10 次，遵循受限 Retry-After（缺失时等 6 秒）；网络或 5xx 歧义不重放。浏览器两次提交前等待 13 秒恢复两个令牌。会话新建后等待新会话空消息视图，再填输入；发送和 SSE 响应等待用 Promise.all 收集，避免测试异步等待产生未处理拒绝。

早期重复运行中曾有一次流结束未携带 done，事后同一已成功运行的只读重订阅实际返回 status、15 个 delta 和 done，未复现；没有据此修改生产流逻辑。缺少 done 的后续失败将写入 `stream-failure.json`，包含当前公开运行状态、事件类型及受控 reason，便于定位；不把该历史失败描述为已查明或已修复。
