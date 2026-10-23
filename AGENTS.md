# AGENTS.md

本文记录当前仓库已确认的信息及用户明确指定的工作约定。文中路径相对于项目根目录；TODO 表示尚未确认或尚未配置的事项。

## 当前有效入口：my-campus 第二步（2026-10-24）

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

以下原脚手架概况、入口、依赖与副作用描述作为旧业务参考保留；与当前第二步入口不一致时，以上述第二步约定为准。下文的密钥保护、提交和推送要求继续有效。

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
