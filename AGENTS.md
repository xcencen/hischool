# AGENTS.md

本文记录当前仓库已确认的信息及用户明确指定的工作约定。文中路径相对于项目根目录；TODO 表示尚未确认或尚未配置的事项。

## 当前有效入口：第七步 M1 接入基础（2026-10-25）

- 本轮用户明确要求编写并验证下一待办，已结束此前只读模式；本阶段为 M1 接入基础与能力验证，尚未注册助手 API、MCP 业务工具、LangGraph 对话图或助手页面。校园业务入口继续使用第六步。
- `app/ai/` 提供独立聊天配置、固定模型工厂、百炼 Chat Completions 参数适配、Decimal 计价与显式探测。校园 Settings 不依赖聊天配置；缺少价格/用量不记为免费，不隐式应用夜间折扣，不自动切换模型。
- M1 可选依赖位于 `requirements-assistant.in/.txt`、`requirements-assistant-dev.txt`，环境与缓存继续在 F 盘。核心组合为 LangGraph 1.0.10、MySQL checkpointer 3.0.0、langchain-openai 1.0.3、FastMCP 2.14.7、MCP 1.30.0。
- 用户已明确授权本轮北京 `deepseek-v4.1-flash-1017` 真实探测：仅演示文本和模拟工具描述，最多 30 次请求、总 5 元。已执行 19 次；流式、usage、三种工具选择与思考开关对照通过。没有执行业务工具；缺失 reasoning 计数保留 null，不保存思考正文。
- 真实验收在单次隔离进程中显式使用 F 盘已有百炼凭证核对聊天权限，未改写真实配置。正式聊天模板为 `backend/assistant.env.example`，真实配置约定仓库外 `F:/my-campus-dev/config/assistant.env`；本阶段不修改生产 Compose 注入。
- `compose.assistant-test.yaml` 为独立临时测试栈，检查点库与校园测试库分离，无宿主端口、正式 env_file 或正式数据挂载。检查点探测只允许 my_campus_test，显式 schema setup、跨进程读取及线程清理；不回退 SQLite，不在命令行传 DSN。
- Redis 令牌桶已修正毫秒/秒单位、回退时间及 TTL 边界；尚未接到业务接口。M1 暂存集合快照在 Docker Python 3.11/独立 MySQL/Redis 中 435 项通过、0 跳过；最终回归结果见 `docs/progress.md`，操作、配置及验证边界见 `docs/assistant.md`。
- 原 README、.vscode 及剩余 AI 提示词/追踪/日志草稿继续单独保留，不混入 M1 提交。后续 M2 为私有 MCP 查询工具层；写工具、正式会话表和生产预算账本不属于本轮。

## 第六步记录（2026-10-25）

- 第六步交付学生手册离线导入与知识检索代码，校园端入口 `/app/knowledge`；暂不制作全功能知识库后台、OCR、生成式回答、MCP 或 LangGraph。教师继续共用校园端。
- 用户已在 F 盘配置百炼 Key 并授权真实验收；`text-embedding-v4`、1024 维短文本连通、手册完整入库和真实语义召回已通过。密钥由 Compose 注入进程，不硬编码、不输出；缺少配置仍明确提示，不生成假向量。
- `app/knowledge/` 负责解析、独立嵌入配置、百炼客户端、FAISS、RQ 任务与 CLI；`services/knowledge_service.py` 保存文档版本、页码、片段和向量，先完整写索引文件再切换 MySQL 指针。API 为 `api/knowledge.py`，全程校园 Bearer 鉴权，原件不放公开静态目录。
- `0005_knowledge` 已应用，新增六张知识表；单例 `KnowledgeState.id=1` 为非自增。已应用迁移不可变；正式 `alembic check` 无差异。备份保存在 F 盘，曾在隔离测试库验证恢复。
- 学生手册文档 ID 1、版本 ID 1、第 1 版，268 页、1289 片段，现为 `indexed`；真实 worker 保存了 1289 条向量并启用 FAISS 索引。PDF 页序与印刷页码分开保存，扫描/图片页明确告警。三个真实问题召回的 15 条引用与持久原文、章节、页码及 offset 核对通过。
- 首次离线快照 `b8d0e4a` 加本步文件在真实 Docker Python 3.11/MySQL/Redis/FAISS 中共 305 项通过；本轮 `965cbe5` 加真实接入增强文件的快照共 375 项通过，均无跳过。自动化嵌入使用替身，另外完成真实服务验收。前端增量检查、本地及容器构建通过；真实检索、鉴权原件及移动端冒烟通过，浏览器失败替身仅验证提示和会话保持。
- 真实配置使用仓库外 `F:/my-campus-dev/config/knowledge.env`，API/worker 共用 F 盘知识原件和 FAISS 目录。本次验证官方北京兼容基址成功后只修正本地基址，其他配置字节保留。配置变更后重新创建服务；不能用单纯 restart 更新环境。Git 与 Docker 均排除 `*.env`，模板可提交。
- `python -m app.knowledge.cli probe` 仅检查进程配置，无数据库/Redis/模型依赖；`probe --live` 显式发送一条短文本，只输出安全状态。嵌入错误按受控 reason 分类，HTTP 401/403 不重试，429/5xx 最多三次，Retry-After 最多等 5 秒；单次网络 30 秒、整个调用最多 45 秒，取消正常传播。上游鉴权失败仍向校园端返回 503，不清除校园 JWT。
- API、worker、CLI 显式配置两个知识模块的 INFO 日志，重复初始化不叠加，不改变全局/httpx 日志。只记录本地关联 ID、状态、次数、条数、耗时和原因，禁止记录密钥、地址、正文、向量和上游异常对象。入库错误保存安全提示并保留有效索引及已写向量。
- 并行 AI 配置、依赖及模型测试继续单独保留，不混入本步提交。具体命令、接口、验证边界和回滚见 `docs/knowledge.md`、`docs/progress.md`。保留 F 盘环境约定、原真实配置和每步提交推送规则。

