# my-campus：第二步基础设施与演示账号

本步建立独立的 MySQL、Redis、异步数据库访问、Alembic 迁移、演示账号初始化和 RQ worker。前端仍是第一步的初始化页面；注册登录接口、角色工作台和其他业务页面在后续步骤实现。

## 目录与职责

| 文件 | 职责 |
| --- | --- |
| `compose.yaml` | MySQL 8.4、Redis 7.4、初始化任务、API、前端、worker 的运行编排 |
| `compose.test.yaml` | 独立的 MySQL/Redis 集成测试环境，使用 `my-campus-test` 项目名 |
| `scripts/setup_local.py` | 首次生成本地 Compose 配置与随机密码，不覆盖已有配置 |
| `backend/app/config.py` | 显式读取 `CAMPUS_*` 配置，限制新库目标，禁止误用旧配置 |
| `backend/app/database.py` | SQLAlchemy 2 异步会话工厂与模型基类，不在导入时连接或建表 |
| `backend/app/models/user.py` | 学生、教师、管理员三角色的用户模型 |
| `backend/migrations/`、`backend/alembic.ini` | 显式管理表结构与迁移版本 |
| `backend/app/seed.py` | 按固定用户名补齐演示账号，不覆盖已有密码、角色或资料 |
| `backend/app/initialize.py` | 按顺序运行迁移和演示账号初始化 |
| `backend/app/worker.py` | 独立 RQ worker；本步仅就绪，不接入知识处理任务 |
| `backend/tests/test_foundation.py` | 无外部服务的配置隔离、懒连接、种子和离线迁移测试 |
| `backend/tests/test_infrastructure_integration.py` | 真实 MySQL/Redis 的独立集成验收 |

旧 `backend/.env`、`backend/.venv` 和旧数据库保留。本步按计划迁移公共配置、数据库与用户模型，其他旧业务模块仍未挂载；原始源码可从基线提交恢复。不执行旧 `sql/backend.sql`，不使用旧批处理启动脚本。

## 环境与首次准备

开发运行环境、依赖、缓存以及容器持久化数据统一放在 **`F:\my-campus-dev`**；源码继续位于 E 盘。Python 必须为 **3.11**；前端 Node 版本遵循 `frontend/package.json`。第一步已有本地环境的安装方式见 [initialization.md](initialization.md)。

完整验收还需要可用的 Docker Desktop（Linux 容器）及 Docker Compose。Docker Desktop 的镜像和虚拟磁盘位置应由用户在 Docker Desktop 设置中配置到 F 盘，再拉取镜像；仓库不会自动安装 Docker 或迁移用户已有镜像。未安装 Docker 时可以完成单元测试与离线 SQL 检查，不能把它们当作真实 MySQL/Redis 验收。

在仓库根目录执行首次配置生成。命令不读取旧 `.env`，也不会输出生成的密码：

```powershell
& F:\my-campus-dev\venvs\backend\Scripts\python.exe scripts/setup_local.py --data-root F:/my-campus-dev/data
```

生成的根目录 `.env.compose` 用于当前新环境，已被 Git 忽略。它包含数据库密码、JWT 密钥和三种演示账号密码，不能提交、分享或粘贴到聊天里。若文件已存在，脚本拒绝覆盖；应先核对现有配置，而不是重新生成密码。后端实际仅读取进程中的 `CAMPUS_*`，由 Compose 注入；不会自动加载旧 `backend/.env`。

主要配置：

| 变量 | 用途 |
| --- | --- |
| `APP_MODE` | 默认 `bootstrap`；Compose 使用 `campus` 才初始化数据库/Redis 客户端 |
| `CAMPUS_DATABASE_URL` | 只接受 `mysql+asyncmy`，目标库只允许 `my_campus` 或测试库 `my_campus_test` |
| `CAMPUS_REDIS_URL` | Redis 连接地址 |
| `CAMPUS_JWT_SECRET` | 至少 32 个字符的随机密钥，本步只建立配置基础 |
| `CAMPUS_DEMO_ADMIN_PASSWORD` | `demo_admin` 首次创建时的密码 |
| `CAMPUS_DEMO_TEACHER_PASSWORD` | `demo_teacher` 首次创建时的密码 |
| `CAMPUS_DEMO_STUDENT_PASSWORD` | `demo_student` 首次创建时的密码 |

三个演示账号只用于后续功能联调。**本步没有登录页面或登录接口，账号创建成功并不代表认证模块已交付。** 公开注册固定为学生、教师和管理员由后台分配等规则留到认证步骤验收。

## 启动与检查

在仓库根目录启动：

```powershell
docker compose --env-file .env.compose up -d --build
docker compose --env-file .env.compose ps -a
docker compose --env-file .env.compose logs init api worker
```

初始化任务等待 MySQL 和 Redis 健康后执行迁移，再补齐演示用户。API 与 worker 等待初始化成功才启动；如果初始化失败，先检查 `init` 日志，不清空数据库或删除数据目录重试。

| 地址/服务 | 说明 |
| --- | --- |
| `http://127.0.0.1:5173` | 初始化页面 |
| `http://127.0.0.1:8000/api/health` | 应用存活检查，保持第一步的响应合同 |
| `http://127.0.0.1:8000/api/ready` | `campus` 模式下的依赖就绪检查，依赖不可用时返回 503 |
| `127.0.0.1:13306` | 新 MySQL，仅绑定本机，库为 `my_campus` |
| `127.0.0.1:16379` | 新 Redis，仅绑定本机 |

