# 第七步 M4：助手聊天页面与流式交互

校园端入口为 `/app/assistant`，学生、教师和管理员沿用既有登录与导航。M4在M3会话、运行、预算接口上增加页面及一个只读SSE订阅接口；不修改模型、预算、运行调度或数据库结构。本阶段不启用正式校园数据外发，也不复用先前阶段的云调用额度。

## 页面与状态管理

| 文件 | 职责 |
| --- | --- |
| `frontend/src/views/AssistantChat.vue` | 两栏布局、会话列表及归档/删除、运行状态、费用提示、错误反馈和组件组合；窄屏会话横向排列 |
| `frontend/src/components/assistant/AssistantMessages.vue` | 历史消息、分段回复、可信来源、消息区滚动和加载更早记录 |
| `frontend/src/components/assistant/AssistantComposer.vue` | 输入、长度限制、发送/停止、输入法组合与键盘交互 |
| `frontend/src/composables/useAssistantChat.ts` | 当前会话/运行、历史分页、提交幂等、订阅生命周期、取消、有限重连和跨会话异步隔离 |
| `frontend/src/api/assistant.ts` | M3请求及Bearer fetch流，复用校园错误/身份约定，超时与AbortController清理 |
| `frontend/src/utils/assistant-events.ts` | 有界UTF-8/SSE帧解码、运行/回复校验及来源地址白名单；可独立测试 |
| `backend/app/assistant/stream.py` | 当前身份及本人范围的短事务读取、Redis订阅容量租约、状态/回复分段、断线释放 |
| `backend/app/api/assistant.py` | 新增订阅入口，使用原JWT解码契约；不持有贯穿响应生命周期的数据库依赖 |

正文使用Vue文本插值及保留换行显示，不将模型文本转换为HTML。引用只展示服务器返回且满足固定校园路径的metadata；用户和模型正文不能创建任意URL。消息、输入、JWT和SSE正文不写入新的浏览器持久存储。

切换会话或离开页面会终止原订阅，并以选择序号/订阅序号丢弃迟到结果；登录变化清空内存。关闭页面只断开读取，已提交运行仍由M3维护；“停止”按钮才调用原取消接口。取消在服务端确认前保持等待状态。

## 上下文与历史

页面按会话UUID读取最新一页消息，提供“加载更早消息”。前端提交仅包含本轮content和request_key，不上传可伪造的历史、角色或工具结果。多轮上下文继续由M3选择成功完整轮次，默认最多8轮及48KB，正文到期读取即时脱敏。

收到分段或新消息时，位于底部的用户自动跟随最新消息；向上查看历史时保留阅读位置并显示“回到最新消息”。加载更早记录保持当前视口，切换会话定位最新消息。

## 流式协议与边界

```text
POST /api/assistant/conversations/{conversation_id}/runs
  → M3运行ID（预算预留与幂等规则保持）
GET /api/assistant/runs/{run_id}/events?after=0
  → status（排队/生成状态）
  → delta（校验并持久化后的回复分段）
  → done（权威运行及回复）
```

M3模型适配器仍以完整回答结束图运行。**本阶段实时推送运行状态，并在最终身份、引用校验和SQL提交成功后分段发送回答；没有改成上游模型逐Token透传。** 页面分别显示“正在生成回答”和“正在接收已完成的回复”。思考、工具中间文本及未通过最终校验的回答不进入流通道。分段发送有独立的断线/重连生命周期，完成结果也能在页面刷新后从历史读取。

接口使用 `Authorization: Bearer <校园JWT>`，不使用将令牌写入URL的原生EventSource。`after`为已接收的分段序号，整数0–250；不接受身份、模型、Key或费用参数。订阅不调用模型、不创建运行、不重复计费。

| event | data | SSE id |
| --- | --- | --- |
| `status` | `{"run": M3公开RunDTO}` | 无 |
| `delta` | `{"run_id":"UUID","sequence":1,"text":"回复片段"}` | 等于sequence |
| `done` | `{"run": M3公开RunDTO,"message": 完整白名单消息或null}` | 无 |
| `error` | `{"reason":"unauthenticated/unavailable/not_found/expired/rate_limited"}` | 无，发送后关闭 |

实际reason为上述字符串之一，示例中的斜线仅表示可选值。回复每64个Unicode字符一段，最多250段；id从1递增，重连游标不改变原回复。运行期间每秒读取状态，仅变化时发送status，约10秒发送心跳注释。单次连接最长为排队期限+运行期限+60秒，硬上限1260秒，默认360秒。正常失败、取消、排队过期以done且message=null结束。

连接建立前身份/归属/期限/游标/容量失败返回常规HTTP错误；建立后返回受控error并结束。每次观察、每段正文及最终done前都重新读取MySQL当前身份、Redis撤销状态及正文期限，短事务在yield前释放锁及连接。跨用户包括管理员读取统一404。

Redis仅保存连接随机ID及到期时间，用户最多2、全局32个活跃订阅，15秒租约并续期，退出幂等释放；进程崩溃后自动过期。Redis或MySQL不可用时拒绝继续输出。响应包含 `Cache-Control: private, no-store, no-transform`、`X-Accel-Buffering: no` 和nosniff；既有Nginx `/api/` 已关闭proxy buffering，心跳维持读超时。

## 异常与恢复

