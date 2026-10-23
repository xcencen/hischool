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

- 状态：代码及无服务检查完成，**等待真实容器验收**；未进入第三步。
- 交付：异步 SQLAlchemy/asyncmy、新库白名单、UTC 微秒时间、三角色用户模型、Alembic、幂等种子、Redis/RQ worker、Compose 及独立测试编排。
- 本地验证：Python 3.11 编译通过；44 项测试通过，4 项 MySQL/Redis 集成测试明确跳过；前端类型检查及生产构建通过。
- 编排验证：两个文件通过 YAML 语法检查及实际 `docker compose config --quiet` 检查，不打印展开后的密码。
- 测试修复：Windows 事件循环自身的本机连接曾被懒连接测试误判；检测已移入事件循环内部，数据库连接拦截保留。
- 独立配置：`.env.compose` 已生成随机密码，不提交、不打印、不覆盖原 `backend/.env`；MySQL/Redis 演示和测试数据目录分离，均在 F 盘。
- 环境阻塞：Docker CLI 与 Compose 已安装到 `F:\my-campus-dev\docker\app`，虚拟磁盘位于其 `data` 目录；引擎状态为 stopped。启动日志报告 `WslHypervisorNotRunning` / `HCS_E_HYPERV_NOT_INSTALLED`。BIOS 虚拟化已开启，但 Windows hypervisor 尚未运行。检查系统可选功能需要管理员权限，尚未修改系统功能或重启电脑。
- 未运行：真实迁移/种子、MySQL/Redis 集成、镜像构建与容器启动、真实 worker、代理及重启持久化冒烟。已准备 [执行说明](infrastructure.md) 和 `scripts/smoke_compose.py`，环境就绪后接着验收，不能把跳过算作通过。
- 保留：旧数据库未连接、原本地配置校验值未变；旧业务 API/服务/页面未挂载，旧源码可由基线恢复。README 原有未提交改动和 `.vscode/` 本地文件单独保留。

Windows 虚拟机平台/WSL2 的启用与重启要求参见 [Microsoft WSL 排错](https://learn.microsoft.com/en-us/windows/wsl/troubleshooting)，Docker 前提参见 [官方安装说明](https://docs.docker.com/desktop/setup/install/windows-install/)。需要先由用户完成系统环境准备，再恢复此步联调。

## 后续顺序

第二步真实验收通过后，按原计划逐步进入认证与权限、课程课表、通知和活动闭环、个人中心和管理、知识导入及检索、MCP/LangGraph 流式助手、最终联调与部署说明。每步开始前说明文件范围；每步完成后运行相应检查并提交。模型阶段再提示用户配置 API，不提前请求密钥。

## Git 状态说明

当前工作分支为 `codex/my-campus-init`。此前推送至 `https://github.com/xcencen/hischool.git` 被自动审批拒绝，原因是待上传源码与该远端尚未得到明确对应授权；未通过其他方式绕过。未经确认不得声称已同步远端。
