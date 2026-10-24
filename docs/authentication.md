# 第三步：账号、权限和个人中心

本步在第二步已验证的 MySQL/Redis 基础上接入真实持久化的认证功能。数据库仍为独立 `my_campus`，不对接学校系统；用户表结构沿用 `0001_users`，不执行自动建表或重写已应用迁移。

## 页面与角色

| 地址 | 功能 |
| --- | --- |
| `/login` | 三种角色使用同一登录页面 |
| `/register` | 公开注册固定为学生，页面和接口均不能自行指定教师或管理员 |
| `/app` | 已登录用户的账号首页 |
| `/app/profile` | 本人资料维护 |
| `/app/password` | 校验旧密码并修改密码 |
| `/admin/users` | 管理员的用户列表、创建账号、资料/角色/启用状态管理 |
| `/status` | 第一阶段初始化和健康状态页面，保留匿名访问 |

学生、教师共用校园端个人中心，不提供独立教师工作台。管理员可创建教师、学生或管理员账号，也可分配角色；最后一个有效管理员不能被禁用或降级。前端路由从后端读取当前角色，后端接口独立检查权限。账号首页不展示未完成的课表、通知、活动或智能助手入口。

演示账号 `demo_admin`、`demo_teacher`、`demo_student` 的初始密码分别来自本地 `.env.compose` 中对应的 `CAMPUS_DEMO_*_PASSWORD`；请在本地查看，不复制到聊天或提交到 Git。也可通过注册页面创建自己的学生演示账号。重复种子不会重置已有账号密码。

## 接口

所有接口使用 `code/message/data`，错误同时使用正确 HTTP 状态，不能只检查响应体。

| 接口 | 请求及行为 |
| --- | --- |
| `POST /api/auth/register` | `username/password/name?`，固定学生；多余的角色字段被拒绝 |
| `POST /api/auth/login` | `username/password`；返回 `token` 和无密码的 `user` |
| `POST /api/auth/logout` | 撤销当前 JWT，后续请求不能继续使用该凭证 |
| `GET /api/user/me` | 返回当前登录用户信息，不接受客户端指定其他用户 |
| `PATCH /api/user/me` | 修改本人资料，不能修改角色或启用状态 |
| `POST /api/user/me/password` | `old_password/new_password`；成功后重新登录 |
| `GET /api/admin/users` | `q/page/page_size`，返回 `list/total` |
| `POST /api/admin/users` | 管理员创建指定角色账号，密码必须显式提供 |
| `PATCH /api/admin/users/{id}` | 管理员维护资料、角色和启用状态 |

密码使用 bcrypt 哈希，限制为 8 至 72 个 UTF-8 字节；中文按字节计算，不能只按字符长度判断。JWT 包含用户 ID、凭证版本、唯一 ID、签发和过期时间及固定签发者/受众。角色、状态和版本由服务端查询 MySQL，不能用客户端传入的角色或修改本地存储获得权限。

退出通过 Redis 撤销当前凭证；密码、角色、启用状态改变会更新凭证版本，使旧 JWT 失效。Redis 不可用时鉴权返回明确的服务故障，不能绕过撤销检查。登录限流也由 Redis 原子操作维护。凭证不写入 URL 或普通日志。

## 运行与验收

从仓库根目录重新构建并启动：

```powershell
docker compose --env-file .env.compose up -d --build
```

访问 <http://127.0.0.1:5173>。首次配置与 F 盘持久化目录设置仍参见 [基础设施说明](infrastructure.md)，不重新生成 `.env.compose`。

真实回归使用独立测试库和独立测试签名密钥；`compose.test.yaml` 中的固定测试密钥仅供隔离的测试容器使用，不能用于主演示或正式环境：

```powershell
docker compose --env-file .env.compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
```

前端继续执行 `npm run type-check`、`npm run build`，本步只把已接入的认证页面加入增量 TypeScript 检查，旧业务 JavaScript 并未全量迁移。

核心验收覆盖注册提权拒绝、重复用户名、错误密码、学生/教师访问管理接口、本人资料范围、退出后旧凭证失效、密码和角色状态变更后旧凭证失效、最后管理员保护。浏览器冒烟覆盖登录、资料修改、退出和直接访问后台地址。实际通过数量及验证记录在 [实施进度](progress.md) 更新；测试未运行时不能标记通过。

## 回滚

本步不改变表结构。代码回滚使用本步提交的反向提交，保留用户数据、Redis 和 `.env.compose`。已创建的演示用户、资料变更、凭证撤销均是真实数据，不通过回滚代码清空数据库。
