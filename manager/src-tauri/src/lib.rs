use serde_json::Value;
use std::io::Read;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// Absolute project root (the Rust crate lives in <root>/manager/src-tauri).
/// Only the CLI is required here: the interpreter may be the machine-wide
/// Python instead of a bundled runtime.
fn has_runtime_layout(root: &PathBuf) -> bool {
    root.join("core").join("cli.py").is_file()
        || root.join("resources").join("core").join("cli.py").is_file()
}

fn project_root() -> PathBuf {
    // Do not assume the process current directory. A desktop app can be
    // launched from a shortcut, the Start menu, or a different shell folder.
    let mut candidates = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        candidates.extend(exe.ancestors().map(PathBuf::from));
    }
    if let Ok(dir) = std::env::current_dir() {
        candidates.extend(dir.ancestors().map(PathBuf::from));
    }
    candidates.into_iter().find(has_runtime_layout)
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

fn bundled_python(root: &PathBuf) -> Option<PathBuf> {
    [
        root.join("runtime").join("python").join("python.exe"),
        root.join("resources").join("runtime").join("python").join("python.exe"),
        root.join(".venv").join("Scripts").join("python.exe"),
    ].into_iter().find(|path| path.is_file())
}

/// Resolve an interpreter through the `py` launcher or `python` on PATH and
/// keep the path it reports, so callers always get a real executable even
/// when those names are shims (e.g. the Microsoft Store alias).
fn probe_python(program: &str, version_flag: Option<&str>) -> Option<PathBuf> {
    let mut cmd = silent_command(program);
    if let Some(flag) = version_flag {
        cmd.arg(flag);
    }
    let output = cmd
        .args(["-c", "import sys;print(sys.executable)"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let path = PathBuf::from(String::from_utf8_lossy(&output.stdout).trim());
    path.is_file().then_some(path)
}

fn system_python() -> Option<PathBuf> {
    probe_python("py", Some("-3")).or_else(|| probe_python("python", None))
}

/// A bundled runtime or project venv wins because it can carry camoufox;
/// otherwise fall back to the machine-wide Python. The resolved interpreter is
/// cached: without it every 3s `list` poll also re-probed `py -3`/`python`.
fn python_path(root: &PathBuf) -> PathBuf {
    static CACHE: std::sync::OnceLock<PathBuf> = std::sync::OnceLock::new();
    if let Some(path) = CACHE.get() {
        return path.clone();
    }
    let resolved = bundled_python(root)
        .or_else(system_python)
        .unwrap_or_else(|| PathBuf::from("python"));
    // Do not cache the bare fallback, so installing Python later is picked up
    // by the environment check without restarting the GUI.
    if resolved.is_file() {
        let _ = CACHE.set(resolved.clone());
    }
    resolved
}

fn cli_path(root: &PathBuf) -> PathBuf {
    let bundled = root.join("resources").join("core").join("cli.py");
    if bundled.is_file() { bundled } else { root.join("core").join("cli.py") }
}

/// Run a probe process with a hard timeout so a hanging interpreter can never
/// stall the UI. Returns `None` on spawn failure or timeout.
fn run_with_timeout(
    program: &PathBuf,
    args: &[&str],
    cwd: &PathBuf,
    timeout: std::time::Duration,
) -> Option<bool> {
    use std::process::Stdio;
    let mut child = silent_command(program)
        .args(args)
        .current_dir(cwd)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    let started = std::time::Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Some(status.success()),
            Ok(None) if started.elapsed() < timeout => {
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    }
}

fn find_camoufox_exe(dir: &PathBuf, depth: usize) -> Option<PathBuf> {
    let exe = dir.join("camoufox.exe");
    if exe.is_file() {
        return Some(exe);
    }
    if depth == 0 {
        return None;
    }
    for entry in std::fs::read_dir(dir).ok()?.flatten() {
        if entry.file_type().map(|kind| kind.is_dir()).unwrap_or(false) {
            if let Some(found) = find_camoufox_exe(&entry.path(), depth - 1) {
                return Some(found);
            }
        }
    }
    None
}

/// Locate an installed engine on disk. Never ask camoufox for its path:
/// `pkgman.get_path` resolves the build and may hit the network.
fn find_engine(root: &PathBuf) -> Option<PathBuf> {
    let mut dirs = vec![
        root.join("runtime").join("camoufox"),
        root.join("resources").join("runtime").join("camoufox"),
    ];
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        dirs.push(PathBuf::from(local).join("camoufox"));
    }
    if let Ok(custom) = std::env::var("CAMOUFOX_INSTALL_DIR") {
        dirs.push(PathBuf::from(custom));
    }
    dirs.into_iter().find_map(|dir| find_camoufox_exe(&dir, 6))
}

fn code_root(root: &PathBuf) -> PathBuf {
    cli_path(root).parent().and_then(|p| p.parent())
        .map(PathBuf::from).unwrap_or_else(|| root.clone())
}

/// User-owned data lives in one portable `data` folder so the whole
/// directory can be copied to migrate to another machine. Development runs
/// keep it under the repo; packaged builds use LocalAppData.
fn storage_root(root: &PathBuf) -> PathBuf {
    let base = if has_runtime_layout(root) && root.join("core").join("cli.py").is_file() {
        root.clone()
    } else if let Ok(local_app_data) = std::env::var("LOCALAPPDATA") {
        PathBuf::from(local_app_data).join("ShadowFox")
    } else {
        root.clone()
    };
    let data = base.join("data");
    let _ = std::fs::create_dir_all(&data);
    data
}

fn packs_dir(root: &PathBuf) -> PathBuf {
    let dir = storage_root(root).join("packs");
    let _ = std::fs::create_dir_all(&dir);
    dir
}

/// A Command that never opens a console window on Windows. Without this,
/// every python/reg subprocess flashes a black box over the GUI.
fn silent_command(program: impl AsRef<std::ffi::OsStr>) -> Command {
    #[allow(unused_mut)]
    let mut cmd = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

/// A hung CLI must not pin a blocking-pool thread forever: async commands make
/// repeated operations pile up otherwise. Budgets are per command family.
fn cli_timeout(args: &[&str]) -> Duration {
    match args.first().copied().unwrap_or("") {
        "list" | "status" | "history" | "proxy-sources" | "proxy-nodes"
        | "proxy-discover" | "ext-list" => Duration::from_secs(30),
        "launch" | "stop" | "cookies" => Duration::from_secs(120),
        "create" | "clone" | "rebuild" | "ext-install" | "ext-import"
        | "proxy-import" => Duration::from_secs(300),
        "export" | "export-all" | "import" | "import-all" => Duration::from_secs(900),
        _ => Duration::from_secs(180),
    }
}

fn run_cli(args: &[&str]) -> Result<Value, String> {
    let root = project_root();
    let python = python_path(&root);
    if !python.is_file() {
        return Err("未找到可用的 Python 运行时，请安装 Python 或创建项目 .venv".into());
    }
    let code = code_root(&root);
    let data_root = storage_root(&root);
    let profiles = data_root.join("profiles");
    let mut child = silent_command(&python)
        .arg("-m")
        .arg("core.cli")
        .arg("--profiles")
        .arg(&profiles)
        .args(args)
        .current_dir(&code)
        .env("PYTHONPATH", &code)
        .env("PYTHONIOENCODING", "utf-8")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to run CLI: {e}"))?;

    // Drain both pipes on their own threads; a full pipe buffer would deadlock
    // a plain wait loop once a list gets long.
    let mut stdout_pipe = child.stdout.take().ok_or("无法读取命令输出")?;
    let mut stderr_pipe = child.stderr.take().ok_or("无法读取命令输出")?;
    let stdout_reader = std::thread::spawn(move || {
        let mut buffer = Vec::new();
        let _ = stdout_pipe.read_to_end(&mut buffer);
        buffer
    });
    let stderr_reader = std::thread::spawn(move || {
        let mut buffer = Vec::new();
        let _ = stderr_pipe.read_to_end(&mut buffer);
        buffer
    });

    let timeout = cli_timeout(args);
    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {
                if Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!(
                        "命令执行超时（{} 秒），请检查网络或代理配置",
                        timeout.as_secs()
                    ));
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(e) => {
                let _ = child.kill();
                return Err(format!("failed to wait for CLI: {e}"));
            }
        }
    };
    let stdout = String::from_utf8_lossy(&stdout_reader.join().unwrap_or_default())
        .trim()
        .to_string();
    let stderr = String::from_utf8_lossy(&stderr_reader.join().unwrap_or_default())
        .trim()
        .to_string();
    if !status.success() {
        let detail = format!("{}{}", stdout, stderr).trim().to_string();
        let message = if detail.contains("could not draw a coherent identity") {
            "暂时没有生成符合条件的指纹，请稍后重试".to_string()
        } else if detail.contains("proxy mode requires") {
            "代理模式需要选择节点或填写代理服务器".to_string()
        } else if detail.contains("unsupported os") || detail.contains("unsupported country") {
            format!("身份参数不受支持：{detail}")
        } else {
            detail
        };
        let label = match args.first() {
            Some(&"create") => "创建命令失败",
            Some(&"edit") => "保存失败",
            Some(&"proxy-import") => "导入订阅失败",
            Some(&"proxy-delete") => "删除订阅失败",
            Some(&"proxy-set-core") => "设置内核失败",
            Some(&"import") => "导入身份包失败",
            Some(&"launch") => "启动失败",
            _ => "命令执行失败",
        };
        return Err(format!("{label}：{message}"));
    }
    if stdout.is_empty() {
        return Ok(Value::Null);
    }
    serde_json::from_str(&stdout).map_err(|e| format!("bad CLI JSON {e}: {stdout}"))
}

