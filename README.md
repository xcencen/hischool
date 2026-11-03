> 当前阶段：M6 上线准备已完成（2026-11-03），状态为“准备完成，保持关闭”。正式0006/0007迁移与灰度未执行，云调用0。交付与708项后端/32项浏览器等实际证据见 [M6记录](docs/assistant-m6.md)。
>
> 日常开发沿用 [基础设施](docs/infrastructure.md)；隔离验收使用 [M6无云入口](docs/assistant-m6-release.md#当前操作入口)；正式发布准备使用独立 `compose.release.yaml` 和发布准入清单。旧初始化SQL与开发自动seed不能用于正式发布。下方旧阶段说明均为历史参考。

> 当前阶段：M5.1–M5.5 开发与隔离验收已完成。最终后端 696 项及前端生产镜像 22 项浏览器用例通过；正式助手迁移与灰度尚未执行。交付见 [M5 总记录](docs/assistant-m5.md) 与 [发布手册](docs/assistant-m5-release.md)。下方旧阶段说明作为历史参考。

# my-campus

前六步已完成，包含学生手册真实百炼嵌入、FAISS 检索、来源引用，以及鉴权、限流、超时处理和安全日志。使用见 [知识检索](docs/knowledge.md)、[通知与活动](docs/community.md)、[课程说明](docs/courses.md)、[认证说明](docs/authentication.md)；部署见 [基础设施说明](docs/infrastructure.md)，验收见 [实施进度](docs/progress.md)。

下方保留原脚手架说明，涉及数据库、旧业务和旧启动脚本的步骤暂不适用于当前入口。

---

# hischool
当前的实验项目