- 提交响应超时可能发生在M3已入队之后，页面保留原文本及request_key，提供“确认原提交结果”；不自动生成新键重新发起付费运行。
- 流被截断、空闲超时或暂时服务异常时最多自动重新订阅两次，之后显示手动重连按钮。重连清空未完成的本地片段，从原运行重新读取，done以权威消息替换，避免重复拼接；不重新提交问题。
- 身份失效清除与该请求匹配的原登录状态并交给既有登录流程。HTTP与SSE统一处理404/410：先终止订阅及在途历史、递增选择序号，再清除不可访问的消息或脱敏到期正文/引用、停用输入；迟到响应不能恢复正文。取消恰好返回成功时只读重订阅原运行，补齐权威回复。
- 两个M3开关默认false。预算策略关闭时页面提示未启用、禁止发送，历史管理仍依赖已迁移的M3服务；后端尚未部署或表未迁移时显示受控不可用提示，不提供虚构回答。

## 验证与发布

2026-10-30完成以下验收，均以本步源码快照为准，不包含工作区原有预算/阶段记录草稿：

| 检查 | 结果与边界 |
| --- | --- |
| 后端完整回归 | 独立真实MySQL/Redis/FAISS/MCP HTTP/LangGraph环境，**664项通过、0跳过**，185.64秒；5项第三方弃用警告 |
| 前端类型与生产构建 | `npm run type-check`、`npm run build`及最终生产镜像构建通过；保留既有主包大于500KB提示，助手页面按路由懒加载 |
| 纯流协议 | Node内建测试**6项通过、0跳过**：UTF-8/CRLF跨块、事件边界、运行/金额/终态校验、引用白名单、受控错误 |
| 生产页面浏览器 | 现有Playwright/Edge对最终镜像导出的dist执行**20项合成HTTP/SSE场景全部通过**，无外部API或云访问 |
| 基础校园兼容性 | 后端基础镜像无LangGraph/FastMCP SDK时，两种入口和SSE模块/路由导入通过；基础与完整测试镜像`pip check`通过 |
| 只读审查与配置 | 审查发现普通HTTP404/410清理缺口；新增测试先在旧产物失败，再修复并通过全场景。五份原真实配置SHA256保持不变，本步未修改真实配置、应用迁移或部署正式服务 |

浏览器场景覆盖中文分段、多轮追问、历史分页、断流只读重连、提交超时保留原幂等键、停止/成功竞态、迟到历史、HTTP提交/分页/管理/取消的404/410、SSE到期/删除、会话切换、退出/撤销、滚动阅读保护、XSS文本、默认关闭及390px移动端。正文和工具自动化仍使用合成替身；这些结果不代表已验证真实校园数据外发或云模型首Token延迟。

复现命令（以下`docker`、`node`使用已安装的对应程序，依赖/缓存/产物仍放F盘）：

```powershell
# frontend目录；Node需支持strip-types。本阶段不新增npm依赖。
npm run type-check
npm run build
node --experimental-strip-types --test tests/assistant-events.test.mjs

# 项目根目录；标准方式独立构建测试镜像并启动临时服务
docker compose -p my-campus-ai-m4-test -f compose.assistant-test.yaml run --build --rm tests python -B -m pytest -q -p no:cacheprovider tests
docker compose -p my-campus-ai-m4-test -f compose.assistant-test.yaml down

# 将最终生产镜像的/usr/share/nginx/html导出到F盘后，使用已有Playwright/Edge。
node scripts/verify_assistant_ui.mjs --dist F:/my-campus-dev/temp/m4-ui/dist --output F:/my-campus-dev/temp/m4-ui/results-final --playwright C:/Users/Stephen/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright --browser "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --port 5184
```

本次后端复用已固定版本且依赖检查通过的`my-campus-ai-m2-test-tests:latest`测试镜像，以F盘暂存快照的`app/tests/migrations`只读覆盖；实际全量命令为：

```powershell
docker compose -p my-campus-ai-m4-test -f F:/my-campus-dev/temp/step7-m4-verification/compose.assistant-test.yaml -f F:/my-campus-dev/temp/compose.m4-verification.json run --rm --no-deps tests python -B -m pytest -q -p no:cacheprovider tests
```

浏览器脚本仅监听`127.0.0.1:5184`，拦截所有外部网络，退出时关闭浏览器/计时器/套接字/HTTP服务；可用`--only http-expired,cancel-success`定向复测。结果与截图位于`F:/my-campus-dev/temp/m4-ui/results-final/`；快照保留在`F:/my-campus-dev/temp/step7-m4-verification/`，不将验收产物提交到源码仓库。

后端继续用 `compose.assistant-test.yaml` 的独立MySQL/Redis/检查点库执行全量测试；新测试包括真实HTTP提前到达状态、断开释放、UTF-8/游标、跨用户/撤销、容量、到期及数据库失败。源码快照以Git暂存内容为准，保留工作区已有的M3预算/阶段记录草稿，防止把其回退混入本步。

M4无需新迁移。正式M3仍未应用0006，部署页面及新API前需按[M3部署说明](assistant-m3.md#配置与部署)完成备份、恢复验证和迁移。两个外发开关继续关闭；正式账号、数据范围、配额与发布窗口仍需人工确认。

回滚可单独回退页面、导航和SSE接口，保留M3表及运行/财务记录。先关闭新订阅或停止API，Redis连接租约自动释放；不要回放付费请求或降级删除会话表。建议下一阶段M5安排集成灰度及正式发布验证，待用户确认范围后再执行。