/// Run the CLI off the async worker so URL downloads cannot stall the UI.
async fn run_cli_task(args: Vec<String>) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let refs: Vec<&str> = args.iter().map(|arg| arg.as_str()).collect();
        run_cli(&refs)
    })
    .await
    .map_err(|e| format!("命令执行失败：{e}"))?
}

#[tauri::command]
async fn list_identities() -> Result<Value, String> {
    run_cli_task(vec!["list".into()]).await
}

/// Return actionable diagnostics for the first-run screen and support logs.
/// This deliberately does not launch anything; it only checks the local
/// runtime required by the current development distribution.
#[tauri::command]
async fn environment_check() -> Result<Value, String> {
    let root = project_root();
    let data_root = storage_root(&root);
    let python = python_path(&root);
    let cli = cli_path(&root);
    let profiles = data_root.join("profiles");
    let python_ok = python.is_file();
    let cli_ok = cli.is_file();
    let profiles_ok = profiles.is_dir() || std::fs::create_dir_all(&profiles).is_ok();
    let camoufox_exe = find_engine(&root);
    let engine_ok = camoufox_exe.is_some();
    // Probe the import with a timeout: a slow interpreter must not freeze the UI.
    let camoufox_import_ok = python_ok
        && run_with_timeout(
            &python,
            &["-c", "import camoufox"],
            &code_root(&root),
            std::time::Duration::from_secs(10),
        )
        .unwrap_or(false);
    let checks = vec![
        serde_json::json!({
            "key": "python",
            "label": "Python 运行时",
            "ok": python_ok,
            "detail": if python_ok { python.display().to_string() } else { "未检测到系统 Python，可一键安装".to_string() }
        }),
        serde_json::json!({
            "key": "cli",
            "label": "Cacer CLI",
            "ok": cli_ok,
            "detail": cli.display().to_string()
        }),
        serde_json::json!({
            "key": "profiles",
            "label": "身份数据目录",
            "ok": profiles_ok,
            "detail": profiles.display().to_string()
        }),
        serde_json::json!({
            "key": "engine",
            "label": "Camoufox 浏览器引擎",
            "ok": engine_ok && camoufox_import_ok,
            "detail": if !camoufox_import_ok {
                "未安装 camoufox 依赖，可一键安装".to_string()
            } else if let Some(exe) = &camoufox_exe {
                exe.display().to_string()
            } else {
                "未下载浏览器引擎，可一键安装（约 700 MB）".to_string()
            }
        }),
    ];
    Ok(serde_json::json!({
        "ready": python_ok && cli_ok && profiles_ok && engine_ok && camoufox_import_ok,
        "root": root.display().to_string(),
        "data_root": data_root.display().to_string(),
        "checks": checks
    }))
}

