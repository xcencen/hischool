# M5.5 隔离发布演练与上线手册

本轮完成发布准备，正式库、真实配置及校园数据外发开关未修改。运行源码为提交 `5f9f358` 的 Git 精确快照，位于 F:/my-campus-dev/temp/m5-release/source-5f9f358；不包含工作区技能、提示词、追踪及其他草稿。

## 复现隔离演练

在项目根目录使用 F 盘已有 Python：

```powershell
& 'F:/my-campus-dev/venvs/assistant-m1/Scripts/python.exe' -B scripts/rehearse_assistant_release.py
```

脚本固定项目 my-campus-ai-m5-release，拒绝已有项目容器；源/恢复端只允许 test-mysql/checkpoint-mysql 的 my_campus_test。另一次执行必须通过 `--output` 指定全新的 F 盘产物目录。不会加载正式 env 文件。启动临时 MySQL/Redis 后，所有阶段退出均尝试清理本次项目；清理失败必须处理后才可再次运行。

2026-11-01 实际四阶段全部通过：

1. 空库显式迁移到 0005，插入合成用户及中文分类，15 张表保存逐表行数与排序数据 SHA256。
2. mysqldump 使用 single-transaction、no-tablespaces、GTID 关闭、utf8mb4/hex-blob，二进制备份写入 F 盘；恢复到另一个独立空库，全部行摘要、表集合与版本一致。
3. 源库显式升级 0006，变为 22 张表，原校园表摘要不变；Alembic check 无差异。
4. 模拟在途调用意图和过期正文，真正启动关闭模式维护进程（无聊天、MCP 或价格配置）；未知费用 0.03 元只结算一次、预留释放、正文擦除。新运行返回 503，校园 health/ready 返回 200；进程正常退出，重复恢复计数 0，运行/用量/预算/告警财务摘要保持。

另已实际启动旧 M4 后端镜像 `my-campus-backend:m4-verified`（sha256:19e03d4fa4a9bdaf6341fe79907b56b895fc6c76695876f8ff4e6263f6818bce），连接隔离的 0006 数据库：校园 health/ready 200、关闭后新运行 503、现存四类财务数据摘要完全不变。只读挂载的探测脚本不覆盖镜像内应用源码，模型与工具派发为 0；不是正式部署。最终五阶段报告及 SQL 位于 F:/my-campus-dev/temp/m5-release/rehearsal-verified，备份 SHA256 为 `a4cd96a74e824cbf4b3fba87cfd6e6ee3bbe63bf2d55f3156664e5af5fb54c38`。真正 worker SIGKILL/自然租约恢复另见 M5.4。

旧镜像探测容器有固定名称和所有权标签，CLI 超时也在 finally 核验并清理；报告即使清理失败仍会保存，失败不会显示为通过。两项模拟 Docker 超时/清理失败测试通过，最终真实五阶段演练退出 0。探测只使用本地已验证镜像，不自动拉取旧版本。

## 发布物与检查

从 Git 快照实际构建的镜像 ID：

| 镜像 | ID |
| --- | --- |
| my-campus-backend:m5-release | sha256:aaf2edfe639d3264958a5ecff36f026a97f91c6383905e092ab68ee264413888 |
| my-campus-assistant:m5-release | sha256:0ff6d67be5113404f66d301eaf202f1d00b2884d15ac6a245aae599d0e0de79e |
| my-campus-frontend:m5-release | sha256:f23e22e48d0f9e44da88617a909f47f8cd8be1ef493a0cf28036d297cf4a9be5 |

基础/助手镜像 pip check 均通过；基础 bootstrap/campus 导入不需要 LangGraph。助手只读容器、tmpfs /tmp、移除 capabilities、无网络条件下，worker 导入和真实 PID/成功维护健康标记通过。前端镜像内类型检查及构建通过，保留已有 >500KB 主包提示；从最终镜像导出的实际生产文件通过全部 22 项合成浏览器场景。SSE Node 协议 6 项此前通过，实际代理与云验收边界见总记录。

最终精确源码快照后端全量回归：**696 通过、0 跳过，5 项第三方弃用警告，209.63 秒**，完整日志 F:/my-campus-dev/temp/m5-release/backend-tests.log。发布支持脚本另外完成独立真实演练及两项故障清理测试；它们不计入后端 696 项。整体只读审查及清理修复复查无剩余重要问题。

## 正式发布及回退顺序

- 发布前核对旧镜像 ID、配置模板版本、当前迁移版本、容量和价格版本；备份正式库到 F 盘并在独立库恢复核验。只有获批发布窗口内才迁移到 0006，不修改历史迁移。
- API/worker 共用助手策略配置；聊天密钥及显式价格只给 worker；MCP 独立委托配置只给 worker/MCP，嵌入配置只给知识/MCP。不输出 Compose 展开环境，配置变化需重新创建服务。
- 首先保持两个助手开关关闭，验证校园服务、维护 worker、健康标记、留存与财务查询。按获批范围启用后验证端到端和账本；健康检查不代表模型/MCP/权限全链路就绪，分别检查各依赖。
- 出现越权正文、重复派发/记账、无法结算的持续队列、迁移不一致或持续不可用时回退：关闭两个开关并重新创建 API，停止新任务，等待/取消在途任务并用维护 worker 结算或等待自然租约回收，确认预留释放后回退应用/页面镜像。
- 保留 0006 表及财务记录，不在已有业务或财务数据上 downgrade。结构问题采用后续新迁移；若确需灾难恢复，先隔离故障现场与账本，再依据核验过的备份和批准恢复点操作。
- Docker unhealthy 状态用于检测，不保证自动重启卡住的进程；运维需处理告警。默认取消检测可能等待约 10 秒身份心跳，不能承诺立即停止上游费用。

正式灰度前仍需人工确认：适用人群与字段、告知同意及供应商数据政策、正式聊天账号/价格/配额、发布窗口、备份保留期限与最小财务元数据留存。限定合成云验收的 10 次额度已经用尽，后续不得自动继续调用。
