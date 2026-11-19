"""Assemble installer resources from a published, fixed runtime release."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from prepare_release import copy_tree, sha256, tree_id  # noqa: E402


def fetch(url: str, retries: int = 3) -> bytes:
    last: Exception | None = None
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
        except Exception as error:
            last = error
    raise SystemExit(f"无法下载 {url}: {last}")


def valid_hash(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def runtime_assets(manifest: dict) -> list[dict]:
    return [manifest["python"], *manifest["font_packs"]]


def validate(manifest: dict, base: str) -> None:
    if (manifest.get("schema") != 2 or not valid_hash(manifest.get("engine_id"))
            or not isinstance(manifest.get("python"), dict)
            or not isinstance(manifest.get("font_packs"), list)
            or not isinstance(manifest.get("font_index"), dict)):
        raise SystemExit("运行时清单无效，需要包含语言字体包的 schema 2 清单")
    packs = manifest["font_packs"]
    if not any(pack.get("id") == "base" for pack in packs):
        raise SystemExit("运行时清单缺少基础字体包")
    names = set()
    for asset in runtime_assets(manifest):
        name = asset.get("file")
        if (not isinstance(name, str) or not name or "/" in name or "\\" in name
                or ":" in name or name in {".", ".."} or name in names
                or not valid_hash(asset.get("sha256"))
                or asset.get("url") != f"{base}/{name}"
                or not isinstance(asset.get("size"), int) or asset["size"] <= 0
                or not isinstance(asset.get("unpacked_size"), int) or asset["unpacked_size"] <= 0):
            raise SystemExit("运行时资源名称、地址、大小或哈希无效")
        names.add(name)


def download_asset(asset: dict, assets: Path, retries: int = 3) -> None:
    """Stream large archives, reusing only files with the expected size and hash."""
    assets.mkdir(parents=True, exist_ok=True)
    target = assets / asset["file"]
    if target.is_file() and target.stat().st_size == asset["size"] and sha256(target) == asset["sha256"]:
        return
    partial = target.with_suffix(target.suffix + ".partial")
    last: Exception | None = None
    for _ in range(retries):
        try:
            size = 0
            with urllib.request.urlopen(asset["url"], timeout=120) as response, partial.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > asset["size"]:
                        raise ValueError("下载内容超出清单大小")
                    output.write(chunk)
            if size != asset["size"] or sha256(partial) != asset["sha256"]:
                raise ValueError("运行时资源大小或 SHA256 不一致")
            partial.replace(target)
            return
        except Exception as error:
            last = error
        finally:
            partial.unlink(missing_ok=True)
    raise SystemExit(f"无法下载并验证 {asset['file']}: {last}")


def prepare(engine: Path | None, resources: Path, repo: str, tag: str,
            assets: Path | None = None) -> dict:
    base = f"https://github.com/{repo}/releases/download/{tag}"
    manifest_bytes = fetch(f"{base}/runtime-manifest.json")
    manifest = json.loads(manifest_bytes)
    validate(manifest, base)
    font_index = fetch(f"{base}/font-index.json")
    requirements = fetch(f"{base}/runtime-dependencies.txt")
    if json.loads(font_index) != manifest["font_index"]:
        raise SystemExit("字体索引与固定运行时清单不一致")
    runtime = resources / "runtime"
    if engine:
        if not (engine / "camoufox.exe").is_file():
            raise SystemExit("指定目录缺少 camoufox.exe")
        if resources.exists():
            shutil.rmtree(resources)
        browser = runtime / "camoufox"
        copy_tree(engine, browser, without_fonts=True)
        # Branding rewrites these files locally; always ship the pristine ones.
        for relative in ("browser/omni.ja", "camoufox.exe"):
            original = engine / (relative + ".cacer-original")
            if original.is_file():
                shutil.copy2(original, browser / relative)
    elif not (runtime / "camoufox/camoufox.exe").is_file():
        raise SystemExit("缺少浏览器引擎，请先准备完整资源或传入 --engine")

    # Do not overwrite the pin with whatever engine happened to be fetched.
    if tree_id(runtime / "camoufox") != manifest["engine_id"]:
        raise SystemExit("浏览器引擎与固定运行时不一致；请使用匹配的引擎，或发布新的运行时版本")
    core = resources / "core"
    if core.exists():
        shutil.rmtree(core)
    copy_tree(REPO / "core", core)
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "manifest.json").write_bytes(manifest_bytes)
    (runtime / "font-index.json").write_bytes(font_index)
    (runtime / "requirements.txt").write_bytes(requirements)
    if assets is not None:
        for asset in runtime_assets(manifest):
            download_asset(asset, assets)
        (assets / "font-index.json").write_bytes(font_index)
        (assets / "runtime-manifest.json").write_bytes(manifest_bytes)
        (assets / "runtime-dependencies.txt").write_bytes(requirements)
    print(f"运行时资源及引擎已固定: {tag}")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="baseless1119/CacerBrowser")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--assets", type=Path, help="Download verified archives for the app smoke test")
    parser.add_argument("--resources", type=Path, default=REPO / "manager" / "src-tauri" / "resources")
    arguments = parser.parse_args()
    prepare(arguments.engine, arguments.resources, arguments.repo, arguments.tag, arguments.assets)