#[tauri::command]
async fn create_identity(req: Value) -> Result<Value, String> {
    let name = req["name"].as_str().unwrap_or("").trim().to_string();
    if name.is_empty() {
        return Err("名称必填".into());
    }
    let os = req["os"].as_str().unwrap_or("");
    let country = req["country"].as_str().unwrap_or("");
    let network = req["network"].as_str().unwrap_or("direct");
    let proxy_server = req["proxy_server"].as_str().unwrap_or("");
    let proxy_source = req["proxy_source"].as_str().unwrap_or("");
    let proxy_node = req["proxy_node"].as_str().unwrap_or("");
    let note = req["note"].as_str().unwrap_or("");
    let ui_locale = req["ui_locale"].as_str().unwrap_or("zh-CN");
    let memory_cache = req["memory_cache"].as_bool().unwrap_or(true);

    // Country-filtered fingerprint draws can legitimately miss several times;
    // use a larger budget for GUI creation so users do not see intermittent
    // `CLI rc=1` failures.
    let mut args: Vec<String> = vec![
        "create".into(),
        name.clone(),
        "--network".into(),
        network.to_string(),
        "--max-draws".into(),
        "80".into(),
    ];
    if !os.is_empty() {
        args.push("--os".into());
        args.push(os.to_string());
    }
    if !country.is_empty() {
        args.push("--country".into());
        args.push(country.to_string());
    }
    if !proxy_server.is_empty() {
        args.push("--proxy-server".into());
        args.push(proxy_server.to_string());
    }
    if !proxy_source.is_empty() && !proxy_node.is_empty() {
        args.push("--proxy-source".into());
        args.push(proxy_source.to_string());
        args.push("--proxy-node".into());
        args.push(proxy_node.to_string());
    }
    if !note.is_empty() {
        args.push("--note".into());
        args.push(note.to_string());
    }
    args.push("--ui-locale".into());
    args.push(ui_locale.to_string());
    if !memory_cache {
        args.push("--no-memory-cache".into());
    }
    run_cli_task(args).await
}