容器内用服务名 `mysql:3306`、`redis:6379`，本地 Python 用上述宿主机端口。不要把旧库地址复制到新变量中。MySQL 使用 `utf8mb4`、InnoDB，应用将 UTC 时间写入 `DATETIME(6)`；面向用户的北京时间展示由后续业务页面处理。

单独运行第一步健康应用仍无需任何数据库配置：

```powershell
$env:APP_MODE = 'bootstrap'
Set-Location backend
& F:\my-campus-dev\venvs\backend\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 迁移与种子

表结构只由 Alembic 管理，应用启动不会执行 `create_all`。首次迁移只创建当前用户表和 Alembic 版本表，不启用旧课程、课表或学习计划表。

生成离线迁移 SQL（不连接数据库，不读取旧配置）：

```powershell
Set-Location backend
& F:\my-campus-dev\venvs\backend\Scripts\python.exe -m alembic upgrade head --sql
```

需要重新补齐演示账号时，在 MySQL/Redis 已运行的前提下执行：

```powershell
docker compose --env-file .env.compose run --rm init
```

种子使用 `demo_admin`、`demo_teacher`、`demo_student` 作为稳定业务键。已存在的账号不改密码、角色或资料；并发插入遇到唯一键冲突时仅执行无副作用的更新。修改 `.env.compose` 中的初始密码不会重置已有用户密码。当前服务没有密码管理接口，不以重跑种子作为密码重置方式。

## 测试与验收

本地无外部服务检查：

```powershell
$env:TEMP = 'F:\my-campus-dev\temp'
$env:TMP = $env:TEMP
$env:UV_CACHE_DIR = 'F:\my-campus-dev\cache\uv'
uv pip install --python F:\my-campus-dev\venvs\backend\Scripts\python.exe -r backend/requirements-dev.txt
Set-Location backend
& F:\my-campus-dev\venvs\backend\Scripts\python.exe -m pytest -q tests
Set-Location ../frontend
npm run type-check
npm run build
```

真实集成验收使用专门的 Compose 文件，不复用演示库。测试项目名、库名 `my_campus_test` 和 F 盘测试数据路径与主环境分离：

```powershell
docker compose --env-file .env.compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose --env-file .env.compose -f compose.test.yaml down
```

集成测试通过 `CAMPUS_INTEGRATION=1` 显式启用；缺少配置时应报告跳过，不能报告通过。需要验证：

1. 干净测试库从零执行迁移成功，真实数据类型、唯一约束与三角色正确。
2. 种子重复运行不增加账号；修改管理员资料、角色或密码后重跑仍保留修改。
3. 新账号密码为不可逆哈希，Redis 可以正常访问，worker 能连接队列。
4. 真实服务启动与重启后数据保留，健康接口仍可用；MySQL 或 Redis 暂停时就绪接口返回 503。
5. 原配置、旧数据库与旧业务源码未被访问或覆盖。

独立测试文件使用 `SimpleWorker` 验证真实 Redis/RQ 协议，HTTP 测试使用 `TestClient`。实际容器、`knowledge` worker 消费、Nginx 代理和重启保留数据，需在主 Compose 栈运行后执行以下额外冒烟检查：

```powershell
& F:\my-campus-dev\venvs\backend\Scripts\python.exe scripts/smoke_compose.py --exercise-restarts
```

该命令只操作 `my-campus` 项目的容器，会短暂停止并恢复 MySQL/Redis，再重启演示服务检查数据指纹；不删除数据。运行时避免同时修改演示用户。未加 `--exercise-restarts` 只检查 HTTP、代理、演示数据和真实 worker。Docker 未加入 PATH 时可用 `--docker` 指定其可执行文件路径。首次运行 Compose 前需停止占用 8000/5173 的本地开发服务。

记录测试命令、实际 Python 版本、通过/跳过数量和未执行原因。当前步骤只有真实 Compose 验收完成后才进入下一步；没有 Docker 的情况下保留“等待环境验收”，不以离线检查代替。

## 停止、备份与回滚

正常停止保留数据：

```powershell
docker compose --env-file .env.compose down
```

MySQL 和 Redis 使用 F 盘持久化目录。不要使用删除数据目录或清空卷作为故障处理。后续任何已有数据的结构变更前，应先备份 `my_campus` 并验证可恢复，再执行迁移；备份文件也应放在 F 盘受控目录，不能加入 Git。

本步代码回滚使用对应提交的反向提交，保留 `.env.compose`、MySQL/Redis 数据和旧源码。迁移失败时停止并检查 MySQL 的实际表结构及 Alembic 版本；MySQL DDL 不保证整体事务回滚，不能假定失败后库仍为空。初始迁移的 `downgrade` 会删除新用户表，仅可用于确认可丢弃的测试环境；已有业务数据时优先用修复迁移，不能自动降级清库。

本步未接入学校接口、模型、MCP、FAISS、知识处理或业务工作台。后续模型仍按已确定的百炼北京 `deepseek-v4.1-flash`，不会自动改成其他型号。