## 第五步记录（2026-10-24）

- 第五步完成校园通知、分类管理、活动、报名取消、个人报名记录以及管理员内容审核。校园端新增 `/app/notices`、`/app/activities`、`/app/registrations` 及详情页；管理端新增通知、分类、活动管理。
- 教师在共用校园端 `/app/my-notices`、`/app/my-activities` 维护本人内容，不制作独立工作台。修改已发布内容需重新审核；审核绑定 `expected_revision`，版本不符返回 409。
- `0004_community` 新增 `notice_categories/notices/activities/activity_registrations`，历史迁移不可变。API 时间带时区，UTC 微秒入库，页面固定北京时间。
- 报名与取消按用户、活动、报名记录顺序加锁，复验身份，计数与唯一约束防止超额/重复；取消保留记录、恢复名额，活动开始后禁止取消。存在报名历史的活动不能删除。
- 活跃 API 为 `api/{notices,activities,content_management,admin_community,owned_content}.py`；业务位于 `services/{publication,notice,activity}_service.py`，供后续 MCP 复用。前端使用 `api/community.ts` 和既有 `campus-request.ts`。
- 第五步隔离提交快照在 Docker Python 3.11/MySQL/Redis 中共 161 项通过，无跳过；前端增量检查、本地及容器生产构建通过，三角色页面和移动端业务闭环通过。
- 工作区另有并行 AI 基础模块改动。用户已确认它们单独保留，不混入本步提交。验收以 `88e9674` 加本步文件的 `.workbuddy/step5-verification` 快照为准，不安装或宣称通过并行 AI 依赖/模型测试。本步不需要模型 API。
- 具体范围、接口、启动、备份回滚及第六步知识检索衔接见 `docs/community.md` 和 `docs/progress.md`。保留 F 盘环境约定、原真实配置和每步提交推送规则。

## 第四步记录（2026-10-24）

- 第四步启用课程、选课关联和课程级课时，新增 `app/api/{course,schedule,admin_courses,admin_schedules}.py` 异步路由；保留第三步认证入口与 bootstrap 独立健康模式。旧学习计划和 MCP 同步实现仍不挂载。
- 校园端 `/app/schedule`、`/app/courses`、`/app/courses/:id`；管理员 `/admin/courses`、`/admin/schedules`。活跃课程请求使用 `api/courses.ts`，避免与旧 `course.js` 同名。
- 学生课表按服务端登录身份关联 `course_enrollments`，教师按 `courses.teacher_id` 查看授课；管理员维护学生名单。教师共用校园端，不制作独立工作台。
- `0002_courses` 新建三张表，`0003_course_comments` 修正验证时发现的注释差异；已应用迁移不可变。重复种子保留课程及已有周安排，初始选课只在首次创建演示课程时写入。
- 真实 Docker MySQL/Redis 回归共 127 项通过，含并发冲突课时、教师变更重查、部分更新时段校验及 Alembic 元数据一致性。前端增量类型检查与本地/容器构建通过，页面冒烟覆盖三角色和移动端。
- 迁移前备份在 F 盘，已在隔离测试库验证恢复。备份脚本、接口、页面和回滚见 `docs/courses.md`，阶段记录见 `docs/progress.md`。
- 用户要求完成第四步后先停止，不自动进入通知、活动、知识库或 AI 阶段。本步不需要模型 API。
- 继续遵守 F 盘环境/依赖/缓存/数据约定、配置保密和每步提交推送要求。