#[tauri::command]
fn system_proxy() -> Result<Value, String> {
    // Read the Windows user proxy (WinINET) so the GUI can prefill
    // "use system proxy" for new identities.
    let out = silent_command("reg")
        .args([
            "query",
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            "/v",
            "ProxyServer",
        ])
        .output()
        .map_err(|e| format!("reg query failed: {e}"))?;
    let text = String::from_utf8_lossy(&out.stdout);
    let server = text
        .lines()
        .find(|l| l.contains("ProxyServer"))
        .and_then(|l| l.rsplit(|c: char| c.is_whitespace()).next())
        .map(|s| s.trim().to_string())
        .unwrap_or_default();
    let out2 = silent_command("reg")
        .args([
            "query",
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            "/v",
            "ProxyEnable",
        ])
        .output()
        .map_err(|e| format!("reg query failed: {e}"))?;
    let text2 = String::from_utf8_lossy(&out2.stdout);
    let enabled = text2.contains("0x1");
    Ok(serde_json::json!({ "enabled": enabled, "server": server }))
}

#[tauri::command]
async fn edit_identity(id: String, req: Value) -> Result<Value, String> {
    let name = req["name"].as_str().unwrap_or("");
    let note = req["note"].as_str();
    let network = req["network"].as_str().unwrap_or("");
    let proxy_server = req["proxy_server"].as_str();
    let proxy_source = req["proxy_source"].as_str();
    let proxy_node = req["proxy_node"].as_str();
    let clear_proxy = req["clear_proxy"].as_bool().unwrap_or(false);
    let ui_locale = req["ui_locale"].as_str();
    let memory_cache = req["memory_cache"].as_bool();

    let mut args: Vec<String> = vec!["edit".into(), id.clone()];
    if !name.is_empty() {
        args.push("--name".into());
        args.push(name.to_string());
    }
    // Always forward the note (possibly empty) so it can be cleared.
    if let Some(value) = note {
        args.push("--note".into());
        args.push(value.to_string());
    }
    if !network.is_empty() {
        args.push("--network".into());
        args.push(network.to_string());
    }
    if let Some(locale) = ui_locale {
        args.push("--ui-locale".into());
        args.push(locale.to_string());
    }
    if let Some(cache) = memory_cache {
        args.push(if cache { "--memory-cache".to_string() } else { "--no-memory-cache".to_string() });
    }
    // Empty strings explicitly clear a previous subscription selection.
    if let Some(source) = proxy_source {
        args.push("--proxy-source".into());
        args.push(source.to_string());
    }
    if let Some(node) = proxy_node {
        args.push("--proxy-node".into());
        args.push(node.to_string());
    }
    if clear_proxy {
        args.push("--clear-proxy".into());
    } else if let Some(server) = proxy_server {
        // Only touch routing when the frontend actually sent the field: edits
        // made while the browser is running carry name/note only.
        args.push("--proxy-server".into());
        args.push(server.to_string());
    }
    run_cli_task(args).await
}

