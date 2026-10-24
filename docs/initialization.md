# my-campus：第一步工程初始化

本文记录第一步的独立初始化页面和健康接口。当前完整账号入口与启动方式见 [认证说明](authentication.md)；按本文独立运行时，前端访问 `/status`，后端使用默认 `APP_MODE=bootstrap`，无需数据库、Redis、模型、MCP 或知识库。

## 环境和目录

- Node.js：符合 `frontend/package.json` 的 `engines`，本次使用 24.16.0。
- Python：**3.11**，本次使用 3.11.15；不能用其他 Python 版本的检查代替验收。
- 前端：Vue 3.5、Element Plus 2、Vite；新增入口使用 TypeScript 5.9。
- 后端：FastAPI 0.115.13、Uvicorn 0.35.0。
- 源码保留在 E 盘；按本地约定，运行环境、下载缓存和依赖统一放在 **`F:\my-campus-dev`**。

```text
frontend/src/main.ts                 新前端入口
frontend/src/bootstrap/              初始化页面、健康请求、样式
frontend/tsconfig.json               仅检查新增入口和 bootstrap 下的 TypeScript/Vue
backend/app/main.py                  无外部服务副作用的应用工厂
backend/app/bootstrap/               独立配置和健康路由
backend/tests/test_bootstrap.py      初始化验收测试
backend/requirements-bootstrap.txt   当前运行依赖
backend/requirements-dev.txt         当前运行及测试依赖
```

旧 `frontend/src/main.js`、`App.vue`、路由和业务页面，以及后端 API、模型、业务服务和 MCP 源码均保留。**旧 `requirements.txt`、`start-all.bat`、`start-backend.bat`、`start-mcp.bat` 和旧数据库初始化脚本不用于本阶段。** 不执行 `sql/backend.sql`。

## 安装（Windows PowerShell）

在仓库根目录操作。已有本地环境可直接跳到“启动”。以下步骤仅为首次建立环境；目标目录已有文件时先核对，不覆盖旧环境或真实配置。

把临时文件和缓存定向到 F 盘（只影响当前终端）：

```powershell
New-Item -ItemType Directory -Force -Path F:\my-campus-dev\temp,F:\my-campus-dev\cache\uv,F:\my-campus-dev\cache\npm | Out-Null
$env:TEMP = 'F:\my-campus-dev\temp'
$env:TMP = $env:TEMP
$env:UV_CACHE_DIR = 'F:\my-campus-dev\cache\uv'
$env:npm_config_cache = 'F:\my-campus-dev\cache\npm'
```

使用已安装的 `uv` 建立 Python 3.11 环境。`--no-bin --no-registry` 避免改动用户的全局 Python 注册与启动路径：

```powershell
uv python install 3.11 --install-dir F:\my-campus-dev\python --no-bin --no-registry
uv venv F:\my-campus-dev\venvs\backend --python F:\my-campus-dev\python\cpython-3.11-windows-x86_64-none\python.exe
uv pip install --python F:\my-campus-dev\venvs\backend\Scripts\python.exe -r backend/requirements-dev.txt
```

上面使用 uv 的 3.11 简短目录名；若本机下载目录不同，按实际路径调整。只运行服务时可安装 `requirements-bootstrap.txt`；测试需要 `requirements-dev.txt`。已保留的 `backend/.venv` 不使用、不覆盖。

前端依赖放到 F 盘，源码目录通过目录链接访问。仅在 `frontend/node_modules` **尚不存在**时执行以下建立链接步骤；已有依赖目录时先确认其内容，不能直接覆盖或删除：

```powershell
New-Item -ItemType Directory -Force -Path F:\my-campus-dev\frontend\node_modules | Out-Null
New-Item -ItemType Junction -Path frontend/node_modules -Target F:\my-campus-dev\frontend\node_modules
Set-Location frontend
npm install --no-audit --no-fund
```

本机已建好上述 F 盘环境；`frontend/node_modules` 以及 `backend/.venv-bootstrap` 为本地目录链接，均不提交 Git。

## 启动

第一个终端，从仓库根目录启动后端：

```powershell
Set-Location backend
& F:\my-campus-dev\venvs\backend\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

第二个终端，从仓库根目录启动前端：

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 <http://127.0.0.1:5173/status>。页面显示 `my-campus`、版本和后端连接结果，可点击“重新检查”。后端停止时显示未连接；每次检查最多等待 5 秒。

当前只开放根路径、`/api/health` 和 FastAPI 自带文档，不提供登录或其他旧业务接口。

## 配置和接口

后端**不自动加载 `.env`**，因此无需复制配置即可启动，原有 `backend/.env` 不会被读取。可选配置只读取进程环境变量：

| 配置 | 默认值 |
| --- | --- |
| `APP_NAME` | `my-campus` |
| `APP_VERSION` | `0.1.0` |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` |

前端健康检查校验 `my-campus` 的响应合同；正常使用时保留默认项目名。跨域开发地址改变时，使用逗号分隔的 `CORS_ORIGINS` 调整允许来源。

`frontend/.env.example` 提供 `VITE_API_BASE_URL` 示例。已有 `.env.development` 保留；可通过本地 `.env.local` 覆盖，修改后重启 Vite。开发时留空可使用 Vite `/api` 代理；生产构建留空使用同源 `/api`，部署时需配置反向代理，或在构建前设置可访问的后端地址。预览命令自身不提供生产 API 代理。

`GET http://127.0.0.1:8000/api/health` 返回 HTTP 200：

```json
{"code":200,"message":"ok","data":{"name":"my-campus","version":"0.1.0","status":"ok"}}
```

该接口只说明应用已运行，不检查未来的数据库或模型可用性。

## 检查

```powershell
# 仓库根目录
Set-Location backend
& F:\my-campus-dev\venvs\backend\Scripts\python.exe --version
& F:\my-campus-dev\venvs\backend\Scripts\python.exe -m pytest -q tests/test_bootstrap.py

Set-Location ../frontend
npm run type-check
npm run build
```

TypeScript 的 strict 检查仅覆盖新入口和初始化模块，原 JavaScript 页面逐步迁移，不代表旧业务已完成类型改造。后端测试覆盖健康返回、旧路由未挂载、配置和 CORS，以及禁止旧模块和网络连接的独立进程导入检查。

人工验收：前后端启动后确认连接正常；停止后端后重新检查确认离线；恢复后端后重新检查确认恢复。手机宽度下检查页面无横向溢出。本步不引入 Playwright 全量回归。

## 后续阶段和保护措施

后续按单独确认的步骤加入 MySQL、Redis、LangGraph、MCP、FAISS 和百炼北京地域 `deepseek-v4.1-flash`。`backend/.env.example` 中相关变量只是注释占位，本步不校验模型权限、不调用模型、不创建数据库或执行迁移，也不编排 Docker Compose。

真实 `.env`、依赖、上传、知识原件、索引和本地缓存由根目录 `.gitignore` 排除。知识原件与索引统一放在未跟踪的 `data/` 目录；不要另行加入真实密钥或原始资料。

初始化前已建立源码基线提交 `4d60d0c`。本地源码备份位于 `.workbuddy/tmp/my-campus-source-baseline-20261023.zip`，不含密钥、依赖和上传文件，也不上传远端。回滚本次初始化可反向提交初始化提交；不需要数据库回滚。原 README 的已有未提交修改单独保留。
