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

构建发布资源时，使用干净的 Python 虚拟环境安装 `requirements-runtime.txt`，再运行 `tools/package_runtime.ps1`。脚本需要 `CAMOUFOX_RUNTIME`、官方嵌入式 Python ZIP 和目标版本的 Release 下载地址；具体参数见脚本注释。它会保留浏览器核心，将字体和 Python 分别打包为 Release 附件。

后端命令行可在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m core.cli --help
.\.venv\Scripts\python.exe -m pytest checks -q
```

## GitHub 自动构建与版本发布

仓库的 `.github/workflows/release.yml` 使用 GitHub Actions 构建 Windows x64 安装包。推送 `v主版本.次版本.修订号` 标签时自动创建同名 Release，各版本独立保留；例如 `v0.1.0`、`v0.1.1`、`v0.2.0`。目前只接受正式版本标签。

在仓库根目录发布一个版本：

```powershell
git push origin main
git tag v0.1.0
git push origin v0.1.0
```

标签指向的提交就是发布源码，应在提交完成后再打标签。版本号会在构建环境中同步到 Tauri、npm 和 Cargo 配置，不需要手动修改多个文件。已发布的标签和安装包应保留；修复问题后使用新版本号发布。

打开仓库的 **Actions → Windows Release** 查看进度。流程在干净虚拟环境中安装固定版本依赖，下载 Camoufox 配套引擎和官方嵌入式 Python，分别生成浏览器核心、字体包和 Python 运行时包。后端校验、TypeScript 检查、运行时安装校验，以及 Windows/macOS/Linux 指纹的真实浏览器启动检查通过后，再构建 NSIS 安装包。构建或校验失败时不会发布 Release。

成功后，其他人进入仓库的 **Releases**，选择版本，在 **Assets** 下载：

- `Cacer_版本_windows_x64-setup.exe`：Windows 64 位安装包，包含管理器、后端代码和浏览器核心，不包含字体和 Python。
- `fonts.zip`：配套完整字体集，首次启动浏览器时从本版本 Release 下载，也可在设置中提前下载。
- `python-runtime.zip`：精简的专用嵌入式 Python 和配套依赖，由用户选择快捷安装。
- `runtime-manifest.json`：运行时版本、下载大小和 SHA256；安装包内含相同清单，下载时使用内置摘要验证。
- `SHA256SUMS.txt`：全部下载附件的 SHA256 校验值。
- `runtime-dependencies.txt`：该版本完整 Python 依赖锁定清单。

首次打开管理器无需 Python。运行环境未就绪时，用户可选择「快捷安装 Python 与依赖」，或展开「手动安装 Python / 使用已有 Python」，复制 PowerShell 命令创建独立虚拟环境，再指定其 `python.exe`。快捷安装不修改系统 PATH。安装界面提供进度、取消、重试及下载代理设置（HTTP 或 SOCKS5）。

字体先以完整配套字体集下载，暂不按系统拆分，避免缺失跨系统指纹需要的字形。文件校验、解压完成后才启用，所有环境共享缓存；安装成功后删除下载 ZIP。管理器升级时，清单摘要相同的运行时可复用，首次使用全部功能的下载总量不会因分包自动减少。

运行时缓存位于应用数据目录旁的 `runtime-cache`，与保存环境、登录信息的 `data` 目录分开，导出用户数据不包含运行时。开发构建没有发布清单时继续使用本地 `.venv` 和已下载引擎。手动 Actions 构建的附件可用于本地校验；其下载地址只有对应版本的 Release 发布后才可访问。

WebView2 缺失时安装器会联网安装，无需 Node.js 或 Rust。代理订阅功能仍需配置本机可用的 mihomo/Clash 内核。安装包未配置 Windows 代码签名。

只想验证构建时，可在 **Actions → Windows Release → Run workflow** 选择分支手动运行。产物保存在该次运行的 **Artifacts**，保留 14 天；手动运行不会创建 Release。

工作流使用 GitHub 自动提供的 `GITHUB_TOKEN`，无需添加个人令牌。如果组织禁用了 Actions 或禁止工作流写入仓库，需要由仓库管理员开放相应权限。仓库为私有时，Release 下载也需要仓库访问权限；面向所有人下载需要公开仓库。

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
