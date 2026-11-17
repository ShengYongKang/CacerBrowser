"""Extension center: one global add-on repository shared by every environment.

Camoufox is a Firefox build, so only Firefox add-ons (XPI) apply -- Chromium
CRX packages are not installable. The engine accepts a list of *extracted*
add-on directories at launch, which is why the per-environment switch is a
launch-time decision: toggling an extension never touches the fingerprint.

Layout under <data>/extensions/:

    registry.json              installed add-ons (metadata only)
    <slug>/<version>/          the extracted XPI itself
"""

from __future__ import annotations

from contextlib import nullcontext

import json
import logging
import os
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

AMO_API = "https://addons.mozilla.org/api/v5/addons"
ENGINE_SLUG = "ublock-origin"
ENGINE_NAME = "uBlock Origin"
ENGINE_ADDON_PATH = os.path.join("addons", "UBO")
REGISTRY_FILE = "registry.json"
SYNC_STATE_FILE = "shadowfox-extensions.json"
_SAFE_EXT = (".xpi", ".zip")


# --------------------------------------------------------------------- paths


def repo_root(profiles_dir: Path) -> Path:
    root = Path(profiles_dir).resolve().parent / "extensions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _link_or_copy(source: str, target: str) -> None:
    """Copy an extension file as a hard link when the volume supports it.

    Falls back to a regular copy (different volume / FAT / failure).
    """
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _prune_versions(slug_dir: Path, keep: Path) -> None:
    """Drop older version folders so upgrades do not leak full XPI payloads."""
    try:
        children = [child for child in slug_dir.iterdir() if child.is_dir()]
    except OSError:
        return
    for child in children:
        if child.resolve() == keep.resolve():
            continue
        shutil.rmtree(child, ignore_errors=True)


def _registry_path(root: Path) -> Path:
    return root / REGISTRY_FILE


