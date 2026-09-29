# 完整社区预测系统

面向社区人口与公共服务设施需求分析的单页面工作台。系统支持社区数据录入和 Excel 导入、人口预测、设施需求预测、图表与 Word/Excel 报告、社区管理、工程管理，以及独立运行或嵌入既有业务系统。

## 技术栈

- 前端：React 18、TypeScript、Vite
- 后端：Python、FastAPI、SQLAlchemy、Pydantic
- 数据库：SQLite（默认），可通过环境变量切换数据库连接
- 文档与表格：python-docx、openpyxl、Pillow

## 目录结构

```text
backend/       FastAPI 接口、预测服务、数据模型和测试
frontend/      React 单页面应用及可嵌入组件
docs/          单页面与大系统嵌入说明
scripts/       开发启动、测试和文档生成脚本
测试用数据/   不含姓名等身份字段的自动化测试夹具
交付文档/     大系统嵌入接入说明
```

原始社区调研表、运行数据库、工程数据、日志和构建产物不进入源码仓库。

## 下载后快速启动（推荐）

适用于从 GitHub 下载或克隆源码的 Windows 用户：

1. 安装 **Python 3.11+** 和 **Node.js 20+**，安装时允许加入 `PATH`。
2. 下载仓库 ZIP 并完整解压，或执行 `git clone`。不要只复制其中几个文件。
3. 双击根目录的 `一键启动.bat`。
4. 首次启动会自动创建 `.venv`、安装 Python 与前端依赖；完成后浏览器自动打开 `http://127.0.0.1:5173`。
5. 使用期间保持启动窗口开启；关闭该窗口即可同时停止前端和后端服务。

首次安装依赖需要联网，耗时取决于网络。若启动失败，请先关闭占用 `5173` 或 `8000` 端口的程序，再重新双击启动脚本。项目路径可包含中文和空格，但应完整解压后再运行。

## 开发环境

- Windows 10/11
- Python 3.11 或更高版本
- Node.js 20 或更高版本
- pnpm（推荐通过 Corepack 启用）

## 初始化

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
pip install -r backend\requirements-dev.txt

corepack enable
pnpm --dir frontend install --frozen-lockfile
```

如需自定义配置，复制示例文件后再修改，不要提交真实密码或令牌：

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env
```

## 命令行启动开发环境

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
```

- 前端：http://127.0.0.1:5173
- 后端接口文档：http://127.0.0.1:8000/docs

停止服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop-dev.ps1
```

普通用户建议直接双击根目录的 `一键启动.bat`。使用期间保持启动窗口开启，关闭窗口即可停止全部服务。

## 检查与构建

```powershell
.\.venv\Scripts\python.exe -m pytest
pnpm --dir frontend run lint
pnpm --dir frontend run build
pnpm --dir frontend run build:embed
```

单页面与嵌入说明见 `docs/SINGLE_WORKSPACE_GUIDE.md` 和 `交付文档/完整社区预测模块嵌入大系统接入说明.docx`。

## 融合开发建议

从 `main` 创建独立融合分支：

```powershell
git switch -c integration/main-system
```

完成一个可验证阶段后提交 Pull Request。不要提交 `.env`、SQLite 数据库、`runtime`、原始调研表、居民明细、`node_modules` 或构建目录。

## 数据安全

本仓库仅包含程序源码、开发说明和匿名测试夹具。测试夹具中的人口记录只保留序号、性别、出生年份和年龄等预测所需字段，不包含姓名、证件号码、电话号码或住址。社区原始调研数据和其他居民明细必须在获得授权并完成脱敏后，通过受控渠道交付，不应提交到公开仓库。
