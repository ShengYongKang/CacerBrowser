"""Build a browser-only install tree and independently cached runtime assets.

Run with the clean dependency interpreter. The embedded Python archive is
provided by CI. Fingerprint model data is prepared before archiving dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clean_file(path: Path) -> bool:
    return (
        not any(part in {"__pycache__", ".pytest_cache"} for part in path.parts)
        and path.suffix not in {".pyc", ".pyo"}
        and not path.name.endswith(".cacer-original")
        and not path.name.startswith(".cacer-")
    )


def archive_tree(source: Path, output: Path) -> dict:
    size = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file() and clean_file(path.relative_to(source)):
                info = zipfile.ZipInfo(path.relative_to(source).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with path.open("rb") as source_file, archive.open(info, "w", force_zip64=True) as archive_file:
                    shutil.copyfileobj(source_file, archive_file, length=1024 * 1024)
                size += path.stat().st_size
    return {
        "sha256": sha256(output),
        "size": output.stat().st_size,
        "unpacked_size": size,
        "file": output.name,
    }


def copy_tree(source: Path, target: Path, *, without_fonts: bool = False) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if not clean_file(relative) or (without_fonts and relative.parts[0] == "fonts"):
            continue
        if path.is_file():
            output = target / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, output)


def tree_id(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def prepare(engine: Path, embed: Path, assets: Path, resources: Path, release_base: str) -> dict:
    if not (engine / "camoufox.exe").is_file() or not (engine / "fonts").is_dir():
        raise ValueError("Expected an installed Camoufox engine with its fonts directory")
    if not release_base.startswith("https://github.com/") or "/releases/download/" not in release_base:
        raise ValueError("Expected a versioned GitHub Release download base")
    if resources.exists():
        shutil.rmtree(resources)
    resources.mkdir(parents=True)
    assets.mkdir(parents=True, exist_ok=True)
    copy_tree(REPO / "core", resources / "core")
    browser = resources / "runtime" / "camoufox"
    copy_tree(engine, browser, without_fonts=True)
    # Local branding modifies omni.ja and camoufox.exe; always package originals
    # rather than a developer's branded/experimental engine.
    for relative in ("browser/omni.ja", "camoufox.exe"):
        original = engine / (relative + ".cacer-original")
        if original.is_file():
            shutil.copy2(original, browser / relative)
    engine_id = tree_id(browser)

    font_asset = archive_tree(engine / "fonts", assets / "fonts.zip")
    if font_asset["unpacked_size"] == 0:
        raise ValueError("The font bundle is empty")

    # Fresh CI environments do not have fpgen's lazily downloaded model yet.
    # Initialize it before copying site-packages so users receive a complete runtime.
    import fpgen
    fpgen.generate()

    with tempfile.TemporaryDirectory(prefix="cacer-python-build-") as temporary:
        python = Path(temporary)
        with zipfile.ZipFile(embed) as archive:
            archive.extractall(python)
        if not (python / "python.exe").is_file():
            raise ValueError("Not a Windows embedded Python archive")
        site = Path(sys.prefix) / "Lib" / "site-packages"
        if not site.is_dir():
            raise ValueError("Run using the clean Windows dependency venv")
        for item in site.iterdir():
            if item.name.startswith(("pip", "setuptools", "_distutils", "wheel")):
                continue
            if item.is_dir():
                copy_tree(item, python / "Lib" / "site-packages" / item.name)
            elif clean_file(item):
                target = python / "Lib" / "site-packages" / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        pth_files = list(python.glob("python*._pth"))
        if len(pth_files) != 1:
            raise ValueError("Expected exactly one embedded Python path configuration")
        stdlib = next(python.glob("python3*.zip")).name
        pth_files[0].write_text(f"{stdlib}\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
        python_asset = archive_tree(python, assets / "python-runtime.zip")

    import subprocess
    locked = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    (assets / "runtime-dependencies.txt").write_text(locked, encoding="utf-8")
    shutil.copy2(assets / "runtime-dependencies.txt", resources / "runtime" / "requirements.txt")
    manifest = {
        "schema": 1,
        "engine_id": engine_id,
        "python_version": ".".join(map(str, sys.version_info[:2])),
        "fonts": {**font_asset, "url": release_base.rstrip("/") + "/" + font_asset["file"]},
        "python": {**python_asset, "url": release_base.rstrip("/") + "/" + python_asset["file"]},
    }
    (resources / "runtime" / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    shutil.copy2(resources / "runtime" / "manifest.json", assets / "runtime-manifest.json")
    print(json.dumps(manifest, indent=2))
    print(f"Bundled browser core: {sum(p.stat().st_size for p in browser.rglob('*') if p.is_file()) / 1e6:.1f} MB")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--python-embed", required=True, type=Path)
    parser.add_argument("--release-base", required=True)
    parser.add_argument("--assets", type=Path, default=REPO / "build" / "release-assets")
    parser.add_argument("--resources", type=Path, default=REPO / "manager" / "src-tauri" / "resources")
    args = parser.parse_args()
    prepare(args.engine, args.python_embed, args.assets, args.resources, args.release_base)