## 第三步记录（2026-10-24）

- 第二步真实 Docker/MySQL/Redis 验收已通过；第三步启用新版认证、个人中心和管理员用户管理。
- `APP_MODE=bootstrap` 保留独立健康应用；`APP_MODE=campus` 才组合新版异步 `app/api/{auth,user,admin_users}.py`。其他旧同步业务路由仍不挂载。
- 前端 `router/campus.ts` 管理 `/login`、`/register`、`/app`、`/admin/users`，匿名状态页迁至 `/status`。活跃请求使用 `utils/campus-request.ts`，避免 Vite 优先解析同名旧 `request.js`。
- 注册固定学生；管理员分配角色；教师共用校园端。JWT、Redis 撤销/限流和 MySQL 权限版本共同鉴权，密码/角色/状态变更使旧凭证失效。
- 单元与真实 MySQL/Redis 回归共 91 项通过；新增测试使用独立 JWT 签名密钥，不与主演示共享。测试命令仍为全量 `pytest -q tests` 或 `compose.test.yaml`。
- 启动、接口、演示账号和回滚见 `docs/authentication.md`，整体记录见 `docs/progress.md`。尚未启用课表、通知、活动、知识库或 AI 助手。
- 用户已明确授权将当前及后续项目提交推送到 `https://github.com/xcencen/hischool.git` 的 `codex/my-campus-init` 分支；每步提交并推送，真实配置与密钥不提交。

## 第二步记录（2026-10-24）

- 第一步初始化保留。默认 `APP_MODE=bootstrap` 仍只启用独立健康应用，不导入数据库或旧配置；显式 `APP_MODE=campus` 启用新版异步 MySQL/Redis 客户端及 `/api/ready`。
- 新版 `app/config.py` 只读取进程 `CAMPUS_*`，不会读取原 `backend/.env`。数据库只允许 `my_campus` 或 `my_campus_test`，旧实例和旧库不访问。
- `app/database.py`、用户模型已迁移为异步基础；其他旧业务暂未接入，不能直接挂载旧同步路由。初始化前源码可从 `4d60d0c` 恢复。
- 依赖：`requirements-campus.txt` 为当前运行依赖（包含 bootstrap），`requirements-dev.txt` 为测试依赖。所有安装和缓存继续在 F 盘。
- 结构由 `backend/migrations/` 和 Alembic 显式管理，演示数据独立由 `python -m app.seed` 插入，不自动建表、不覆盖已有账号。
- 编排、独立集成测试、配置生成和回滚见 `docs/infrastructure.md`。先完成第二步真实 MySQL/Redis/Compose 验收，再进入第三步；无 Docker 时不能以单元测试代替集成验收。
- 本地检查：在 `backend` 用 F 盘 Python 3.11 执行 `python -m pytest -q tests`（无服务时集成测试显式跳过）；前端继续 `npm run type-check` 和 `npm run build`。

## 第一步记录（2026-10-23）

- 本阶段仅启用 `frontend/src/main.ts` 和 `frontend/src/bootstrap/` 初始化页面，以及 `backend/app/main.py`、`backend/app/bootstrap/` 健康应用；旧业务源码保留但不接入。
- 后端使用 Python **3.11**、FastAPI 0.115，安装 `requirements-bootstrap.txt`（运行）或 `requirements-dev.txt`（含测试）；不使用旧 `requirements.txt` 和旧启动批处理脚本。
- 新后端导入不加载旧 `.env`、不导入数据库、不自动建表、不创建上传目录。唯一业务接口是 `GET /api/health`；本阶段不运行 SQL 或迁移。
- 前端增量检查：`npm run type-check`；生产构建：`npm run build`。strict 只覆盖新增 TypeScript/Vue 模块。
- 后端检查：在 `backend` 用 Python 3.11 执行 `python -m pytest -q tests/test_bootstrap.py`。
- 按用户要求，开发运行环境、依赖与缓存放在 `F:\my-campus-dev`，源码留在 E 盘。现有 `backend/.venv` 和真实 `.env` 不覆盖。
- 具体安装、启动、配置与回滚步骤见 `docs/initialization.md`。未来模型配置为百炼北京 `deepseek-v4.1-flash`，本阶段不接入模型。