#[tauri::command]
async fn reorder_identities(ids: Vec<String>) -> Result<Value, String> {
    if ids.is_empty() {
        return Err("排序列表不能为空".into());
    }
    run_cli_task(vec!["reorder".into(), "--ids".into(), ids.join(",")]).await
}

#[tauri::command]
async fn export_cookies(id: String, output: String) -> Result<Value, String> {
    if output.trim().is_empty() { return Err("导出路径不能为空".into()); }
    run_cli_task(vec![
        "cookies".into(),
        id,
        "--output".into(),
        output.trim().to_string(),
    ])
    .await
}

#[tauri::command]
async fn rebuild_identity(id: String, os: String, country: String) -> Result<Value, String> {
    let mut args: Vec<String> =
        vec!["rebuild".into(), id, "--max-draws".into(), "80".into()];
    if !os.is_empty() {
        args.push("--os".into());
        args.push(os);
    }
    if !country.is_empty() {
        args.push("--country".into());
        args.push(country);
    }
    run_cli_task(args).await
}

#[tauri::command]
async fn clone_identity(id: String, name: String) -> Result<Value, String> {
    let name = name.trim();
    if name.is_empty() {
        return Err("新环境名称不能为空".into());
    }
    run_cli_task(vec!["clone".into(), id, name.to_string()]).await
}

#[tauri::command]
async fn delete_identity(id: String, purge: bool) -> Result<Value, String> {
    if purge {
        run_cli_task(vec!["delete".into(), id, "--purge-profile".into()]).await
    } else {
        run_cli_task(vec!["delete".into(), id]).await
    }
}

#[tauri::command]
async fn launch_identity(id: String) -> Result<Value, String> {
    // The Python CLI supervises the detached browser helper. Returning after
    // the helper publishes `starting` keeps the Tauri UI responsive; the
    // frontend refresh loop observes the later `running` state.
    run_cli_task(vec!["launch".into(), id, "--no-wait".into()]).await
}

#[tauri::command]
async fn stop_identity(id: String) -> Result<Value, String> {
    run_cli_task(vec!["stop".into(), id]).await
}

// ------------------------------------------------------- proxy subscriptions

#[tauri::command]
async fn proxy_sources() -> Result<Value, String> {
    run_cli_task(vec!["proxy-sources".into()]).await
}

#[tauri::command]
async fn proxy_nodes(source: String) -> Result<Value, String> {
    if source.trim().is_empty() {
        return Err("请先选择订阅".into());
    }
    run_cli_task(vec![
        "proxy-nodes".into(),
        "--source".into(),
        source.trim().to_string(),
    ])
    .await
}

/// Async: subscription URLs are fetched over the network.
#[tauri::command]
async fn proxy_import(kind: String, value: String, name: String, label: String) -> Result<Value, String> {
    let value = value.trim();
    if value.is_empty() {
        return Err("订阅内容不能为空".into());
    }
    let mut args: Vec<String> = vec![
        "proxy-import".into(),
        "--kind".into(),
        kind,
        "--value".into(),
        value.to_string(),
    ];
    if !name.trim().is_empty() {
        args.push("--name".into());
        args.push(name.trim().to_string());
    }
    if !label.trim().is_empty() {
        args.push("--label".into());
        args.push(label.trim().to_string());
    }
    run_cli_task(args).await
}

