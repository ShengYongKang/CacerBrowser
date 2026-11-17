//! Download fixed, build-verified runtimes without requiring Python to exist.
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{atomic::{AtomicBool, Ordering}, Mutex};
use std::time::Duration;

#[derive(Clone, Deserialize)]
pub struct Asset {
    pub sha256: String,
    pub size: u64,
    pub unpacked_size: u64,
    pub url: String,
}
#[derive(Clone, Deserialize)]
pub struct Manifest {
    pub schema: u32,
    pub engine_id: String,
    pub python_version: String,
    pub python: Asset,
    pub fonts: Asset,
}
#[derive(Clone, Default, Serialize)]
pub struct Status {
    pub busy: bool,
    pub message: String,
    pub downloaded: u64,
    pub total: u64,
}
static STATUS: Mutex<Status> = Mutex::new(Status {
    busy: false, message: String::new(), downloaded: 0, total: 0,
});
static CANCEL: AtomicBool = AtomicBool::new(false);

pub fn status() -> Status { STATUS.lock().unwrap().clone() }
pub fn cancel() { CANCEL.store(true, Ordering::Relaxed); }
fn cancelled() -> Result<(), String> {
    if CANCEL.load(Ordering::Relaxed) { Err("已取消，可重新尝试".into()) } else { Ok(()) }
}
fn progress(message: &str, downloaded: u64, total: u64) {
    let mut state = STATUS.lock().unwrap();
    state.message = message.into();
    state.downloaded = downloaded;
    state.total = total;
}
pub fn operation<T>(work: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
    {
        let mut state = STATUS.lock().unwrap();
        if state.busy { return Err("另一个运行时安装正在进行".into()); }
        CANCEL.store(false, Ordering::Relaxed);
        *state = Status { busy: true, message: "正在准备".into(), ..Default::default() };
    }
    let result = work();
    let mut state = STATUS.lock().unwrap();
    state.busy = false;
    state.message = match &result { Ok(_) => "准备完成".into(), Err(error) => error.clone() };
    result
}
pub fn resource_dir(root: &Path) -> PathBuf {
    let packaged = root.join("resources/runtime");
    if packaged.join("manifest.json").is_file() { packaged } else { root.join("runtime") }
}
pub fn manifest(root: &Path) -> Result<Manifest, String> {
    let bytes = fs::read(resource_dir(root).join("manifest.json"))
        .map_err(|_| "当前构建没有运行时清单，请使用正式安装包".to_string())?;
    let manifest: Manifest = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    if manifest.schema != 1 || !valid_hash(&manifest.engine_id)
        || !valid_hash(&manifest.python.sha256) || !valid_hash(&manifest.fonts.sha256) {
        return Err("运行时清单无效".into());
    }
    Ok(manifest)
}
fn valid_hash(hash: &str) -> bool {
    hash.len() == 64 && hash.bytes().all(|b| b.is_ascii_hexdigit())
}
pub fn cache(root: &Path) -> PathBuf {
    super::storage_root(&root.to_path_buf()).parent().unwrap_or(root).join("runtime-cache")
}
pub fn python_dir(root: &Path, manifest: &Manifest) -> PathBuf {
    cache(root).join(format!("python-{}", &manifest.python.sha256[..16]))
}
pub fn engine_dir(root: &Path, manifest: &Manifest) -> PathBuf {
    cache(root).join(format!("engine-{}-{}", &manifest.engine_id[..16], &manifest.fonts.sha256[..16]))
}
fn complete(directory: &Path, hash: &str) -> bool {
    fs::read_to_string(directory.join(".complete")).map(|s| s == hash).unwrap_or(false)
}
pub fn prepared_engine(root: &Path) -> Option<PathBuf> {
    let manifest = manifest(root).ok()?;
    let directory = engine_dir(root, &manifest);
    (complete(&directory, &manifest.fonts.sha256) && directory.join("camoufox.exe").is_file())
        .then_some(directory)
}
pub fn prepared_python(root: &Path) -> Option<PathBuf> {
    let manifest = manifest(root).ok()?;
    let directory = python_dir(root, &manifest);
    let executable = directory.join("python.exe");
    (complete(&directory, &manifest.python.sha256) && executable.is_file()).then_some(executable)
}
pub fn selected_python(root: &Path) -> Option<PathBuf> {
    let path = PathBuf::from(fs::read_to_string(cache(root).join("python-path.txt")).ok()?.trim());
    path.is_file().then_some(path)
}
pub fn select_python(root: &Path, path: &str) -> Result<(), String> {
    let executable = PathBuf::from(path.trim().trim_matches('"'));
    if !executable.is_file() { return Err("请选择现有的 python.exe 文件".into()); }
    if !super::run_with_timeout(&executable, &["-c", "import camoufox, playwright, fpgen, PIL, socks"], &super::code_root(&root.to_path_buf()), Duration::from_secs(20)).unwrap_or(false) {
        return Err("该 Python 缺少运行依赖，请先执行安装命令".into());
    }
    fs::create_dir_all(cache(root)).map_err(|e| e.to_string())?;
    fs::write(cache(root).join("python-path.txt"), executable.to_string_lossy().as_bytes()).map_err(|e| e.to_string())
}
fn digest_file(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(|e| e.to_string())?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 1024 * 128];
    loop {
        cancelled()?;
        let length = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if length == 0 { break; }
        digest.update(&buffer[..length]);
    }
    Ok(format!("{:x}", digest.finalize()))
}
fn download(root: &Path, asset: &Asset, proxy: &str, name: &str) -> Result<PathBuf, String> {
    let url = reqwest::Url::parse(&asset.url).map_err(|e| e.to_string())?;
    if url.scheme() != "https" || url.host_str() != Some("github.com")
        || !url.path().starts_with("/ShengYongKang/CacerBrowser/releases/download/") {
        return Err("运行时下载地址不属于项目 Release".into());
    }
    let downloads = cache(root).join("downloads");
    fs::create_dir_all(&downloads).map_err(|e| e.to_string())?;
    let target = downloads.join(format!("{}.zip", asset.sha256));
    if target.is_file() && fs::metadata(&target).map_err(|e| e.to_string())?.len() == asset.size
        && digest_file(&target)? == asset.sha256 {
        return Ok(target);
    }
    let partial = downloads.join(format!("{}.partial", asset.sha256));
    let result = tauri::async_runtime::block_on(async {
        let mut builder = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(20))
            .read_timeout(Duration::from_secs(30))
            .timeout(Duration::from_secs(7200))
            .user_agent("Cacer-runtime");
        if !proxy.trim().is_empty() {
            builder = builder.proxy(reqwest::Proxy::all(proxy.trim()).map_err(|e| e.to_string())?);
        }
        let client = builder.build().map_err(|e| e.to_string())?;
        let mut response = client.get(url).send().await.and_then(|r| r.error_for_status()).map_err(|e| format!("下载失败：{e}"))?;
        if let Some(length) = response.content_length() {
            if length != asset.size { return Err("下载大小与清单不一致".into()); }
        }
        let mut output = File::create(&partial).map_err(|e| e.to_string())?;
        let mut digest = Sha256::new();
        let mut downloaded = 0;
        progress(name, 0, asset.size);
        loop {
            cancelled()?;
            let Some(chunk) = response.chunk().await.map_err(|e| e.to_string())? else { break; };
            downloaded += chunk.len() as u64;
            if downloaded > asset.size { return Err("下载内容超出预期大小".into()); }
            output.write_all(&chunk).map_err(|e| e.to_string())?;
            digest.update(&chunk);
            progress(name, downloaded, asset.size);
        }
        if downloaded != asset.size || format!("{:x}", digest.finalize()) != asset.sha256 {
            return Err("SHA256 校验失败，请重试".into());
        }
        drop(output);
        if target.exists() { fs::remove_file(&target).map_err(|e| e.to_string())?; }
        fs::rename(&partial, &target).map_err(|e| e.to_string())?;
        Ok(target.clone())
    });
    if result.is_err() { let _ = fs::remove_file(&partial); }
    result
}
fn extract(archive: &Path, target: &Path, limit: u64) -> Result<(), String> {
    let mut archive = zip::ZipArchive::new(File::open(archive).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    let mut total = 0u64;
    for index in 0..archive.len() {
        cancelled()?;
        let mut entry = archive.by_index(index).map_err(|e| e.to_string())?;
        let relative = entry.enclosed_name().ok_or("压缩包包含非法路径")?;
        // Windows also interprets backslashes, drive letters and ADS separators.
        if relative.components().any(|part| !matches!(part, std::path::Component::Normal(_)))
            || entry.name().contains(['\\', ':'])
            || entry.unix_mode().map(|m| m & 0o170000 == 0o120000).unwrap_or(false) {
            return Err("压缩包包含非法路径".into());
        }
        total = total.checked_add(entry.size()).ok_or("解压大小溢出")?;
        if total > limit { return Err("解压大小超出清单".into()); }
        let output = target.join(relative);
        if entry.is_dir() { fs::create_dir_all(output).map_err(|e| e.to_string())?; continue; }
        fs::create_dir_all(output.parent().ok_or("非法路径")?).map_err(|e| e.to_string())?;
        let mut file = File::create(&output).map_err(|e| e.to_string())?;
        let mut buffer = [0u8; 128 * 1024];
        let mut written = 0u64;
        loop {
            cancelled()?;
            let length = entry.read(&mut buffer).map_err(|e| e.to_string())?;
            if length == 0 { break; }
            written += length as u64;
            if written > entry.size() { return Err("文件解压大小无效".into()); }
            file.write_all(&buffer[..length]).map_err(|e| e.to_string())?;
        }
    }
    if total != limit { return Err("解压内容不完整".into()); }
    Ok(())
}
fn copy_tree(source: &Path, target: &Path) -> Result<(), String> {
    fs::create_dir_all(target).map_err(|e| e.to_string())?;
    for entry in fs::read_dir(source).map_err(|e| e.to_string())? {
        cancelled()?;
        let entry = entry.map_err(|e| e.to_string())?;
        if entry.file_type().map_err(|e| e.to_string())?.is_dir() {
            copy_tree(&entry.path(), &target.join(entry.file_name()))?;
        } else {
            fs::copy(entry.path(), target.join(entry.file_name())).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}
pub fn install(root: &Path, kind: &str, proxy: &str) -> Result<PathBuf, String> {
    let manifest = manifest(root)?;
    let (asset, target, label) = match kind {
        "python" => (&manifest.python, python_dir(root, &manifest), "正在下载 Python 与依赖"),
        "fonts" => (&manifest.fonts, engine_dir(root, &manifest), "正在下载浏览器字体"),
        _ => return Err("未知运行时类型".into()),
    };
    if complete(&target, &asset.sha256) { return Ok(target); }
    let archive = download(root, asset, proxy, label)?;
    progress("正在解压并验证", asset.size, asset.size);
    let staging = target.with_extension("staging");
    if staging.exists() { fs::remove_dir_all(&staging).map_err(|e| e.to_string())?; }
    fs::create_dir_all(&staging).map_err(|e| e.to_string())?;
    let result = (|| {
        if kind == "fonts" {
            copy_tree(&resource_dir(root).join("camoufox"), &staging)?;
            extract(&archive, &staging.join("fonts"), asset.unpacked_size)?;
        } else {
            extract(&archive, &staging, asset.unpacked_size)?;
            if !super::run_with_timeout(&staging.join("python.exe"), &["-c", "import camoufox, playwright, fpgen, PIL, socks"], &staging, Duration::from_secs(30)).unwrap_or(false) {
                return Err("Python 依赖验证失败".into());
            }
        }
        cancelled()?;
        fs::write(staging.join(".complete"), &asset.sha256).map_err(|e| e.to_string())?;
        if target.exists() { fs::remove_dir_all(&target).map_err(|e| e.to_string())?; }
        fs::rename(&staging, &target).map_err(|e| e.to_string())?;
        let _ = fs::remove_file(&archive);
        Ok(target)
    })();
    if result.is_err() { let _ = fs::remove_dir_all(staging); }
    result
}
fn ps_quote(text: &str) -> String { format!("'{}'", text.replace('\'', "''")) }
pub fn guide(root: &Path) -> Result<String, String> {
    let manifest = manifest(root)?;
    let destination = cache(root).join(format!("manual-python-{}", &manifest.python.sha256[..16]));
    let requirements = resource_dir(root).join("requirements.txt");
    Ok(format!(
        "# 若未安装 Python，请先执行（或从 python.org 安装 Python {} x64）\nwinget install -e --id Python.Python.{}\n\n# 在 PowerShell 中执行，创建独立环境并安装依赖\npy -{} -m venv {}\n& {} -m pip install -r {}\n\n# 安装完成后，在下方填入此解释器路径并应用\n# {}",
        manifest.python_version, manifest.python_version, manifest.python_version,
        ps_quote(&destination.to_string_lossy()),
        ps_quote(&destination.join("Scripts/python.exe").to_string_lossy()),
        ps_quote(&requirements.to_string_lossy()),
        destination.join("Scripts/python.exe").display()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use zip::write::SimpleFileOptions;

    struct TestDir(PathBuf);
    impl TestDir {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!("cacer-runtime-test-{}-{}", std::process::id(),
                std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for TestDir { fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); } }
    fn archive(path: &Path, name: &str, bytes: &[u8]) {
        let mut writer = zip::ZipWriter::new(File::create(path).unwrap());
        writer.start_file(name, SimpleFileOptions::default()).unwrap();
        writer.write_all(bytes).unwrap();
        writer.finish().unwrap();
    }
    #[test]
    fn extraction_rejects_windows_and_parent_paths() {
        let dir = TestDir::new();
        for name in ["../escape", "C:/escape", "fonts/file:stream", "fonts\\escape"] {
            let zip = dir.0.join("bad.zip");
            archive(&zip, name, b"test");
            assert!(extract(&zip, &dir.0.join("out"), 4).is_err(), "{name}");
        }
        assert!(!dir.0.join("escape").exists());
    }
    #[test]
    fn extraction_checks_size_and_crc() {
        let dir = TestDir::new();
        let zip = dir.0.join("good.zip");
        archive(&zip, "fonts/font.ttf", b"font");
        operation(|| extract(&zip, &dir.0.join("out"), 4)).unwrap();
        assert_eq!(fs::read(dir.0.join("out/fonts/font.ttf")).unwrap(), b"font");
        assert!(operation(|| extract(&zip, &dir.0.join("too-small"), 3)).is_err());
        assert!(operation(|| extract(&zip, &dir.0.join("too-large"), 5)).is_err());
    }
    #[test]
    fn cancellation_and_busy_are_reset_for_retry() {
        assert!(operation(|| {
            assert!(operation(|| Ok(())).is_err());
            cancel();
            cancelled()
        }).is_err());
        assert!(!status().busy);
        assert!(operation(cancelled).is_ok());
    }
    #[test]
    fn cached_font_install_is_verified_and_atomic() {
        let dir = TestDir::new();
        fs::create_dir_all(dir.0.join("core")).unwrap();
        fs::write(dir.0.join("core/cli.py"), "").unwrap();
        let runtime = dir.0.join("runtime");
        fs::create_dir_all(runtime.join("camoufox")).unwrap();
        fs::write(runtime.join("camoufox/camoufox.exe"), "engine").unwrap();
        let zip = dir.0.join("fonts.zip");
        archive(&zip, "font.ttf", b"font");
        let hash = operation(|| digest_file(&zip)).unwrap();
        let asset = serde_json::json!({
            "sha256": hash, "size": fs::metadata(&zip).unwrap().len(), "unpacked_size": 4,
            "url": "https://github.com/ShengYongKang/CacerBrowser/releases/download/v0.0.0/fonts.zip"
        });
        let manifest = serde_json::json!({"schema": 1, "engine_id": "a".repeat(64),
            "python_version": "3.14", "python": asset, "fonts": asset});
        fs::write(runtime.join("manifest.json"), manifest.to_string()).unwrap();
        let downloads = cache(&dir.0).join("downloads");
        fs::create_dir_all(&downloads).unwrap();
        fs::copy(&zip, downloads.join(format!("{hash}.zip"))).unwrap();
        let target = operation(|| install(&dir.0, "fonts", "")).unwrap();
        assert_eq!(prepared_engine(&dir.0).unwrap(), target);
        assert_eq!(fs::read(target.join("fonts/font.ttf")).unwrap(), b"font");
        assert_eq!(fs::read(target.join("camoufox.exe")).unwrap(), b"engine");
        assert_eq!(operation(|| install(&dir.0, "fonts", "")).unwrap(), target);
        // An invalid asset may never become a completed runtime.
        fs::remove_dir_all(&target).unwrap();
        fs::copy(&zip, downloads.join(format!("{hash}.zip"))).unwrap();
        let mut broken = manifest;
        broken["fonts"]["unpacked_size"] = 3.into();
        fs::write(runtime.join("manifest.json"), broken.to_string()).unwrap();
        assert!(operation(|| install(&dir.0, "fonts", "")).is_err());
        assert!(prepared_engine(&dir.0).is_none());
        assert!(!target.with_extension("staging").exists());
    }
    #[test]
    fn arbitrary_download_hosts_are_rejected() {
        let dir = TestDir::new();
        let asset = Asset { sha256: "a".repeat(64), size: 4, unpacked_size: 4,
            url: "https://example.com/payload.zip".into() };
        assert!(operation(|| download(&dir.0, &asset, "", "test")).is_err());
    }
    #[test]
    fn manual_commands_quote_paths() {
        assert_eq!(ps_quote("C:/it's a folder"), "'C:/it''s a folder'");
    }
}
