# M6：正式灰度上线条件

## 已批准范围与边界

2026-11-01 用户批准实施：指定账号与页面确认、独立显式发布、本地检查与管理状态、可重复无云验收、发布准入资料。
正式开关保持关闭，不执行正式迁移，不修改真实配置，不追加云调用。M5 10 次额度已耗尽。
沿用 Python 3.11、Vue/TypeScript、MySQL/Redis、六个只读 MCP 工具；预算 0.10 元/运行、1 元/用户日、5 元/全局日，80% 告警，正文七天。
运行依赖、缓存和验收产物放 F:/my-campus-dev。当前 codex/my-campus-init 分支按文件提交推送；技能暂存、编辑器和既有草稿保持独立。

## 实施清单

- [x] M6.1 灰度准入：0007 只新增政策、资格、确认、运行快照表；默认空名单；资格/确认代次绑定运行；提交、领取、派发意图、结果提交统一校验。撤权先提交则旧运行不能发布新结果；重新授权不复活旧运行。已完成历史和费用仍归本人可读，取消/删除/维护可用。
- [x] M6.2 正式编排：固定镜像，普通启动无 build、迁移或 seed；独立显式迁移到固定 revision；隔离演练 0005→0006→0007 与关闭模式旧镜像回退，保留表和账本。
- [x] M6.3 运行监测：安全聚合、管理员状态页、本地检查；过期队列/租约/终态预留/正文清理逾期60秒告警；退出码0正常、1需处理、2无法评估；区分模型未知费用和嵌入上界计费。
- [x] M6.4 无云验收：参数化工具和产物路径、独立锁定浏览器依赖、统一检查入口、测试隔离/失败非零/所有权清理；报告标记提交和镜像。
- [x] M6.5 发布资料：当前入口与历史区分、数据外发清单、账号/告知/字段/价格额度/留存/窗口/责任人门禁。缺项保持关闭。

## 接口约定

- `GET /api/assistant/access` → `{eligible, consented, can_run, generation, policy: {version, title, text}|null}`。`can_run` 同时要求双开关、当前资格和当前确认。
- `POST /api/assistant/consent` 请求 `{policy_version}`；`DELETE /api/assistant/consent` 无正文。返回同上。版本已变返回409，名单外403；不清除校园登录。
- `GET /api/admin/assistant/access?page=1&page_size=20` → `{list:[{user_id,username,name,eligible,generation}],total,page,page_size}`；`PUT /api/admin/assistant/access/{user_id}` 请求 `{eligible,expected_generation}`，返回该条目；无记录代次为0。
- 政策通过显式本地 CLI 发布获批文本，版本不可复用；发布新版本废止旧运行资格。未发布时默认无政策。测试仅发布显著标注的合成政策。
- `GET /api/admin/assistant/operations` 返回安全聚合；具体类型由监测模块共享给前端。校园 `/ready` 不变。

## 验收要求

新增真实隔离 MySQL/Redis 准入、撤权/重授权、旧确认、角色权限、完成竞态、SSE重连、worker恢复、监测、迁移兼容用例；必要集成测试零跳过。
前端类型检查、生产构建、原22项浏览器场景和新增确认/撤权/管理状态场景；SSE协议和实际代理链路。
代码变更后重新验证镜像与回退，M5历史696项/22项仅作基线。
旧镜像不认识灰度规则，回退必须保持双开关关闭且禁止派发；不降库，不删除财务/确认记录。已经发出的上游调用仍保守结算，已到客户端的内容无法收回。
正式账号、获批告知与字段、留存期限和窗口为后续发布输入；本阶段不新增财务自动删除或外部通知平台。

## 结果记录（2026-11-03）

开发、隔离验收和只读独立审查已完成；交付状态为 **准备完成，保持关闭**。正式发布准入材料仍待批准，未执行正式0006/0007迁移、告知发布、正式账号授权或配置启用；本阶段云调用为0。

核心提交 `d194f39`，发布/验收工具运行源码提交 `c2225f3`，均已推送 `codex/my-campus-init`。本轮最后追加真实代理撤权验收、回退准入表指纹及文档；它们不改变运行镜像中的业务代码，提交见本分支历史。

| 检查 | 实际结果 |
|---|---|
| Docker Python3.11 / 独立MySQL、Redis全量后端 | 708通过、0失败、0跳过；5项既有第三方弃用警告 |
| 前端 | 类型检查和生产构建通过；32项浏览器通过（原22项加10项） |
| SSE协议 | 6通过、0跳过 |
| 标准库脚本测试 | 发布/门禁/清理8通过，本地检查3通过 |
| 实际Nginx/API/持久worker/MCP/FAISS链路 | 12合成场景及真实浏览器两轮通过；重连不重复调用或收费 |
| 真实代理撤回确认 | 6项检查通过：普通用户全局状态403、撤回结束SSE且无正文、重连403、结算释放预留、拒绝提交无新增费用且校园登录有效、重新确认不复活旧运行 |
| 运维故障 | 双订阅限额、真实心跳、慢读、Redis故障拒绝、恢复不重放、在途取消均通过 |
| 发布演练 | 0005→0006→0007、恢复前后表指纹、关闭维护、保守结算及旧镜像兼容回退均通过；追加核对四张M6表记录哈希不变 |
| 独立正式编排 | 七服务健康，本地检查退出0；重复启动全表指纹不变；只有显式migrate执行迁移，无seed |
| 新镜像 | backend/assistant的pip check、frontend的nginx版本检查均通过；实际镜像ID见报告 |

最终统一入口从已提交源码执行，无工作区覆盖：

```powershell
& 'F:/my-campus-dev/venvs/assistant-m1/Scripts/python.exe' -B scripts/verify_assistant.py --output F:/my-campus-dev/temp/m6-acceptance-c2225f3 --browser 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
```

证据位于 `F:/my-campus-dev/temp/m6-acceptance-c2225f3/report.json`、`ui/assistant-ui-report.json`、`e2e/results.json`、`e2e/operations-results.json`、`release/report.json` 与 `release-compose/report.json`。追加真实撤权证据为 `F:/my-campus-dev/temp/m6-access-c2225f3b/access-results.json`，追加回退证据为 `F:/my-campus-dev/temp/m6-release-final-20261103/report.json`。`combined-report.json` 合并真实追加阶段并记录报告与验收代码SHA256，已通过当前验收报告门禁校验；原始统一报告保持不变。

所有测试栈均核验不存在后创建，结束后清理；构建镜像与F盘证据保留供审阅。新镜像为本地验收产物，尚未发布registry；正式发布仍需核对registry digest、获批提交和完整准入材料，不能直接把本地tag填入清单。模型/嵌入均为替身，结果不证明真实模型回答质量。

审查发现的健康探针、测试镜像传递、验收报告版本/镜像绑定、回退镜像绑定与Windows UTF-8问题均已修复并验证。构建仍有既有前端包体积提示，本阶段未扩大为打包优化。原技能暂存、README/AGENTS/progress既有草稿、编辑器和提示词/追踪草稿独立保留。

后续进入正式发布前，补齐并批准试用账号、告知及外发字段、提供商账号/价格额度、备份及财务/确认记录留存、窗口/责任人和回退条件；按 `assistant-m6-release.md` 从获批版本重新核验，再单独授权迁移和启用。当前不得沿用已耗尽的M5云额度。
