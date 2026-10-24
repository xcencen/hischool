# 第六步：学生手册导入与知识检索

本步在前五步基础上增加“本地资料 → 按章节切片 → 百炼文本嵌入 → FAISS 检索 → 原文与页码核对”的最小闭环。继续使用 Vue 3.5、增量 TypeScript 5.9、Element Plus、Python 3.11、FastAPI、异步 SQLAlchemy、MySQL、Redis/RQ 和 Docker Compose。

当前用户选择稍后配置百炼 Key，因此先交付代码、资料解析和离线验证。**真实百炼嵌入调用及真实语义检索尚未验收**，不能以替身向量的测试结果代替。缺少 Key 或服务未就绪时明确显示待配置或待建索引，不切换模型、不生成假向量。

## 范围与文件关系

本步提供校园端 `/app/knowledge`，展示已导入资料、处理状态、相关原文片段、章节和页码，以及带鉴权的原件查看。资料导入、停用和索引操作由运维 CLI 执行。全功能知识库后台、通用 OCR、DeepSeek 生成回答、MCP 及 LangGraph 对话循环仍留待后续阶段；不自动编造 FAQ、校规或办事指南。

| 文件或模块 | 职责和调用关系 |
| --- | --- |
| `backend/app/knowledge/documents.py` | PDF/Markdown/TXT 解析、断行合并、章节/条款切分和页码保留，不执行资料中的指令 |
| `backend/app/models/knowledge.py`、`backend/migrations/versions/0005_knowledge.py` | MySQL 文档、版本、页、片段与向量、索引记录及有效索引指针 |
| `backend/app/knowledge/settings.py`、`embeddings.py` | 只读进程环境，独立加载百炼嵌入设置；固定模型与维度，校验服务返回值 |
| `backend/app/knowledge/vector_index.py` | 向量归一化、FAISS CPU 内积检索、原子文件写入与 SHA256 校验 |
| `backend/app/services/knowledge_service.py` | 幂等导入、版本切换、向量保存、索引重建、停用过滤及来源读取 |
| `backend/app/knowledge/cli.py`、`tasks.py` | 运维命令与 Redis/RQ 入库任务，任务参数只含版本和任务 ID，不含 Key |
| `backend/app/api/knowledge.py` | 登录鉴权后的状态、资料列表、检索及原件接口 |
| `frontend/src/api/knowledge.ts`、`views/KnowledgeSearch.vue` | 复用校园鉴权通道，展示原文和引用，使用 Bearer 获取来源文件 |

MySQL 是持久事实来源，FAISS 文件是可重建的检索产物。`0005_knowledge` 新增 `knowledge_documents`、`knowledge_versions`、`knowledge_pages`、`knowledge_chunks`、`knowledge_indexes`、`knowledge_state` 六张表。`KnowledgeState` 是 `id=1` 的非自增单例，种子显式初始化；应用导入不自动建表。

## 页序、章节与附件

片段按章节和条款分段，目标上限约 700 个字符、重叠约 100 个字符，不跨 PDF 页。片段 offset 指向标准化后的该页文本。表格优先提取列与行关系，并在行内容中保留列名；无法可靠识别时保留文本并提示人工核对。

`page_number` 是从 1 开始的 PDF 实际页序，用于打开 `#page=`；`page_label` 是识别到的印刷页码，无法可靠识别时为空。不能把两者混用或假定全书固定偏移。本次手册的 PDF 第 7 页对应印刷页 1，第 9 页对应印刷页 3；其中还有目录、分隔页和空白页。

扫描页及图片附件仅标记待识别，不执行 OCR，不把页脚当正文。实际手册 PDF 第 27、28 页为待识别图片附件，第 71、73 页含图片告警；这些局限会保留在版本 warnings 中。Markdown 图片引用只作为资料数据保留，不下载或执行。上传内容不能改变用户身份、检索权限或后续工具权限。

