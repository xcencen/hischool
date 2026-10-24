# my-campus 实施进度

## 已确认范围

沿用 Vue 3.5、TypeScript 5.9 增量迁移、Element Plus 2、Python 3.11、FastAPI 0.115、MySQL、Redis 7.4、LangGraph 1.0、MCP、FAISS 和 Docker Compose。后续模型为百炼北京 `deepseek-v4.1-flash`，启用时再验证型号权限并在本地配置 Key。

失物招领及认领交接、教师独立工作台、知识库后台全功能、Playwright 全量回归和 100% strict 迁移暂不制作。学校业务使用演示数据。

## 第一步：初始化

- 状态：本地完成，提交 `bb58fb3`；源码基线 `4d60d0c`。
- 交付：独立初始化页面、健康接口、配置模板、增量 TypeScript、Python 3.11 环境和启动文档。
- 验证：后端 4 项通过，类型检查和构建通过，浏览器连接、断开和恢复通过。
- 位置：源码在 E 盘；环境、依赖、缓存在 `F:\my-campus-dev`。

## 第二步：基础设施

- 状态：**已完成真实容器验收**，可以按顺序进入第三步。
- 交付：异步 SQLAlchemy/asyncmy、新库白名单、UTC 微秒时间、三角色用户模型、Alembic、幂等种子、Redis/RQ worker、Compose 及独立测试编排。
- 验证：Python 3.11 编译通过；Docker 独立 MySQL/Redis 环境中 **48 项测试全部通过，无跳过**；前端容器内 `npm ci`、类型检查和生产构建通过。
- 编排验证：两个文件通过 YAML 语法检查及实际 `docker compose config --quiet` 检查，不打印展开后的密码。
- 测试修复：Windows 事件循环自身的本机连接曾被懒连接测试误判；检测已移入事件循环内部，数据库连接拦截保留。
- 独立配置：`.env.compose` 已生成随机密码，不提交、不打印、不覆盖原 `backend/.env`；MySQL/Redis 演示和测试数据目录分离，均在 F 盘。
- 环境：用户启用系统功能并重启后，Docker Linux 引擎已正常运行。Docker 程序位于 `F:\my-campus-dev\docker\app`，虚拟磁盘位于其 `data` 目录。
- 真实验收：新库从零迁移和三角色种子通过；重复种子保留资料、角色和密码修改；MySQL 微秒时间和角色约束通过；真实 Redis/RQ 队列通过。
- 主环境：`scripts/smoke_compose.py --exercise-restarts` 全部通过，覆盖实际 worker、API、Nginx 代理、依赖停止后 503、恢复后 200、服务重启后用户数据指纹一致及 worker 再次执行任务。
- 问题处理：Docker Hub 认证连接曾超时，预拉取同版本官方镜像后成功；真实 MySQL CHECK 失败由 asyncmy 映射为 `OperationalError`，测试已改为严格校验错误码 3819 和 `ck_users_role`，约束本身未更改。
- 保留：旧数据库未连接、原本地配置校验值未变；旧业务 API/服务/页面未挂载，旧源码可由基线恢复。README 原有未提交改动和 `.vscode/` 本地文件单独保留。

Windows 虚拟机平台/WSL2 的启用与重启要求参见 [Microsoft WSL 排错](https://learn.microsoft.com/en-us/windows/wsl/troubleshooting)，Docker 前提参见 [官方安装说明](https://docs.docker.com/desktop/setup/install/windows-install/)。运行及验证命令见 [基础设施说明](infrastructure.md)。

## 后续顺序

第二步真实验收通过后，按原计划逐步进入认证与权限、课程课表、通知和活动闭环、个人中心和管理、知识导入及检索、MCP/LangGraph 流式助手、最终联调与部署说明。每步开始前说明文件范围；每步完成后运行相应检查并提交。模型阶段再提示用户配置 API，不提前请求密钥。

## Git 状态说明

当前工作分支为 `codex/my-campus-init`。此前推送至 `https://github.com/xcencen/hischool.git` 被自动审批拒绝，原因是待上传源码与该远端尚未得到明确对应授权；未通过其他方式绕过。未经确认不得声称已同步远端。
