# M5.4 worker 健康与故障维护

本阶段只在隔离 MySQL/Redis 与合成模型链路验收；真实云调用新增 0，原有 10 次额度已经用尽。正式开关、配置、校园数据和历史迁移没有修改。

## 本地健康契约

`python -B -m app.assistant.health` 只读取容器内固定 `/tmp/campus-assistant-health.json`，不读取配置、连接数据库/Redis、请求模型或 MCP。输出只有 `healthy` / `unhealthy`，退出码 0 / 1。探测面向 Linux 容器，其他平台安全返回不健康。

标记严格限定 pid、heartbeat、maintenance、mode 四字段；时间使用单调时钟。写入同目录临时文件后原子替换。探测要求进程仍存在、心跳不超过 30 秒、最近成功维护不超过 60 秒；缺少、损坏、过大、多字段、非法/未来时间都拒绝。运行循环每轮更新存活；只有孤儿恢复和正文清理均成功后更新维护时间。两个开关任一关闭仍执行维护，模式为 maintenance；两个均启用则为 active。

`serve` 的回调可注入，默认不写文件；只有独立 worker 的 `main` 创建写入器。导入模块和既有测试不会自动生成健康标记。启动首轮总会维护，避免容器单调时钟不足 5 秒时跳过。Compose 在现有只读容器及 `/tmp` tmpfs 上增加本地 healthcheck：10 秒间隔、3 秒超时、连续 3 次失败、20 秒启动宽限。

Docker 的 unhealthy 状态不会自动触发 `restart: unless-stopped`；该策略只在进程退出时重启。维护异常使 worker 退出，维护阻塞使心跳过期并产生 unhealthy，需运维处理。此探测不改变公共 `/api/ready` 的 MySQL/Redis 语义，也不保证 MCP/模型上游可用。

## TDD 记录

- 新增测试后、实现前，F 盘 Python 执行 `python -B -m pytest -q -p no:cacheprovider tests/test_assistant_worker.py`：4 失败、4 通过，10.46 秒。四个失败均为 `serve() got an unexpected keyword argument 'heartbeat'`，证明新回调契约尚不存在。
- 健康模块第一次 RED 为缺失模块导入错误；随后 CLI 行为用例实际失败：期望安全状态而 stdout 为空，stderr 为 `No module named app.assistant.health`。此时字段用例因模块不存在在 fixture 设置阶段失败，不将这些错误计为完成字段测试。
- 根代理在独立 Docker 栈复核 RED：5 失败、4 通过、11 错误，6.12 秒，分别对应上述缺失 CLI/回调与模块。之后才添加生产实现。
- 最初本地健康 RED 使用默认 pytest 临时目录，可能创建 C 盘空测试目录；后续临时文件验证改为隔离 Docker `/tmp`，不声称全部临时产物都位于 F 盘。
- GREEN（根代理执行）：`docker compose -p my-campus-ai-m5-test -f compose.assistant-test.yaml -f .workbuddy/m5-test.yaml run --rm tests python -B -m pytest -q -p no:cacheprovider tests/test_assistant_health.py tests/test_assistant_worker.py tests/test_assistant_stream_integration.py`：最终冻结源码 **33 通过、0 跳过、3 项第三方弃用警告，11.09 秒**（健康 15、worker 9、真实流式 9）。
- 较早组合验证使用同一 Compose 命令运行 `tests/test_assistant_health.py tests/test_assistant_worker.py tests/test_assistant_runs_integration.py tests/test_assistant_sessions_integration.py tests/test_assistant_budget_integration.py tests/test_assistant_stream_integration.py`：**56 通过、0 跳过、4 项第三方弃用警告，51.60 秒**。此轮发生于最后健康/worker 用例补齐前，最终新增用例由上面的 33 项补验覆盖；不将 56 宣称为最终全部用例数。

## 验收范围与结果

健康单元覆盖缺少/损坏/过大标记、非法字段、过期/未来时间、心跳更新不能掩盖维护停滞、第一次成功维护前不健康、安全 CLI，以及真实子进程退出后新鲜标记仍不健康。子进程用例验证进程存在性，不等同于实际 worker 被 kill 后恢复。