#[tauri::command]
async fn proxy_rename(source: String, label: String) -> Result<Value, String> {
    if source.trim().is_empty() {
        return Err("请先选择订阅".into());
    }
    let mut args: Vec<String> = vec![
        "proxy-rename".into(),
        "--source".into(),
        source.trim().to_string(),
    ];
    if !label.trim().is_empty() {
        args.push("--label".into());
        args.push(label.trim().to_string());
    }
    run_cli_task(args).await
}

#[tauri::command]
async fn proxy_delete(source: String) -> Result<Value, String> {
    if source.trim().is_empty() {
        return Err("请先选择订阅".into());
    }
    run_cli_task(vec![
        "proxy-delete".into(),
        "--source".into(),
        source.trim().to_string(),
    ])
    .await
}

#[tauri::command]
async fn proxy_set_core(path: String) -> Result<Value, String> {
    if path.trim().is_empty() {
        return Err("内核路径不能为空".into());
    }
    run_cli_task(vec![
        "proxy-set-core".into(),
        "--path".into(),
        path.trim().to_string(),
    ])
    .await
}

#[tauri::command]
async fn clash_configs() -> Result<Value, String> {
    run_cli_task(vec!["proxy-discover".into()]).await
}

// ---------------------------------------------------------- extension center

#[tauri::command]
async fn ext_list() -> Result<Value, String> {
    run_cli_task(vec!["ext-list".into()]).await
}

/// Async: the AMO search API is a network call.
#[tauri::command]
async fn ext_search(query: String, limit: usize) -> Result<Value, String> {
    let query = query.trim();
    if query.is_empty() {
        return Err("搜索关键词不能为空".into());
    }
    run_cli_task(vec![
        "ext-search".into(),
        "--query".into(),
        query.to_string(),
        "--limit".into(),
        limit.clamp(1, 40).to_string(),
    ])
    .await
}

/// Async: downloads the XPI from addons.mozilla.org.
#[tauri::command]
async fn ext_install(slug: String) -> Result<Value, String> {
    let slug = slug.trim();
    if slug.is_empty() {
        return Err("扩展标识不能为空".into());
    }
    run_cli_task(vec!["ext-install".into(), "--slug".into(), slug.to_string()]).await
}

/// Async: reads/extracts a local XPI or extension folder.
#[tauri::command]
async fn ext_import(path: String) -> Result<Value, String> {
    let path = path.trim();
    if path.is_empty() {
        return Err("请选择扩展安装包或文件夹".into());
    }
    run_cli_task(vec!["ext-import".into(), "--path".into(), path.to_string()]).await
}

#[tauri::command]
async fn ext_remove(slug: String) -> Result<Value, String> {
    let slug = slug.trim();
    if slug.is_empty() {
        return Err("扩展标识不能为空".into());
    }
    run_cli_task(vec!["ext-remove".into(), "--slug".into(), slug.to_string()]).await
}

// -------------------------------------------------- portable data + packs

/// The one folder that holds every user-owned file. The GUI shows this path
/// and offers to open it, so migration means copying a single directory.
#[tauri::command]
fn data_overview() -> Result<Value, String> {
    let root = project_root();
    let data = storage_root(&root);
    let packs = packs_dir(&root);
    let mut items = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&packs) {
        for entry in entries.flatten() {
            let path = entry.path();
            let is_pack = path
                .extension()
                .and_then(|ext| ext.to_str())
                .map(|ext| ext.eq_ignore_ascii_case("sfx"))
                .unwrap_or(false);
            if !is_pack {
                continue;
            }
            let meta = entry.metadata().ok();
            let modified = meta
                .as_ref()
                .and_then(|m| m.modified().ok())
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_secs())
                .unwrap_or(0);
            items.push(serde_json::json!({
                "name": path.file_name().and_then(|n| n.to_str()).unwrap_or_default(),
                "size": meta.as_ref().map(|m| m.len()).unwrap_or(0),
                "modified": modified,
            }));
        }
    }
    items.sort_by(|a, b| b["modified"].as_u64().cmp(&a["modified"].as_u64()));
    Ok(serde_json::json!({
        "dir": data.display().to_string(),
        "packs_dir": packs.display().to_string(),
        "packs": items,
    }))
}

