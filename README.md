# Cacer Browser

基于 Camoufox 的 Windows 浏览器环境管理器，使用 Python 管理独立浏览器配置，使用 Tauri 2、React 和 Vite 提供桌面界面。支持环境管理、直连与代理、扩展管理和数据导入导出。

## 开发运行

需要 Python 3.12+、Node.js、Rust，以及 Tauri Windows 构建工具链（MSVC C++ Build Tools 和 WebView2）。在仓库根目录执行 PowerShell 命令：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "camoufox[geoip]" playwright pysocks pytest
.\.venv\Scripts\python.exe -m camoufox fetch
cd manager
npm ci --include=dev
npm run tauri dev
```

浏览器引擎需单独下载。网络不通时可配置自己的代理，或使用 `tools/fetch_engine.py` 提供的镜像下载工具。

## 构建与启动

```powershell
cd manager
npm run tauri build
.\src-tauri\target\release\cacer-manager.exe
```

也可双击编译生成的 `cacer-manager.exe`，或安装 `manager/src-tauri/target/release/bundle/` 内的安装包。项目不依赖 VBS 启动脚本。

构建完整运行时资源时，先在仓库根目录运行 `tools/package_runtime.ps1`；所需环境变量及用法见脚本注释。

后端命令行可在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m core.cli --help
.\.venv\Scripts\python.exe -m pytest tests -q
```

## 本地数据与仓库边界

- `core/`：Python 后端及品牌资源。
- `manager/`：桌面管理器源代码、图标与依赖锁文件。
- `tests/`：自动化测试。
- `tools/`：通用引擎下载、指纹验证与打包工具。

浏览器环境、Cookie、登录凭据、代理订阅及运行记录默认保存在 `data/`；旧版 `profiles/` 也属于私人数据。这些目录、数据导出包、密钥、本机开发报告、会话记录、下载的运行时和构建缓存均由 `.gitignore` 排除。导出的浏览器数据可能含有完整登录状态，应自行妥善保管。

新仓库以清理后的源码快照作为独立初始提交。旧仓库历史保留在本地备份分支，不随新仓库上传。
