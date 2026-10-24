# 第五步：校园通知与活动

本步沿用前四步的 Vue 3.5 / TypeScript 增量检查、Element Plus、FastAPI 0.115、SQLAlchemy 异步 MySQL、Redis 和 Compose，完成校园通知和活动业务闭环。初始化内容是明确标记的演示数据；发布、审核、报名和取消真实持久化。不连接学校接口，也不调用模型。

## 范围与完成标准

- 通知：启用分类、分页列表、详情、标题/正文搜索，管理员分类维护及通知发布。
- 活动：分页列表、搜索、详情、报名、开始前取消、个人报名记录和管理员管理。
- 教师在共用校园端维护本人通知和活动；草稿或提交审核，管理员审核后公开。修改已发布内容须重新审核。不新增教师独立工作台。
- 学生不能维护内容，教师不能修改他人内容，校园端只查询已发布内容；停用通知分类立即隐藏关联通知。
- 活动事务、并发及权限测试通过，前端类型检查/构建、真实 Compose 联调和页面冒烟通过；提交不含真实配置和并行 AI 改动。

## 文件与调用关系

| 文件或模块 | 职责及依赖 |
| --- | --- |
| `backend/app/models/{publication,notice,activity}.py` | 内容状态、分类、容量及报名唯一约束；继承现有 UTC 微秒时间基类 |
| `backend/migrations/versions/0004_community.py` | 新增四张 InnoDB 表；历史迁移不修改，DDL 与种子分离 |
| `backend/app/services/publication_service.py` | 锁后权限重验、本人范围、版本绑定审核；复用原用户服务 |
| `backend/app/services/{notice_service,activity_service}.py` | 公开过滤、分类、内容管理、报名与取消事务，可供后续 MCP 复用 |
| `backend/app/api/{notices,activities,content_management,admin_community,owned_content}.py` | FastAPI 参数校验与鉴权；校园端、本人范围及管理员范围明确分开 |
| `backend/app/demo_community.py` | 按稳定编码补齐演示内容，不覆盖既有修改；由原 seed 显式调用 |
| `frontend/src/api/community.ts`、新增业务页面 | 复用 `campus-request.ts`；列表、详情、个人记录及共用内容管理表单 |
| `backend/tests/test_community*.py` | 输入与时区校验，以及独立真实 MySQL/Redis 中的权限、审核、并发和业务闭环 |

调用链仍为页面 → TypeScript API 封装 → FastAPI 鉴权 → 异步业务服务 → MySQL。课程管理与账号管理是已有相似实现；本步沿用其响应信封、错误 HTTP 状态、请求竞态处理、权限路由及测试方式。Redis 继续负责鉴权撤销和限流，本步不引入新的基础设施依赖。

## 页面与接口

| 页面 | 用途 |
| --- | --- |
| `/app/notices`、`/app/notices/:id` | 校园通知及详情 |
| `/app/activities`、`/app/activities/:id` | 活动列表、详情和报名/取消 |
| `/app/registrations` | 本人的有效及已取消报名 |
| `/app/my-notices`、`/app/my-activities` | 教师在共用校园端维护本人内容 |
| `/admin/notices`、`/admin/activities` | 管理员内容管理和审核 |
| `/admin/notice-categories` | 管理员分类维护 |

公开业务接口也要求登录。`GET /api/notices` 支持 `q/category_id/page/page_size`；`GET /api/activities` 支持 `q/page/page_size`。详情为 `GET /api/{notices|activities}/{id}`。分类列表是 `GET /api/notice-categories`。

管理 CRUD 位于 `/api/admin/{notices|activities}`，本人 CRUD 位于 `/api/owned/{notices|activities}`。管理员审核使用 `POST /api/admin/{kind}/{id}/review`，提交 `expected_revision`、`action: publish|reject`、`note`；退回须填写原因。分类管理位于 `/api/admin/notice-categories`。

报名：`POST /api/activities/{id}/registrations`；取消：`POST /api/activities/{id}/registrations/cancel`；本人记录：`GET /api/user/me/registrations`。参与者由服务端登录身份确定，不接受模型或客户端指定其他用户。

## 核心规则

内容状态为 `draft/pending/published/rejected`。教师只能保存草稿或提交待审；管理员可直接发布。每次修改递增 `revision`，修改会清除旧审核意见，教师修改已发布内容会撤出公开结果。管理员审核在行锁后检查版本和待审状态，旧版本返回 409，不能自动重试批准新内容。

报名按“用户 → 活动 → 报名记录”的顺序加锁，锁后重新校验身份和活动条件。活动行保存 `enrolled_count`，数据库约束人数不能超过 `capacity`，报名记录具有 `(activity_id,user_id)` 唯一约束。首次报名或取消后重新报名才增加人数；已有效报名的重复请求返回同一记录。取消保留记录并减人数，重复取消不重复减；重新报名复用原记录。存在任何报名历史的活动不能删除，可撤回发布保留历史。

活动开始前允许取消，包括活动被撤回时；开始时刻起拒绝取消。报名截止时刻起拒绝新报名；原成功报名的重复请求仍返回成功记录。容量不得降到当前有效人数以下。未发布活动的本人报名记录保留，但不展示未发布的标题、地点或正文。

API 活动时间必须携带时区，统一转换 UTC 写入 `DATETIME(6)`，响应带 `Z`。页面固定按 `Asia/Shanghai` 展示和编辑，不依赖浏览器所在时区。正文以纯文本展示，不执行 HTML。

## 启动、验证与回滚

干净的第五步提交使用既有命令，不需要新增依赖：

```powershell
docker compose --env-file .env.compose up -d --build
docker compose --env-file .env.compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
```

前端运行 `npm run type-check` 和 `npm run build`；后端使用 F 盘 Python 3.11。真实测试仅允许 `my_campus_test`，自动化不调用外部模型。`alembic check` 比较实际结构与模型，重启冒烟包含用户、课程、通知、活动和报名数据指纹。

本次工作目录同时存在另一组尚未提交的 AI 配置、依赖及模型测试。用户已确认单独保留。本步验收使用 `88e9674` 基线加本步文件的隔离快照，未把 AI 模块测试失败计为本步通过，也未安装其依赖。源码快照位于忽略目录 `.workbuddy/step5-verification`；在并行修改完成前，勿把当前未提交依赖清单视为本步验收配置。

迁移前调用 `scripts/backup_database.py`，备份和 SHA256 清单保存在 F 盘，并先用 `scripts/verify_backup.py` 在隔离测试库恢复验证。回滚优先反向提交本步代码并保留表与数据，不自动执行删表 downgrade。MySQL DDL 失败时核对版本与实际结构，用新增修复迁移处理，不自动清库。原 `.env`、旧库、知识原件和并行 AI 文件均保留。

## 第六步衔接

按原顺序进入学生手册导入和知识检索：确认资料路径/权限，提取与按章节切分，保存页码引用，使用百炼嵌入与 FAISS 构建可重建索引，验证来源准确和停用过滤。后台全功能仍暂缓。嵌入真实验收时再提示在本地配置 Key；随后 MCP 复用本步公开查询和事务服务，写操作另绑定确认动作 ID，再接 LangGraph 多轮流式助手。