## 本地配置与 F 盘持久化

真实配置保存在 Git 仓库外的 `F:/my-campus-dev/config/knowledge.env`。可参考 `backend/knowledge.env.example`；Key 不发在聊天中、不写进命令行参数或提交记录。文件字段如下，空白处由用户在本地填写：

```dotenv
CAMPUS_EMBED_API_KEY=
# 填百炼北京工作空间控制台提供的 compatible-mode/v1 基址，不带 /embeddings。
CAMPUS_EMBED_BASE_URL=
CAMPUS_EMBED_MODEL_ID=text-embedding-v4
CAMPUS_EMBED_DIM=1024
CAMPUS_KB_MIN_SCORE=0.3
```

模型固定为 `text-embedding-v4`、1024 维；模型、维度和提供方配置须与已有向量一致。基址使用校验允许的北京 HTTPS 地址，不能填写占位符。`CAMPUS_KB_MIN_SCORE` 是相关片段筛选阈值，相似度用于排序，不能当作答案置信度。嵌入协议与当前限制见[百炼文本嵌入官方文档](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)。

Compose 的后端公共配置使用可选 `env_file`，默认读取上述 F 盘文件；文件不存在时不阻止前五步服务启动。必要时可在本地 `.env.compose` 设置 `CAMPUS_KNOWLEDGE_ENV_FILE` 指向另一个本地配置文件。

API、worker 和初始化服务共享以下绑定目录，实际宿主根目录由 `CAMPUS_DATA_ROOT` 控制：

| 默认宿主目录 | 容器目录 | 内容 |
| --- | --- | --- |
| `F:/my-campus-dev/data/knowledge` | `/data/knowledge` | 按内容 SHA256 命名保存的原始资料 |
| `F:/my-campus-dev/data/faiss` | `/data/faiss` | 版本化 FAISS 索引及临时构建文件 |

Compose 显式设置容器内 `CAMPUS_KB_SOURCE_DIR=/data/knowledge`、`CAMPUS_KB_INDEX_DIR=/data/faiss`，不要把 Windows 路径当成容器路径。直接在 Windows 运行 CLI 时，默认使用 F 盘对应目录，同时仍需显式提供校园数据库、Redis、JWT 等进程配置；CLI 不暗中读取旧 `backend/.env`。

配置文件变更后应重新创建服务以重新注入环境；单独 `docker compose restart` 不会更新已创建容器的环境变量：

```powershell
docker compose --env-file .env.compose up -d --force-recreate api worker frontend
```

新建前端容器也会重新解析 API 代理目标。Docker 不在 PATH 时，将命令中的 `docker` 替换为 `F:/my-campus-dev/docker/app/resources/bin/docker.exe`。

## 资料导入与入库 CLI

命令入口是 `python -m app.knowledge.cli`，需要使用已迁移并初始化的 `APP_MODE=campus` 环境。文件只复制到本地存储，不修改用户原件。以下示例先把已提供的手册复制到容器临时目录，避免在文档中硬编码个人微信文件目录：

```powershell
$handbookSource = Read-Host '输入学生手册 PDF 的本地绝对路径'
docker compose --env-file .env.compose cp $handbookSource api:/tmp/student-handbook.pdf
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli import /tmp/student-handbook.pdf --code student-handbook --title 学生手册 --category regulations
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli inspect
```

`import` 返回 `document_id`、`version_id`、资料版本号、状态、页数、片段数和 warnings。无 Key 时先保留 `parsed` 版本；不要添加 `--enqueue`。同一资料编码和相同源文件 SHA256 重复导入会返回既有版本，不重复插入页与片段；内容改变才创建新版本。资料分类为 `faq/regulations/guide`，仅分类已有真实内容，不自动生成新规定。