def _load_registry(root: Path) -> List[Dict[str, Any]]:
    path = _registry_path(root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("extensions") if isinstance(data, dict) else data
    return [item for item in (items or []) if isinstance(item, dict) and item.get("slug")]


def _save_registry(root: Path, items: List[Dict[str, Any]]) -> None:
    path = _registry_path(root)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps({"extensions": items}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)


# ------------------------------------------------------------------ metadata


def _safe_component(value: str, fallback: str = "extension") -> str:
    cleaned = "".join(
        ch if (ch.isalnum() or ch in "._-") else "-" for ch in (value or "")
    ).strip("-.")
    return cleaned or fallback


def _addon_dir_name(addon_id: str) -> str:
    """Firefox requires an unpacked profile add-on's folder name to equal its
    add-on ID, so '@', '{', '}' and '+' must survive (only path separators and
    other illegal characters are replaced)."""
    cleaned = "".join(
        ch if (ch.isalnum() or ch in "@._-{}+~") else "-" for ch in (addon_id or "")
    ).strip(".-")
    return cleaned or "extension"


def _message(base: Path, locale: Optional[str], token: str) -> Optional[str]:
    if not locale:
        return None
    path = base / "_locales" / locale / "messages.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = data.get(token)
    if isinstance(entry, dict):
        message = entry.get("message")
        if isinstance(message, str) and message:
            return message
    return None


def _text(value: Any, base: Optional[Path] = None, locale: Optional[str] = None) -> str:
    """Manifest fields are either strings, __MSG_x__ placeholders or AMO's
    localized dicts; normalize all three to one display string."""
    if isinstance(value, str):
        if value.startswith("__MSG_") and value.endswith("__") and base is not None:
            token = value[6:-2]
            return _message(base, locale, token) or value
        return value
    if isinstance(value, dict):
        for key in ("zh-CN", "zh", "en-US", "en"):
            text = value.get(key)
            if isinstance(text, str) and text:
                return text
        for text in value.values():
            if isinstance(text, str) and text:
                return text
    return ""


def _manifest_meta(directory: Path) -> Dict[str, str]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    settings = manifest.get("browser_specific_settings") or manifest.get("applications") or {}
    gecko = settings.get("gecko") if isinstance(settings, dict) else {}
    addon_id = ""
    if isinstance(gecko, dict):
        addon_id = str(gecko.get("id") or "")
    locale = manifest.get("default_locale")
    return {
        "addon_id": addon_id,
        "name": _text(manifest.get("name"), directory, locale) or directory.name,
        "summary": _text(manifest.get("description"), directory, locale),
        "version": str(manifest.get("version") or ""),
    }


def _engine_dir() -> Optional[Path]:
    try:
        from .engine import get_path
        path = Path(get_path(ENGINE_ADDON_PATH))
    except Exception:
        return None
    return path if (path / "manifest.json").is_file() else None


def _engine_entry() -> Optional[Dict[str, Any]]:
    directory = _engine_dir()
    if directory is None:
        return None
    try:
        meta = _manifest_meta(directory)
    except Exception:
        meta = {"addon_id": "", "name": ENGINE_NAME, "summary": "", "version": ""}
    return {
        "slug": ENGINE_SLUG,
        "addon_id": meta["addon_id"],
        "name": meta["name"] or ENGINE_NAME,
        "summary": meta["summary"] or "引擎内置的广告与追踪拦截器。",
        "version": meta["version"],
        "source": "engine",
        "installed_at": "",
        "icon": "",
        "dir": str(directory),
        "engine": True,
        "removable": False,
    }


def _engine_addon_id() -> str:
    directory = _engine_dir()
    if directory is None:
        return ""
    try:
        return _manifest_meta(directory)["addon_id"]
    except Exception:
        return ""


def _public(entry: Dict[str, Any], root: Path) -> Dict[str, Any]:
    directory = Path(entry.get("dir") or "")
    if not directory.is_absolute():
        directory = root / directory
    return {
        "slug": entry.get("slug", ""),
        "addon_id": entry.get("addon_id", ""),
        "name": entry.get("name", ""),
        "summary": entry.get("summary", ""),
        "version": entry.get("version", ""),
        "source": entry.get("source", "local"),
        "installed_at": entry.get("installed_at", ""),
        "icon": entry.get("icon", ""),
        "engine": bool(entry.get("engine")),
        "removable": bool(entry.get("removable", True)),
        "present": (directory / "manifest.json").is_file(),
    }


# ------------------------------------------------------------------- listing


def list_extensions(profiles_dir: Path) -> List[Dict[str, Any]]:
    """Installed extensions: the engine's bundled add-on first, then the repo."""
    root = repo_root(profiles_dir)
    result: List[Dict[str, Any]] = []
    engine = _engine_entry()
    if engine:
        result.append(_public(engine, root))
    stale = False
    engine_id = _engine_addon_id()
    for entry in _load_registry(root):
        public = _public(entry, root)
        if not public["present"]:
            stale = True
            continue
        if public["slug"] == ENGINE_SLUG:
            continue
        if engine_id and public["addon_id"] == engine_id:
            continue
        result.append(public)
    if stale:
        _save_registry(root, [
            entry for entry in _load_registry(root)
            if _public(entry, root)["present"]
        ])
    return result


def enabled_addon_dirs(profiles_dir: Path, disabled: Optional[List[str]] = None) -> List[str]:
    """Extracted add-on directories to load at launch for one environment."""
    root = repo_root(profiles_dir)
    blocked = {str(item) for item in (disabled or [])}
    dirs: List[str] = []
    if ENGINE_SLUG not in blocked:
        engine = _engine_dir()
        if engine is not None:
            dirs.append(str(engine))
    for entry in _load_registry(root):
        if entry.get("slug") in blocked:
            continue
        directory = Path(entry.get("dir") or "")
        if not directory.is_absolute():
            directory = root / directory
        if (directory / "manifest.json").is_file():
            dirs.append(str(directory))
    return dirs


def sync_profile_extensions(
        profile_dir: Path,
        profiles_dir: Path,
        disabled: Optional[List[str]] = None,
) -> List[str]:
    """Mirror this environment's enabled add-ons into <profile>/extensions/.

    camoufox's own `addons=` option installs temporary add-ons: their settings
    (uBlock rules, translator preferences, ...) are wiped on every restart.
    Installing the same extracted directories as profile add-ons instead makes
    them permanent, so settings persist per environment. The switch stays a
    launch-time file operation: removing the folder makes Firefox uninstall the
    add-on cleanly (verified), restoring it re-installs it. Nothing here touches
    the fingerprint.
    """
    profile = Path(profile_dir)
    target_root = profile / "extensions"
    state_path = profile / SYNC_STATE_FILE
    try:
        previous = set(json.loads(
            state_path.read_text(encoding="utf-8")).get("ids") or [])
    except Exception:
        previous = set()

    desired: Dict[str, Path] = {}
    for directory in enabled_addon_dirs(profiles_dir, disabled):
        source = Path(directory)
        try:
            addon_id = _manifest_meta(source)["addon_id"]
        except Exception:
            continue
        if addon_id:
            desired[addon_id] = source

    target_root.mkdir(parents=True, exist_ok=True)
    for addon_id in previous - set(desired):
        stale = target_root / _addon_dir_name(addon_id)
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)

    synced: List[str] = []
    for addon_id, source in desired.items():
        target = target_root / _addon_dir_name(addon_id)
        try:
            wanted_version = _manifest_meta(source)["version"]
            if target.is_dir() and wanted_version and \
                    _manifest_meta(target)["version"] == wanted_version:
                synced.append(addon_id)
                continue
            incoming = target.with_name(target.name + ".incoming")
            if incoming.exists():
                shutil.rmtree(incoming, ignore_errors=True)
            # Hard-link the payload: each environment keeps its own add-on
            # folder, but N environments no longer store N copies of uBlock.
            shutil.copytree(source, incoming, copy_function=_link_or_copy)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            incoming.replace(target)
            synced.append(addon_id)
        except Exception:
            log.debug("extension sync failed for %s", addon_id, exc_info=True)

    try:
        state_path.write_text(
            json.dumps({"ids": sorted(synced)}, indent=2), encoding="utf-8")
    except OSError:
        pass
    return synced