以下原脚手架概况、入口、依赖与副作用描述作为旧业务参考保留；与当前有效入口不一致时，以上述最新阶段约定为准。下文的密钥保护、提交和推送要求继续有效。

## 项目概况

项目包含前端、FastAPI 后端和独立的 MCP 服务。

- 前端：Vue 3、JavaScript、Vue Router、Element Plus、Axios、Vite。
- 后端：Python、FastAPI、SQLAlchemy、PyMySQL、Pydantic Settings。
- 数据库：README 要求 MySQL 8.0+，连接由 `DATABASE_URL` 配置。
- 身份验证：JWT、PyJWT、bcrypt。
- MCP：FastMCP、LangChain MCP Adapters。
- 学习计划展示：marked、DOMPurify。

当前业务包括登录注册、用户管理、个人信息、密码修改、文件上传、课程管理、课表管理、个人学习计划和 MCP 课表查询。

README 中的功能介绍尚未完整覆盖当前业务代码。

## 目录与入口

| 路径 | 职责 |
| --- | --- |
| `backend/app/main.py` | FastAPI 入口，创建应用、自动建表、注册路由和异常处理、挂载上传目录 |
| `backend/app/config.py` | 环境变量加载及公共配置 |
| `backend/app/database.py` | 数据库连接、会话和模型基类 |
| `backend/app/api/` | HTTP 接口、请求参数和接口权限依赖 |
| `backend/app/services/` | 业务规则与数据库操作 |
| `backend/app/models/` | 用户、课程、课表、学习计划的数据库模型 |
| `backend/app/schemas/` | 接口请求和响应的数据结构 |
| `backend/app/dependencies/` | HTTP 接口及 MCP 的身份、权限检查 |
| `backend/app/common/` | 统一响应和异常处理 |
| `backend/app/utils/` | JWT、密码哈希工具 |
| `backend/mcp_server.py` | 独立 MCP 服务入口 |
| `backend/uploads/` | 上传文件目录 |
| `frontend/index.html` | 前端 HTML 入口 |
| `frontend/src/main.js` | 创建并挂载 Vue 应用 |
| `frontend/src/router/` | 页面路由和登录跳转 |
| `frontend/src/layouts/` | 公共页面布局和菜单 |
| `frontend/src/views/` | 业务页面 |
| `frontend/src/api/` | 后端接口调用函数 |
| `frontend/src/utils/` | Axios 封装、凭证存储和共享用户信息 |
| `sql/backend.sql` | 用户表及演示账号初始化脚本 |
| `.vscode/` | 本地编辑器、启动任务和调试配置 |
| `.workbuddy/tmp/` | 临时检查脚本、日志和报告 |

## 环境与配置

已确认的环境要求：

- Python：README 要求 3.12+。
- Node.js：`frontend/package.json` 声明 `^22.18.0 || >=24.12.0`。
- MySQL：README 要求 8.0+。

环境变量文件：

- `backend/.env`：本地配置文件，当前存在。
- `backend/.env.example`：后端配置模板。
- `frontend/.env.development`：前端开发环境配置。

后端配置项：

- `DATABASE_URL`、`JWT_SECRET_KEY`：代码未提供默认值。
- `JWT_EXPIRE_HOURS`：默认 `24`。
- `JWT_ALGORITHM`：默认 `HS256`。
- `MCP_HOST`：默认 `127.0.0.1`。
- `MCP_PORT`：默认 `8001`。
- `MCP_PATH`：默认 `/mcp`。

前端开发环境将 `VITE_API_BASE_URL` 设置为 `http://127.0.0.1:8000`。Vite 配置同时提供 `/api` 和 `/uploads` 的开发代理。

## 已确认的安装与运行命令

以下命令来自 README、启动脚本或 npm scripts。列出命令不表示已验证执行成功。