fn safe_stem(name: &str) -> String {
    let cleaned: String = name
        .chars()
        .map(|c| match c {
            '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*' => '_',
            c if c.is_control() => '_',
            c => c,
        })
        .collect();
    let trimmed = cleaned.trim().trim_matches('.').trim().to_string();
    if trimmed.is_empty() { "identity".to_string() } else { trimmed }
}

/// Export straight into the packs folder instead of asking for a path.
#[tauri::command]
async fn export_pack(id: String, name: String) -> Result<Value, String> {
    let packs = packs_dir(&project_root());
    let stem = safe_stem(if name.trim().is_empty() { &id } else { name.trim() });
    let mut target = packs.join(format!("{stem}.sfx"));
    if target.exists() {
        let short: String = id.chars().take(8).collect();
        target = packs.join(format!("{stem}-{short}.sfx"));
    }
    let target_text = target.to_string_lossy().to_string();
    let mut value = run_cli_task(vec!["export".into(), id, target_text.clone()]).await?;
    if let Some(obj) = value.as_object_mut() {
        obj.insert("file".into(), serde_json::json!(target_text));
    }
    Ok(value)
}

#[tauri::command]
async fn import_pack(file: String) -> Result<Value, String> {
    let file = file.trim();
    if file.is_empty() {
        return Err("请选择身份包".into());
    }
    if file.contains('/') || file.contains('\\') {
        return Err("身份包名称不合法".into());
    }
    let path = packs_dir(&project_root()).join(file);
    if !path.is_file() {
        return Err(format!("找不到身份包：{}", path.display()));
    }
    run_cli_task(vec!["import".into(), path.to_string_lossy().to_string()]).await
}

/// Whole-data migration: one zip holding every environment (including saved
/// logins), subscription, setting and the launch history. A bare file name is
/// resolved to the user's Downloads folder by the CLI.
#[tauri::command]
async fn export_all_data(archive: String) -> Result<Value, String> {
    let archive = archive.trim();
    if archive.is_empty() {
        return Err("请填写导出文件名".into());
    }
    run_cli_task(vec![
        "export-all".into(),
        "--archive".into(),
        archive.to_string(),
    ])
    .await
}

#[tauri::command]
async fn import_all_data(archive: String) -> Result<Value, String> {
    let archive = archive.trim();
    if archive.is_empty() {
        return Err("请填写数据包路径".into());
    }
    run_cli_task(vec![
        "import-all".into(),
        "--archive".into(),
        archive.to_string(),
    ])
    .await
}

#[tauri::command]
fn open_data_dir() -> Result<Value, String> {
    let dir = storage_root(&project_root());
    std::fs::create_dir_all(&dir).map_err(|e| format!("无法创建数据目录：{e}"))?;
    Command::new("explorer")
        .arg(&dir)
        .spawn()
        .map_err(|e| format!("无法打开数据目录：{e}"))?;
    Ok(serde_json::json!({ "dir": dir.display().to_string() }))
}

#[tauri::command]
async fn launch_history(limit: usize) -> Result<Value, String> {
    let limit = limit.clamp(1, 500).to_string();
    run_cli_task(vec!["history".into(), "--limit".into(), limit]).await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            list_identities,
            environment_check,
            create_identity,
            edit_identity,
            reorder_identities,
            clone_identity,
            export_cookies,
            rebuild_identity,
            delete_identity,
            launch_identity,
            stop_identity,
            system_proxy,
            proxy_sources,
            proxy_nodes,
            proxy_import,
            proxy_rename,
            proxy_delete,
            proxy_set_core,
            clash_configs,
            ext_list,
            ext_search,
            ext_install,
            ext_import,
            ext_remove,
            data_overview,
            export_pack,
            import_pack,
            export_all_data,
            import_all_data,
            open_data_dir,
            launch_history,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