# --------------------------------------------------------------- AMO (store)


def _get_json(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "ShadowFox/0.1", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ShadowFox/0.1"})
    with urllib.request.urlopen(request, timeout=90) as response, \
            open(destination, "wb") as handle:
        shutil.copyfileobj(response, handle)


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    target = target.resolve()
    for member in archive.infolist():
        destination = (target / member.filename).resolve()
        if destination != target and target not in destination.parents:
            raise ValueError("压缩包包含非法路径")
    archive.extractall(target)


def search_extensions(profiles_dir: Path, query: str, limit: int = 20) -> Dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise ValueError("搜索关键词不能为空")
    limit = max(1, min(int(limit or 20), 40))
    params = urllib.parse.urlencode({
        "q": query, "app": "firefox", "type": "extension",
        "page_size": limit, "lang": "zh-CN",
    })
    data = _get_json(f"{AMO_API}/search/?{params}")
    installed = {item["slug"] for item in list_extensions(profiles_dir)}
    results = []
    for addon in data.get("results", []):
        slug = str(addon.get("slug") or "")
        if not slug:
            continue
        current = addon.get("current_version") or {}
        ratings = addon.get("ratings") or {}
        authors = addon.get("authors") or []
        homepage = addon.get("homepage")
        results.append({
            "slug": slug,
            "name": _text(addon.get("name")) or slug,
            "summary": _text(addon.get("summary")),
            "version": str(current.get("version") or ""),
            "icon": addon.get("icon_url") or "",
            "users": int(addon.get("average_daily_users") or 0),
            "rating": round(float(ratings.get("average") or 0), 1),
            "author": str((authors[0] if authors else {}).get("name") or ""),
            "homepage": _text(homepage),
            "installed": slug in installed,
        })
    return {"query": query, "results": results}


def install_from_amo(profiles_dir: Path, slug: str, *, commit_lock=None) -> Dict[str, Any]:
    slug = _safe_component((slug or "").strip().lower())
    if not slug:
        raise ValueError("扩展标识不能为空")
    if slug == ENGINE_SLUG:
        raise ValueError("uBlock Origin 已由引擎内置，请在环境编辑里直接开关，无需重复安装")
    detail = _get_json(f"{AMO_API}/addon/{slug}/?lang=zh-CN")
    current = detail.get("current_version") or {}
    download = current.get("file") or {}
    url = download.get("url")
    if not url:
        raise ValueError("该扩展没有可下载的安装包")
    version = str(current.get("version") or download.get("version") or "0")
    name = _text(detail.get("name")) or slug
    summary = _text(detail.get("summary"))

    root = repo_root(profiles_dir)
    version_dir = root / slug / _safe_component(version, "0")
    # Download, extract and validate before touching an installed version.
    with tempfile.TemporaryDirectory(dir=root.parent) as tmp:
        package = Path(tmp) / "package.xpi"
        extracted = Path(tmp) / "pkg"
        _download(str(url), package)
        with zipfile.ZipFile(package) as archive:
            _safe_extract(archive, extracted)
        if not (extracted / "manifest.json").is_file():
            raise ValueError("安装包格式不正确（缺少 manifest.json）")
        meta = _manifest_meta(extracted)
        entry = {
            "slug": slug,
            "addon_id": meta["addon_id"],
            "name": meta["name"] or name,
            "summary": meta["summary"] or summary,
            "version": meta["version"] or version,
            "source": "amo",
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "icon": detail.get("icon_url") or "",
            "dir": str(version_dir.relative_to(root)),
        }
        with commit_lock or nullcontext():
            if version_dir.is_dir():
                shutil.rmtree(version_dir)
            version_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(extracted), str(version_dir))
            _upsert(root, entry)
            _prune_versions(version_dir.parent, version_dir)
    return _public(entry, root)


