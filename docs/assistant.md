# 第七步：AI 接入基础与私有 MCP 工具

## 本阶段范围

M1 将此前单独保留的 AI 配置、模型工厂和探测草稿整理为可选基础模块。交付配置校验、模型请求适配、显式计价、受预算保护的探测、MySQL 跨进程检查点验证和 Redis 限流修正。本阶段没有注册助手 HTTP 路由、校园 MCP 工具或对话页面；下一阶段为 M2 私有 MCP 工具层。

现有校园认证、课程、通知活动和知识检索仍沿用第六步入口。没有新增正式业务表或修改历史迁移。`AITrace`、旧提示词、旧全局日志配置等其余并行草稿继续单独保留，没有据此宣称完成会话、审计或助手编排。

## 文件与调用关系

| 文件 | 职责 |
| --- | --- |
| `backend/app/ai/settings.py` | 独立读取进程聊天配置，限制北京 HTTPS 地址、固定模型、超时和输出上限；密钥及地址不进入 repr |
| `backend/app/ai/registry.py` | 模型能力；明确 JSON Object 与 JSON Schema 的差别；不在导入时读取价格 |
| `backend/app/ai/factory.py`、`bailian.py` | LangChain 模型工厂；关闭 SDK 自动重试，使用 Chat Completions，转换百炼输出上限字段并保护模型参数 |
| `backend/app/ai/pricing.py` | Decimal 计价、价格版本和币种；缺少价格或用量时返回 unknown/null，不把思考 Token 在输出之外重复计费 |
| `backend/app/ai/probe.py`、`cli.py` | 离线配置检查与显式真实探测；只使用固定演示文本和模拟工具描述，不执行业务工具 |
| `backend/app/ai/checkpoint_probe.py` | 仅针对 `my_campus_test`，在显式授权 schema setup 后验证实际 MySQL、独立读取进程、线程隔离和探测线程清理 |
| `backend/app/infra/redis.py` | 令牌桶单位修正、参数检查、合理过期时间和安全错误信息；本阶段未挂载到业务请求 |
| `scripts/probe_llm.py`、`probe_checkpoint.py` | 兼容命令包装，转交以上新入口；旧自动调用及 SQLite 回退行为已移除 |

`app.config.load_llm_settings` 仅保留惰性兼容转发；校园 `Settings` 不再加载聊天字段。无聊天配置不会影响 bootstrap 或校园基础配置。

## 环境与依赖

- Python 3.11，源码留在 E 盘；环境、依赖、缓存、报告和测试数据放在 F 盘。
- 基础依赖继续使用 `requirements-campus.txt`、`requirements-knowledge.txt`。
- M1 可选运行依赖：`requirements-assistant.txt`，由 `requirements-assistant.in` 解析，包含 Windows/Linux 条件依赖并固定传递依赖版本。
- M1 测试依赖：`requirements-assistant-dev.txt`。
- 已解析组合：LangGraph 1.0.10、MySQL checkpointer 3.0.0、langchain-openai 1.0.3、FastMCP 2.14.7、MCP 1.30.0、langchain-mcp-adapters 0.3.2。没有使用较新 LangGraph 事件接口。
- 本轮独立环境：`F:/my-campus-dev/venvs/assistant-m1`；原 backend 环境保留。
- Docker 新增 `assistant`、`assistant-test` 目标，生产 Compose 仍显式选择原 `runtime`。

依赖重新解析命令（项目根目录）：

```powershell
uv pip compile backend/requirements-assistant.in --python F:/my-campus-dev/venvs/backend/Scripts/python.exe --universal --cache-dir F:/my-campus-dev/cache/uv --output-file backend/requirements-assistant.txt --no-header --no-annotate
```

普通基础 profile 不安装 AI SDK；对应 SDK 单元测试会明确跳过。M1 完整验收必须使用可选 profile 与独立集成环境，不能用跳过结果代替验收。

## 配置与密钥

模板：`backend/assistant.env.example`；真实配置位置约定为 `F:/my-campus-dev/config/assistant.env`，不提交真实配置。代码只读取进程环境，不自动读取任何 `.env`，也不使用旧 `backend/.env`。

必需聊天字段：`CAMPUS_LLM_API_KEY`、`CAMPUS_LLM_BASE_URL`。模型固定 `deepseek-v4.1-flash-1017`；超时 1–45 秒，默认 30 秒；输出上限 64–2048，默认 2048；思考开关只接受 true/false，默认 false。地址只允许北京官方 HTTPS 主机及 `/compatible-mode/v1`，拒绝账号密码、查询参数、片段和非标准端口。以控制台业务空间的实际北京地址为准，不据默认地址假定连通。