| 子命令 | 用途 |
| --- | --- |
| `import PATH --code CODE [--title TITLE] [--category regulations] [--enqueue]` | 解析原件并持久化新版本；可选立即排队，排队需要真实配置 |
| `enqueue VERSION_ID` | 把指定版本交给 `knowledge` 队列处理，常规入库推荐使用 |
| `build VERSION_ID` | 前台执行该版本嵌入及建索引，供运维调试；避免与同版本队列任务并行运行 |
| `rebuild` | 使用 MySQL 已保存且配置一致的向量重建索引，不重新解析或重复请求文档嵌入 |
| `set-active DOCUMENT_ID 0` | 停用资料，检索与原件访问立即按数据库状态过滤 |
| `set-active DOCUMENT_ID 1` | 重新启用资料；不会补齐缺失向量或自动重建文件，应随后执行 `rebuild` |
| `inspect` | 查看索引状态及各资料版本的状态、任务 ID、错误、页数与片段数 |

本次已经解析的版本无需重新导入。用户稍后配置 Key、重新创建服务后，使用 **本次实际 `version_id`** 排队；不要假定它等于资料 ID、版本号或某个固定数字：

```powershell
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli inspect
$knowledgeVersionId = [int](Read-Host '输入本次 import 或 inspect 输出中的 version_id')
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli enqueue $knowledgeVersionId
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli inspect
```

运维时可按需使用以下命令；停止资料是可恢复操作，不删除历史页、片段或向量：

```powershell
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli build $knowledgeVersionId
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli rebuild
$knowledgeDocumentId = [int](Read-Host '输入要停用或启用的 document_id')
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli set-active $knowledgeDocumentId 0
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli set-active $knowledgeDocumentId 1
docker compose --env-file .env.compose exec -T api python -m app.knowledge.cli rebuild
```

版本处理状态依次可能为 `parsed/queued/processing/embedded/indexed`，失败为 `failed`。重复排队会复用仍在队列或运行中的任务；失败后修复配置再用原 `version_id` 重试，完整且配置一致的已保存向量可以复用。RQ 任务只携带版本和任务标识，Key 由 worker 自己的环境读取。

## 索引与失败恢复

向量存入 MySQL 并记录模型、维度及提供方配置摘要；FAISS 使用 `IndexIDMap2(IndexFlatIP)`，对向量做 L2 归一化后使用内积实现余弦相似度。参见 [FAISS 距离说明](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances)。

构建会串行锁定知识库状态，先完整写入临时文件、刷新磁盘，再原子替换版本化索引文件；成功后才在同一数据库事务中切换资料有效版本和有效索引指针。嵌入或重建失败保留上一有效索引，新资料的失败版本不会替换可用资料。停用过滤依赖 MySQL，不能仅靠索引中是否仍存在向量来判断权限。

