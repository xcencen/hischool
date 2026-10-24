# 第四步：课程与课表

在已验证的账号和权限基础上，启用今日课表、本周课表、课程详情和管理员课程排课。所有数据来自独立演示库，管理操作真实持久化，不接学校接口。

## 页面与数据

| 页面 | 功能 |
| --- | --- |
| `/app/schedule` | 今日/本周课表，学生查看本人选课，教师查看本人授课 |
| `/app/courses` | 已启用课程查询 |
| `/app/courses/{id}` | 课程详情，课表可跳转查看 |
| `/admin/courses` | 管理员维护课程、教师、启用状态及选课学生 |
| `/admin/schedules` | 管理员维护课程日期、起止时间、节次与地点 |

教师共用校园端，不新增独立教师工作台。学生选课关联由管理员维护，本步不提供学生自助选课。公开注册的新账号没有默认课程，需先由管理员关联课程；初始 `demo_student`、`demo_teacher` 有演示课表。

旧课表源码按学生逐条保存，无法表达共享的授课安排。新版课程关联教师，学生通过 `course_enrollments` 关联课程，`schedules` 保存课程级课时；不迁移旧库。数据结构通过新增 `0002_courses` 迁移创建。验证时发现列注释遗漏，新增 `0003_course_comments` 修正；已应用的迁移均不修改。

课表日期和课时是 `Asia/Shanghai` 教学业务时间，按日期、开始时间排序；创建/更新时间继续使用 UTC `DATETIME(6)`。查询“今天”由服务端按北京时间计算，一周从周一到周日。今天没有课时显示为空，不能把其他日期的课程当作今日课程。

## 接口

所有接口要求登录并沿用 `code/message/data`；管理接口额外要求有效管理员。

| 接口 | 行为 |
| --- | --- |
| `GET /api/courses?q=` | 已启用课程列表 |
| `GET /api/courses/{id}` | 已启用课程详情，不暴露选课学生名单 |
| `GET /api/schedules/today?date=` | 本人指定日期或北京时间今日的课表 |
| `GET /api/schedules/week?date=` | 本人指定日期所在周；返回 `start_date/end_date/list` |
| `GET/POST /api/admin/courses` | 查询或创建课程 |
| `PATCH/DELETE /api/admin/courses/{id}` | 更新或删除课程；有课表关联时删除被拒绝 |
| `GET /api/admin/courses/options` | 可用教师、学生选项，只有管理员可访问 |
| `GET/PUT /api/admin/courses/{id}/students` | 查看或替换选课学生；写入 `student_ids` |
| `GET/POST /api/admin/schedules` | 查询或创建课时 |
| `PATCH/DELETE /api/admin/schedules/{id}` | 更新或删除课时 |

本人课表不由客户端指定用户 ID。课程须指派有效教师，选课关联只接受有效学生；停用课程不出现在校园端。起止时间非法、重复课程编码、授课教师或教室时间冲突均返回明确错误，不能静默覆盖。

演示种子使用稳定课程编码；一周已有课时则保留该周安排，不覆盖课程名称、地点和课时调整。演示周按北京时间生成；过周后可补充新周数据，已有周的数据不清空。初始选课只在创建演示课程时写入，管理员调整学生名单后不会被种子恢复。两门演示课程为 `DEMO-CS101`、`DEMO-CS102`，默认有周一、周三、周五三个课时。

## 迁移前备份及恢复验证

在新表迁移前执行：

```powershell
& F:\my-campus-dev\venvs\backend\Scripts\python.exe scripts/backup_database.py
```

脚本固定备份 `my-campus` 编排中的 `my_campus`，文件及 SHA256 清单写到 `F:\my-campus-dev\backups`，不输出 SQL 内容。备份含用户数据和密码哈希，保存在本地，不加入 Git。

如需验证恢复，先单独启动测试 MySQL，再将本次备份路径传入：

```powershell
docker compose --env-file .env.compose -f compose.test.yaml up -d --wait test-mysql
& F:\my-campus-dev\venvs\backend\Scripts\python.exe scripts/verify_backup.py --backup F:\my-campus-dev\backups\本次备份.sql
```

恢复脚本固定写入 `my-campus-test` 的 `my_campus_test`，会替换该测试库中备份对应的表；若测试库已有备份外的表则拒绝操作。它校验备份清单，并比较用户数量和 MySQL 表校验值。主演示库只读取，不执行降级或清空。Docker 未加入 PATH 时两个脚本均可使用 `--docker` 指定 F 盘程序路径。

## 构建、验证与回滚

完成备份后按原方式构建启动，初始化任务先迁移再补齐种子：

```powershell
docker compose --env-file .env.compose up -d --build
docker compose --env-file .env.compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
```

必要验证包括本人数据隔离、教师授课范围、管理权限、课程详情、选课角色校验、起止时间及时间冲突、关联删除保护、重复种子保留修改，并回归认证与基础设施。实际结果记录在 [实施进度](progress.md)。

通过 `docker compose --env-file .env.compose exec -T api python -m alembic check` 检查结构与模型一致。使用 `scripts/smoke_compose.py --exercise-restarts` 验证依赖故障恢复和用户、课程、选课、课时数据在重启前后的指纹一致。Docker 不在 PATH 时添加 `--docker F:/my-campus-dev/docker/app/resources/bin/docker.exe`。

回滚优先反向提交代码并保留数据；不要自动执行删除表的降级。新演示库已有数据，MySQL DDL 失败也不能假定整体回滚，应核对 Alembic 版本和实际表结构，再用修复迁移或经过验证的备份恢复。