| 用途 | 执行目录 | 命令 |
| --- | --- | --- |
| 创建后端虚拟环境 | `backend` | `python -m venv .venv` |
| PowerShell 激活虚拟环境 | `backend` | `.\.venv\Scripts\Activate.ps1` |
| 安装后端依赖 | `backend`，已激活虚拟环境 | `pip install -r requirements.txt` |
| 安装前端依赖 | `frontend` | `npm install` |
| 启动后端 | `backend`，已激活虚拟环境 | `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000` |
| 启动前端 | `frontend` | `npm run dev` |
| 启动 MCP | `backend`，已激活虚拟环境 | `python mcp_server.py` |
| 前端构建 | `frontend` | `npm run build` |
| 预览前端构建结果 | `frontend` | `npm run preview` |
| 格式化前端源码 | `frontend` | `npm run format` |

其他启动入口：

- 根目录 `start-all.bat`：启动后端、前端、MCP 三个服务。
- `start-mcp.bat`：激活后端虚拟环境，设置 `PYTHONPATH=.`，再启动 MCP。
- `.vscode/tasks.json` 的“一键启动: 后端 + 前端”：只启动后端和前端。

TODO：后端专门的打包、构建和生产发布命令尚未确认。

## 测试与代码检查

### 单元测试

当前未找到已配置的统一单元测试命令。

- 前端 `package.json` 没有 `test` 脚本。
- 后端依赖清单未声明 pytest。
- README 提供人工冒烟检查步骤。
- `.workbuddy/tmp/` 包含课程、课表、学习计划和 MCP 的临时联调脚本。

TODO：确认正式测试框架、测试目录、执行命令和测试数据库隔离方式。

### lint 与类型检查

当前未找到统一的 lint 或类型检查命令。

- 前端没有 `lint`、`type-check` npm scripts。
- Python 编辑器配置中，`python.analysis.typeCheckingMode` 为 `off`。
- Black 被配置为 VS Code 的 Python 格式化器，未确认项目终端命令。

TODO：确认前后端 lint、类型检查工具及执行命令。

### 格式化

`npm run format` 对应：

```text
prettier --write --experimental-cli src/
```

该命令会修改前端源码。格式规则位于 `frontend/.prettierrc.json`。

TODO：确认仅检查、不写入文件的格式检查命令。

### CI

在已检查的本地项目目录及常见配置位置，未发现 CI 配置。

`.vscode/tasks.json` 是本地开发任务配置。

TODO：确认远端平台是否另行配置流水线，以及提交或合并前必须通过的检查。

## 禁止事项与已确认的副作用

README 已明确说明：

- 不要把包含真实密码的 `.env` 提交到公开仓库。
- 不要在有正式数据的数据库上误执行 `sql/backend.sql`；脚本包含删除并重建用户表的操作。

以下操作具有已确认的写入副作用：

- 导入 `backend/app/main.py` 会执行 `Base.metadata.create_all`，可能创建数据库表。
- 加载 `backend/app/config.py` 会尝试创建上传目录。
- `npm run format` 会改写前端源码。
- `course_smoke.py` 会尝试删除已有课程并创建演示课程。
- `schedule_smoke.py` 会删除查询到的历史课表并写入演示数据。
- `study_plan_smoke.py` 会清理演示用户的计划并创建新计划。
- `regression_readonly.py` 虽然名称包含 `readonly`，仍会写入本地报告。

不能将上述操作视为无写入副作用的检查。

TODO：其他代码修改禁区、分支保护和审批规则尚未确认。

## 改动提交要求（用户明确指定）

- 每次改动完成后，都必须创建 Git 提交（commit），并推送到远端仓库（git push），包括代码、配置和文档修改。
- 如果无法完成提交或推送，必须说明原因及未完成的步骤，不得声称已经提交或同步到远端。

## 提交前检查

已确认的仓库要求：

- [ ] 确认公开提交中不包含带真实密码的 `.env`。

仓库已有前端构建命令和人工冒烟检查说明，但尚未确认它们是否属于强制提交门禁。

- [ ] TODO：确认是否必须执行 `npm run build`。
- [ ] TODO：确认必须执行的单元测试及通过标准。
- [ ] TODO：确认 lint、类型检查和格式检查命令。
- [ ] TODO：确认人工冒烟检查的适用场景及测试数据准备方式。
- [ ] TODO：确认 CI 检查项目、分支规则和提交信息规范。
