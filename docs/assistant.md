# 第七步 M1：AI 接入基础与能力验证

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

## 后续 M2 与回滚

M2 实现私有 MCP 查询工具、独立 audience 的短期凭证、当前身份复验和严格输出白名单。特别注意现有通知/活动服务的 actor 是管理查询分支开关，不能直接把管理员 actor 传给校园查询工具；课表工具始终传入服务端用户，不能使用 user=None。

M1 回滚只需回退本轮源码/可选镜像；没有正式数据库迁移。已有校园 runtime/数据和知识索引不需要回滚。生产环境仍使用原 profile。隔离验证服务用上述专用项目清理，F 盘独立验证环境和安全报告可保留供复核。
