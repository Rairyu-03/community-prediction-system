# 完整社区预测系统

面向社区人口与公共服务设施需求分析的单页面工作台。系统支持社区数据录入和 Excel 导入、人口预测、设施需求预测、图表与 Word/Excel 报告、社区管理、工程管理，以及独立运行或嵌入既有业务系统。

## 技术栈

- 前端：React 18、TypeScript、Vite
- 后端：Python、FastAPI、SQLAlchemy、Pydantic
- 数据库：SQLite（默认），可通过环境变量切换数据库连接
- 文档与表格：python-docx、openpyxl、Pillow
- 桌面交付：PyInstaller 单文件 Windows 程序

## 目录结构

```text
backend/       FastAPI 接口、预测服务、数据模型和测试
frontend/      React 单页面应用及可嵌入组件
packaging/     Windows 打包配置和交付说明
scripts/       开发启动、测试、打包和文档生成脚本
交付文档/     大系统嵌入接入说明
```

原始社区调研表、运行数据库、工程数据、日志和构建产物不进入源码仓库。

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

## 启动开发环境

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
```

- 前端：http://127.0.0.1:5173
- 后端接口文档：http://127.0.0.1:8000/docs

停止服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop-dev.ps1
```

## 检查与构建

```powershell
.\.venv\Scripts\python.exe -m pytest
pnpm --dir frontend run lint
pnpm --dir frontend run build
pnpm --dir frontend run build:embed
```

Windows 单文件程序：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
```

详细打包说明见 `packaging/WINDOWS_README.txt`，单页面与嵌入说明见 `packaging/SINGLE_WORKSPACE_GUIDE.md` 和 `交付文档/完整社区预测模块嵌入大系统接入说明.docx`。

## 融合开发建议

从 `main` 创建独立融合分支：

```powershell
git switch -c integration/main-system
```

完成一个可验证阶段后提交 Pull Request。不要提交 `.env`、SQLite 数据库、`runtime`、原始调研表、居民明细、`node_modules`、构建目录或 EXE。

## 数据安全

本仓库仅包含程序源码与开发说明。社区原始调研数据和居民明细可能包含敏感信息，必须在获得授权并完成脱敏后，通过受控渠道交付，不应提交到公开仓库。