def import_local(profiles_dir: Path, path_str: str, *, commit_lock=None) -> Dict[str, Any]:
    source = Path((path_str or "").strip().strip('"')).expanduser()
    if not source.exists():
        raise ValueError(f"找不到文件或文件夹：{source}")
    root = repo_root(profiles_dir)

    with tempfile.TemporaryDirectory(dir=root.parent) as tmp:
        extracted = Path(tmp) / "pkg"
        if source.is_dir():
            shutil.copytree(source, extracted)
        elif source.suffix.lower() in _SAFE_EXT:
            with zipfile.ZipFile(source) as archive:
                _safe_extract(archive, extracted)
        else:
            raise ValueError("仅支持 .xpi / .zip 安装包或已解压的扩展文件夹")
        # Some packages wrap everything in a single top-level folder.
        if not (extracted / "manifest.json").is_file():
            children = [p for p in extracted.iterdir() if p.is_dir()]
            if len(children) == 1 and (children[0] / "manifest.json").is_file():
                extracted = children[0]
        if not (extracted / "manifest.json").is_file():
            raise ValueError("安装包格式不正确（缺少 manifest.json）")

        meta = _manifest_meta(extracted)
        if meta["addon_id"] and meta["addon_id"] == _engine_addon_id():
            raise ValueError("该扩展已由引擎内置，无需重复导入")
        slug = _safe_component(
            (meta["addon_id"] or source.stem or "extension").lower().replace("@", "-"))
        version = _safe_component(meta["version"] or "0", "0")
        target = root / slug / version
        entry = {
            "slug": slug,
            "addon_id": meta["addon_id"],
            "name": meta["name"],
            "summary": meta["summary"],
            "version": meta["version"] or version,
            "source": "local",
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "icon": "",
            "dir": str(target.relative_to(root)),
        }
        with commit_lock or nullcontext():
            if target.is_dir():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(extracted), str(target))
            _upsert(root, entry)
            _prune_versions(target.parent, target)
    return _public(entry, root)


def remove_extension(profiles_dir: Path, slug: str) -> Dict[str, Any]:
    slug = (slug or "").strip()
    if slug == ENGINE_SLUG:
        raise ValueError("引擎内置扩展不能卸载，只能在环境里关闭")
    root = repo_root(profiles_dir)
    items = _load_registry(root)
    matched = [item for item in items if item.get("slug") == slug]
    if not matched:
        raise ValueError(f"没有找到扩展 {slug}")
    _save_registry(root, [item for item in items if item.get("slug") != slug])
    directory = root / _safe_component(slug)
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)
    return {"slug": slug, "removed": True}


def _upsert(root: Path, entry: Dict[str, Any]) -> None:
    items = [item for item in _load_registry(root) if item.get("slug") != entry["slug"]]
    items.append(entry)
    _save_registry(root, items)