聊天 Key、嵌入 Key 各自显式配置，不自动回退到对方。M1 用户已授权的真实验收临时在单次隔离进程中明确映射已有 F 盘百炼凭证，用来验证该账号的聊天权限；这不等同于正式聊天部署配置。原四份保护配置须验证哈希未变。

计价字段必须完整：CNY 币种、每百万 Token 的输入/输出/缓存价格、价格版本、来源。默认不应用夜间折扣；缺失价格不允许真实探测。本轮探测采用 2026-10-25 官方北京忙时上界：输入 2、输出 8、缓存输入 0.2 元/百万 Token；这是保守估算，不是账单。价格来源：[官方价格](https://help.aliyun.com/zh/model-studio/model-pricing)、[模型及缓存价格](https://docs.bailian.console.aliyun.com/en/model-studio/deepseek-v4-1-flash)。

## 模型探测

在 backend 目录、显式将已批准配置注入当前进程后：

```powershell
F:/my-campus-dev/venvs/assistant-m1/Scripts/python.exe -B -m app.ai.cli probe
F:/my-campus-dev/venvs/assistant-m1/Scripts/python.exe -B -m app.ai.cli probe --live --max-cost-cny 5
F:/my-campus-dev/venvs/assistant-m1/Scripts/python.exe -B -m app.ai.cli probe --live --check-thinking --max-cost-cny 5
```

也可通过已构建镜像显式注入外部配置，不在命令参数中传密钥：

```powershell
docker run --rm --env-file F:/my-campus-dev/config/assistant.env my-campus-ai-m1-test-tests python -B -m app.ai.cli probe
```

- 无 `--live`：只检查配置，不建数据库/Redis/模型客户端，不写报告文件；未配置退出 2，配置有效退出 0，不表示真实连通已通过。
- `--live`：四次固定请求，分别验证 SSE 文本与 usage、auto、required、指定函数；工具只验证名称和严格参数，没有校园读写副作用。
- `--check-thinking`：另加两次同题对照，分别请求关闭和开启思考。只保存 reasoning Token 及是否观察到思考输出，不保存思考正文。没有证据时退出失败，不把缺失计数补成零。
- 普通探测输出上限 128；思考对照输出上限 1024，以容纳模型思考与回复。预留预算包含两类上限及每次 8192 输入 Token 的保守额度。
- 显式费用上限须在 (0, 5] CNY；价格缺失、预算不足、模型字段不符、参数非法、用量缺失均中止，不继续发请求。SDK 自动重试为 0，所有请求受总 120 秒截止时间限制。
- 默认只输出受控 JSON；`--report F:/my-campus-dev/temp/唯一文件名.json` 可额外保存安全摘要，以独占创建防止覆盖配置或历史证据。
- 失败报告包含已知消费与可能不完整的用量状态，不记录请求正文、模型正文、地址、Key 或原始异常。开启云追踪/SDK debug 时拒绝真实探测。
- 用户授权是本轮最多 30 次请求、总 5 元；CLI 的单次预算参数不替代人工授权，也不代表未来多进程/多用户生产预算。生产预算预留账本在 M3 实现。

探测只是能力冒烟，不代表已达到完整业务评测集的 90% 工具选择准确率。官方能力参考：[DeepSeek](https://help.aliyun.com/zh/model-studio/deepseek-api)。

## MySQL、Redis 与完整回归

`compose.assistant-test.yaml` 使用独立项目 `my-campus-ai-m1-test`，无宿主端口、无正式 env_file、无正式数据挂载；MySQL 数据为临时 tmpfs。checkpoint-mysql 与校园回归 test-mysql 分离，避免第三方检查点表干扰 Alembic 元数据检查。配置中的固定密码只用于这些隔离临时测试服务。

```powershell
docker compose -f compose.assistant-test.yaml build tests
docker compose -f compose.assistant-test.yaml up -d --wait test-mysql checkpoint-mysql test-redis
docker compose -f compose.assistant-test.yaml run --rm tests
docker compose -f compose.assistant-test.yaml down --volumes
```

最后一个命令仅清理该临时测试项目，不能用于正式 Compose。

单独检查点探测使用进程变量 `CAMPUS_CHECKPOINT_TEST_DATABASE_URL`，仅接受 `mysql+asyncmy` 与 `my_campus_test`，无默认账号、无 DSN 命令行参数、无 SQLite 自动回退。执行建表及探测须同时显式添加 `--live --allow-schema-setup`：

```powershell
python -B -m app.ai.checkpoint_probe
python -B -m app.ai.checkpoint_probe --live --allow-schema-setup
```

固定版本使用 `langgraph.checkpoint.mysql.asyncmy.AsyncMySaver`。连接参数通过 SQLAlchemy URL 解析，正确解码密码，使用 asyncmy 0.2.10 支持的超时设置。子进程只通过环境继承凭证；清理仅删除本次随机命名的探测线程，不删业务表。这里的 schema setup 只允许隔离测试库，正式检查点迁移属于后续 M3。

Redis 回归既执行模拟器的实际 Lua，也执行真实 Redis；验证 10ms 不会按 10 秒补充、时钟回退不重复补充，以及 TTL 不会过早重建满桶。

## 验证记录与边界

最终可提交源码集合由 Git 暂存区导出至 `.workbuddy/step7-m1-verification`，排除剩余并行草稿，在锁定依赖镜像中只读挂载执行完整回归：**435 项通过、0 跳过**，保留既有 Starlette/FAISS 的 4 项弃用警告。Windows 定向 SDK/配置/计价回归和 134 包依赖兼容性检查通过。

真实模型共执行 19 次演示请求；最终六次探测全部通过，开启时观察到思考输出及 45 reasoning Token，关闭时未观察到思考输出，缺失 Token 计数仍为 null。已知 usage 按北京忙时上界估算约 0.0107 元，诊断失败请求可能缺失 usage；全部请求的配置上界预留合计小于 1 元，未超出授权的 30 次/5 元。详细边界见 `docs/progress.md`。报告只保存于 F 盘，不提交配置或原始响应。

四份原保护配置的哈希保持不变，暂存文件扫描未发现真实 Key。本轮没有部署助手服务或修改正式知识索引；前端没有变更。

最终可选镜像构建、Linux 依赖检查和 bootstrap/离线配置冒烟通过；现有校园 health、ready 均为 200。隔离测试容器和网络已清理。

## M1 回滚

M2 实现私有 MCP 查询工具、独立 audience 的短期凭证、当前身份复验和严格输出白名单。特别注意现有通知/活动服务的 actor 是管理查询分支开关，不能直接把管理员 actor 传给校园查询工具；课表工具始终传入服务端用户，不能使用 user=None。

M1 回滚只需回退本轮源码/可选镜像；没有正式数据库迁移。已有校园 runtime/数据和知识索引不需要回滚。生产环境仍使用原 profile。隔离验证服务用上述专用项目清理，F 盘独立验证环境和安全报告可保留供复核。

## M2：私有只读 MCP 工具

M2 交付独立 Streamable HTTP 服务、六个工具和可信调用客户端。没有新增公开助手 API、会话表、生成式回答、写工具或前端页面。后续 M3 在已有校园请求鉴权之后调用本层；现有校园 API 不因 MCP 配置缺失而导入或启动 MCP。

| 工具 | 参数与返回范围 |
| --- | --- |
| `campus_get_my_schedules` | `date` 为 today/tomorrow/this_week/ISO 日期；本人选课或授课，管理员个人课表为空；最多 50 条并标明截断 |
| `campus_list_notices` | keyword、category_id、page、page_size；仅已发布且分类启用；每页最多 10 条，正文摘要 600 字符 |
| `campus_get_notice` | notice_id；同一公开范围，正文最多 4000 字符，保留详情链接和截断标记 |
| `campus_list_activities` | keyword、page、page_size；仅已发布公开摘要，不推测个人报名状态 |
| `campus_get_activity` | activity_id；已发布详情及登录者自己的报名状态，不返回参与者名单 |
| `campus_search_knowledge` | query（1–1000 字符）、top_k（1–5）；复用现有检索，返回原文、版本、章节、页序、印刷页码与鉴权原件链接 |

所有输入拒绝额外字段和隐式类型转换，不能传 user_id、role、actor、管理开关、密钥、地址或文件路径。课表服务增加可选 SQL limit，原 REST 默认行为保留。通知与活动适配始终显式 `actor=None`，管理员也不能借工具读取草稿。姓名、电话、邮箱、密码、发布者身份和审核信息不进入工具 DTO；原文中的公开文字仍按业务内容返回。

### 文件与调用链路

| 文件 | 职责 |
| --- | --- |
| `app/mcp/settings.py`、`auth.py` | 独立配置、短期凭证签发/验签、工具范围与原登录复验 |
| `app/services/identity_service.py` | HTTP 与 MCP 共用的撤销、状态、权限版本检查，强制刷新 ORM 身份 |
| `app/mcp/catalog.py` | 本地静态工具目录、严格参数、白名单 DTO、受控错误和相对引用链接 |
| `app/mcp/executor.py` | 业务服务适配、限流、截止时间、查询后身份复验、输出上限和安全事件 |
| `app/mcp/server.py`、`runtime.py` | 原生 SDK 的 HTTP 认证与调用；独立生命周期、数据库/Redis 客户端；Host/Origin/请求体限制 |
| `app/mcp/client.py` | 每次调用新签发凭证、新建 SDK 会话；禁止重定向、环境代理及凭证转发；校验本地结果模型 |
| `app/mcp/logging.py`、`__main__.py` | 显式服务入口、受控日志；不在模块导入时配置全局日志或创建资源 |
| `backend/mcp.env.example`、`compose.mcp.yaml` | 密钥模板和可选私有服务编排，无宿主端口、原件挂载或校园 JWT 签名密钥 |

调用链为：校园 Bearer JWT → 调用侧验签并查询 MySQL/Redis → 绑定原 jti、auth_version、原有效期、run_id 和单个工具的委托凭证 → MCP 原生 Bearer 认证 → 当前身份与参数检查 → Redis 限流 → 既有业务服务/FAISS → 新会话再次查询当前身份 → 严格 DTO 与引用 → 可信 SDK 客户端校验。

凭证使用独立 HS256 密钥及 `typ=campus-mcp+jwt`、固定 issuer/audience、精确 resource URL 和 `campus:read` scope。有效期最多 60 秒且不超过原登录期限。不能直接向 MCP 发送校园 JWT，也不把角色或身份参数交给模型。源登录退出、账号停用、密码/角色变化使已签发委托失效；查询等待期间发生撤销时，丢弃查询结果。工具发现只展示凭证允许的子集。

这是单个受控应用内部的委托协议，并非对外 OAuth 授权服务器。HTTP 只用于同一私有 Docker 网络或本机回环；跨主机或多租户接入必须先设计 TLS、网络策略、非对称密钥和标准授权流程。此边界依据 [MCP 官方安全建议](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices)；不允许令牌透传。

### 配置、启动及客户端抽象

真实配置使用独占创建的 `F:/my-campus-dev/config/mcp.env`，不要覆盖原文件；模板可提交，随机密钥不可提交。调用侧与服务侧显式注入同一份 MCP 配置，独立于 `CAMPUS_JWT_SECRET`。M2 服务只需要校园 MySQL/Redis、MCP 密钥和原知识嵌入配置，不需要聊天模型 Key。只读挂载 `/data/faiss`，不挂载知识原件；原件继续由校园 Bearer API 提供。

| 字段 | 默认与限制 |
| --- | --- |
| `CAMPUS_MCP_SIGNING_SECRET` | 必填，至少 32 个非空白字符，必须独立随机生成；签发侧拒绝与校园 JWT 密钥相同 |
| `CAMPUS_MCP_URL` | `http://campus-mcp:8001/mcp`；只允许私有服务名或回环、显式端口、精确路径，无查询参数/账号密码 |
| `CAMPUS_MCP_TOKEN_TTL_S` | 60，范围 1–60 秒 |
| `CAMPUS_MCP_QUERY_TIMEOUT_S` | 10，范围 1–10 秒 |
| `CAMPUS_MCP_KNOWLEDGE_TIMEOUT_S` | 55，范围 1–55 秒，仍受凭证剩余时间限制 |

在项目根目录、准备好独立密钥配置后启动可选服务：

```powershell
docker compose --env-file .env.compose -f compose.yaml -f compose.mcp.yaml --profile assistant-mcp config --quiet
docker compose --env-file .env.compose -f compose.yaml -f compose.mcp.yaml --profile assistant-mcp build campus-mcp
docker compose --env-file .env.compose -f compose.yaml -f compose.mcp.yaml --profile assistant-mcp up -d --no-deps campus-mcp
```

前提是校园 init 已完成，MySQL/Redis 已健康。配置变更后重新创建服务；restart 不更新环境。不要输出展开的 Compose 配置或容器环境。默认主编排不包含本 overlay，助手不可用不会影响校园基础服务。`/ready` 只验证 MySQL/Redis，明确不代表嵌入云服务连通；`/health` 只验证服务生命周期。二者不返回密钥或地址。

未来 M3 在已有异步应用生命周期中构建 `CampusMCPClient(campus_settings, mcp_settings, database, redis)`，调用 `await client.call(name, arguments, campus_token=token, run_id=uuid)`。客户端只信任 `catalog.TOOLS` 和本地 DTO，不加载远端描述/Schema 进入模型；每次调用单独签发单工具授权，避免并发用户共享凭证。内部 MCP 401 转为工具 unavailable，只有原校园 JWT 校验失败才返回 unauthenticated；后续公开 API 仍应将内部失败映射成 503，不清除校园 JWT。

### 限额、错误、日志与隐私

使用真实 Redis 令牌桶：默认单用户 30 次/分钟、全局 120 次/分钟，知识检索另受单用户 5 次/分钟、全局 20 次/分钟限制；容量为突发上限，按分钟速率补充，多级桶可能保守扣额。M2 数值为固定策略，修改需代码审核，未新增环境开关。Redis/身份数据库故障时拒绝执行工具。

普通工具 10 秒，知识工具 55 秒，客户端整个调用 60 秒；不自动重试 MCP 请求，取消正常传播，超时取消本地检索等待。既有嵌入客户端保留第六步受控重试。失败结果没有业务 data/citations，只含固定 reason 与 retryable；后续编排决定是否在总预算内重试或回退到原校园页面。返回体上限 64 KiB、传输上限 256 KiB、请求体上限 16 KiB。禁止浏览器 Origin、重定向、代理环境变量和非允许协议方法；不支持后台任务、资源读取、提示词接口或外部 URLs。

服务日志仅记录本地请求 ID、静态工具名、结果分类和耗时，不记录用户标识、参数、JWT、Key、地址、正文、引用全文、向量或原始异常。显式入口抑制 SDK/HTTP 调试日志；可信客户端以任务上下文过滤本次调用及子任务的依赖日志，退出后恢复其他请求的日志行为，不修改全局日志等级。不要启用云追踪。M2 无持久对话与用量表，嵌入按现有云侧用量计费；正式助手审计、总预算预留和持久用量统计属于 M3。

工具正文与手册片段属于不可信内容，未来编排只能作为证据，不得提升为系统指令、动态工具或可执行代码。正式学生个人数据留存、外发范围与生产预算仍需人工决定；本阶段自动化仅使用独立模拟账号与本地嵌入替身，没有新增付费模型或嵌入请求。

### M2 验收与回滚

自动化执行原生 MCP SDK 和真实 HTTP 服务，使用独立 `my_campus_test`、Redis DB15 和实际 FAISS。核对学生/教师本人隔离、管理员空课表、公开内容过滤、自己报名状态、严格参数、授权工具子集、原登录撤销与权限版本、等待期间撤销丢弃数据、超时取消恢复、真实限流、配置缺失和安全错误。引用同时核对持久片段、页面、原文 offset、版本、章节与服务端链接。

完整命令仍使用 `compose.assistant-test.yaml`；该文件新增 `CAMPUS_MCP_INTEGRATION=1`，完整 profile 不允许用跳过代替验收。定向命令为 `python -B -m pytest -q -p no:cacheprovider tests/test_mcp.py tests/test_mcp_client.py tests/test_mcp_integration.py`。最终全量计数与部署边界记录于 `docs/progress.md`。

M2 最终暂存快照 `.workbuddy/step7-m2-verification` 在锁定依赖镜像中只读挂载 app/tests：**496 项通过、0 跳过**，5 项第三方弃用警告。最终运行镜像从同一可提交源码构建，Linux 依赖检查通过。私有服务已启动，真实三角色的 9 次只读调用、工具发现及退出失效通过；正式库 15 张表指纹、原四份配置哈希保持不变，未新增付费云调用。临时测试使用 `-p my-campus-ai-m2-test` 显式覆盖项目名，清理亦仅针对该临时项目；不清理正式项目。

回滚先停止并移除单个 `campus-mcp` 服务，再回退本轮源码和可选镜像；不要对正式项目执行 down --volumes。无需数据库迁移或知识索引恢复。密钥疑似泄露时重新生成独立 MCP 密钥并重新创建服务与调用侧，所有旧委托随即失效；正常轮换亦如此。现有校园 runtime、业务数据和知识原件保持使用原配置。