后续新增实际 worker SIGKILL 验收补齐上述区别：`tests/test_assistant_runs_integration.py::test_sigkill_worker_recovers_after_real_30_second_lease_without_replay` 在同一隔离 Docker 命令中执行，**1 通过、0 跳过、3 项第三方弃用警告，47.13 秒**。测试子进程实际运行 serve、RunExecutor 和阻塞的合成提供方；提供方只在调用意图提交后写入并 fsync 单次派发标记。父进程核对 MySQL 意图后发送真正 SIGKILL 并确认退出码 -9。随后启动两个开关关闭的实际 serve 维护循环，等待 30 秒租约按真实 UTC 时钟自然到期；未更新租约时间、未修改 utc_now，只有测试预算日期跨进程保持一致。断言恢复在 kill 后 25–60 秒内发生，运行 failed/interrupted、唯一 usage 为 unknown 且收费 0.01 元、运行与用户/全局预算预留均释放、两个预算均只记 0.01 元，无助手回复；第二次恢复不重复收费，派发文件仍只有一行。测试支持入口只允许 my_campus_test、显式隔离标记及 /tmp 产物，队列必须仅有指定运行，最多认领一次；不创建真实模型或 MCP 客户端。

新增真实 Redis 容量验收直接调用生产 ConnectionLease/Lua：32 个不同合成用户 ID 占用全局槽，第 33 个返回 429；释放后可以重新获取并续租，finally 清理全部槽。它验证 Redis 原子容量约束，不代表 32 个实际 HTTP 客户端负载。

既有真实 MySQL/Redis 用例已在上述 56 项组合中本轮重新通过：多 worker 全局 2/每用户 1、跨日队列不派发、孤儿调用未知费用只结算一次且旧 worker 不重放、取消/登录撤销/权限变更终止并隐藏回复、7 天正文清理和过期隐藏。孤儿用例通过修改测试库租约模拟丢失 worker，不声称证明真实进程崩溃。

实际 Nginx 心跳、慢读、取消、Redis 依赖故障与恢复由独立代理验收脚本记录。具体命令和实测结果在根代理完成后补充；不可将确定性提供方的耗时表述为云模型性能。

## 文件与自查

生产改动为 `backend/app/assistant/health.py`、`backend/app/assistant/worker.py`、`compose.assistant.yaml`；测试为 `test_assistant_health.py`、`test_assistant_worker.py`、`test_assistant_stream_integration.py`。其他原有草稿保留，不由本任务暂存或提交。公开健康 API、监控平台及数据库结构均未增加。

自查：生产探测仅依赖标准库，Windows 不调用具有不同语义的 os.kill；标记读长有限且错误关闭；维护时间只在两个维护操作均成功后推进；健康标记不包含密钥、正文或用户标识。健康/维护及定向集成实现已 GREEN；整个 M5.4 仍待根代理完成实际代理验收、完整回归与独立审查后宣告完成。

## 独立审查修正

审查发现 Windows 上独立 worker 的 main 仍会创建 Linux `/tmp` 写入器，可能在维护前因目录不存在而退出。main 现在仅在 POSIX 平台创建写入器，Windows 保留原维护循环并传入 heartbeat=None；Linux 容器的健康探测保持启用。

新增用例只替换 worker 模块的 os 代理，避免全局 os.name 改动影响 pathlib；Windows 分支若创建写入器立即失败，serve 同时断言未安装文件心跳。RED 命令为 F 盘 Python `python -B -m pytest -q -p no:cacheprovider tests/test_assistant_worker.py -k windows_main`，1 失败、9 未选，4.77 秒，失败为 `Windows must not create a /tmp marker`。修复后执行完整 `tests/test_assistant_worker.py`：**10 通过，3.83 秒**。

根代理最终在同一隔离 Docker 项目运行 `tests/test_assistant_health.py tests/test_assistant_worker.py tests/test_assistant_stream_integration.py`：**34 通过、0 跳过、3 项第三方弃用警告，12.97 秒**，包括 Windows 分支回归。实际 SIGKILL 测试另如上通过；既有手动过期孤儿测试保留，与真实 kill 验收分别报告。