索引 SHA256 保存在 MySQL，读取时先校验文件哈希，再交给 FAISS 反序列化，并核对索引类型、维度和片段 ID；原件读取也验证 SHA256。文件缺失、被修改或配置不兼容时返回明确故障，不自动读取任意外部索引。保存向量完整时使用 `rebuild` 恢复，参见 [FAISS 索引持久化说明](https://github.com/facebookresearch/faiss/wiki/Index-IO%2C-cloning-and-hyper-parameter-tuning)。

## HTTP 接口与来源查看

所有接口都要求有效校园 Bearer 登录凭证。除原件文件响应外，JSON 继续使用 `code/message/data`，错误使用对应 HTTP 状态。

| 接口 | 行为 |
| --- | --- |
| `GET /api/knowledge/status` | 是否配置、是否有兼容有效索引、资料/片段数量、模型、维度与状态说明，不返回 Key 或服务器文件路径 |
| `GET /api/knowledge/documents` | 启用资料的版本、解析状态、页数、片段数和识别告警 |
| `POST /api/knowledge/search` | 请求 `query`、`top_k`；返回原文片段、相似度、章节、资料版本和两种页码 |
| `GET /api/knowledge/documents/{document_id}/source?version=VERSION_NUMBER` | 获取指定资料版本的原件；这里传资料版本号，区别于入库任务的 `version_id` |

搜索 API 的 `query` 长度为 1～1000 字符，`top_k` 为 1～10，默认 5。没有足够相关片段时明确提示资料不足，不编造回答。配置、索引或嵌入服务不可用时返回 503；资料不存在或已停用时，来源访问返回 404。

来源接口不是公开静态目录，也不接受把 JWT 放在 URL 中。页面先用 `fetch` 的 `Authorization: Bearer ...` 获取文件 Blob，再打开带 `#page=PDF实际页序` 的本地 Blob URL。文件响应设置 `private, no-store` 和 `nosniff`；登录身份变化时不继续打开旧请求的来源。已授权下载到客户端的内容无法通过后续停用收回，停用会阻止后续服务端检索与来源读取。

## 验证、迁移与回滚

前端继续 `npm run type-check`、`npm run build`。新增运行依赖独立放在 `requirements-knowledge.txt`，包括 PyMuPDF、NumPy、FAISS CPU 与 HTTP 客户端，不把并行 AI 依赖混入本步。

自动化中百炼网络由替身替代，用于验证解析/页码、向量格式、真实 FAISS 读写检索、索引完整性、版本切换、停用过滤和错误恢复；真实 MySQL/Redis 验收使用独立 `my_campus_test`。实际通过数量、正式迁移和本次导入版本记录在 [实施进度](progress.md) 补充；未运行的真实百炼语义检索不能标记通过。

本次隔离快照回归为 **305 项通过、0 跳过**，包括原 161 项与新增 144 项。正式迁移已应用，`alembic check` 无差异；手册两次导入均返回文档 ID 1、版本 ID 1、第 1 版、268 页及 1289 片段。该版本停留在 `parsed`，生产向量和索引均为零。原件 Bearer 下载哈希与用户原件一致，无凭证请求返回 401；真实界面显示待配置并禁止检索。浏览器内独立替身仅验证结果、页码及纯文本渲染，不代表真实召回成功。

`scripts/smoke_compose.py --exercise-restarts` 已验证依赖故障与恢复、实际 worker 及重启后原业务和六张知识表的数据指纹一致；重启后再次核对私有原件哈希及 PDF 页码映射通过。页面和 390px 移动端冒烟通过，无未捕获浏览器错误。

工作目录仍有用户要求单独保留的并行 AI 配置、模型测试等改动。本步验收使用 `b8d0e4a` 基线加本步文件的 `.workbuddy/step6-verification` 快照，保留原 README 未提交内容、旧配置、知识原件和其他 AI 文件。

迁移前数据库备份及其恢复验证保存在 F 盘。首次隔离 MySQL 验收发现单例 `id=1` 的 CHECK 不能引用 AUTO_INCREMENT，因此将 `KnowledgeState.id` 设计为非自增，并修正当时尚未成功应用的 `0005_knowledge`。该次清理仅限已确认空的测试库新表；问题出现时主库尚未执行，历史迁移和原业务表未回退。后续实际迁移结果以实施进度记录为准。

普通回滚优先反向提交代码，保留 MySQL、知识原件及索引卷；不要自动执行删表降级或清库。MySQL DDL 不保证整批回滚，迁移失败应核对实际表结构和 Alembic 版本，再采用新增修复迁移或经过验证的备份恢复。索引产物可由 MySQL 保存的向量重建。原始 PDF、真实 Key、上传原件、索引文件和运行缓存均不得提交 Git。

当前剩余验收是：用户在 F 盘补齐真实北京地域嵌入配置，重建服务环境，排队本次版本，观察其进入 `indexed`，再用学生手册真实问题核对语义召回、页码与原文。完成这些检查后才衔接生成式问答、MCP 与 LangGraph；这些后续能力不属于本步已验收范围。
