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
.\.venv\Scripts\python.exe -m pytest checks -q
```

## 自动化校验脚本

`checks/` 下的三个脚本用于开发时检查后端行为，修改相关功能后可运行。保留 `test_*.py` 文件名，便于 pytest 自动发现用例。

- `test_identity.py`：检查浏览器身份与指纹生成、保存和加载，校验系统、GPU、屏幕、语言和时区的一致性；验证直连、手动代理、订阅代理的启动参数，以及旧版 Tor 配置的兼容处理。
- `test_branding.py`：用临时模拟引擎资源包检查 Cacer 名称和图标替换，确认原始资源已备份、无关内容不变、重复执行不重复改写；模拟文件占用，验证替换失败时原包仍完整。
- `test_operations.py`：检查数据导入的路径校验、损坏包与重复目标拦截、失败回滚和备份保留；验证身份创建、重建、订阅导入及扩展安装时的锁范围，避免慢操作长期占锁或覆盖并发修改。

从仓库根目录运行全部校验：

```powershell
.\.venv\Scripts\python.exe -m pytest checks -q
```

只检查某个模块时，将 `checks` 换成对应脚本路径，例如 `checks/test_branding.py`。脚本使用 pytest 临时目录存放测试数据，不读取项目 `data/` 中的个人浏览器配置，也不启动真实浏览器。启动参数校验会调用已安装引擎的初始化逻辑，可能更新其名称、图标、界面样式及密码管理配置。身份生成用例依赖 fpgen 模型缓存，首次运行可能需要联网下载模型。

## 本地数据与仓库边界

- `core/`：Python 后端及品牌资源。
- `manager/`：桌面管理器源代码、图标与依赖锁文件。
- `checks/`：自动化校验脚本（pytest）。
- `tools/`：通用引擎下载、指纹验证与打包工具。

浏览器环境、Cookie、登录凭据、代理订阅及运行记录默认保存在 `data/`；旧版 `profiles/` 也属于私人数据。这些目录、数据导出包、密钥、本机开发报告、会话记录、下载的运行时和构建缓存均由 `.gitignore` 排除。导出的浏览器数据可能含有完整登录状态，应自行妥善保管。

新仓库以清理后的源码快照作为独立初始提交。旧仓库历史保留在本地备份分支，不随新仓库上传。
