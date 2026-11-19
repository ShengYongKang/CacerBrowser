"""Fail when the bundled manifest does not match its pinned runtime release."""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def fetch(url: str, retries: int = 3) -> bytes:
    last: Exception | None = None
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
        except Exception as error:  # noqa: BLE001 - surface the last attempt
            last = error
    raise SystemExit(f"无法下载 {url}: {last}")


def check(resources: Path, repo: str, tag: str, sums: Path | None = None) -> None:
    manifest = json.loads((resources / "runtime/manifest.json").read_text(encoding="utf-8"))
    base = f"https://github.com/{repo}/releases/download/{tag}/"
    assets = [manifest["python"], *manifest.get("font_packs", [])]
    if manifest.get("fonts"):
        assets.append(manifest["fonts"])
    text = sums.read_text(encoding="utf-8") if sums else fetch(base + "SHA256SUMS.txt").decode()
    digests = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            digests[parts[1].lstrip("*")] = parts[0].lower()
    for asset in assets:
        name = asset["file"]
        if not str(asset["url"]).startswith(base):
            raise SystemExit(f"{name} 不在固定运行时版本 {tag} 下")
        if digests.get(name) != asset["sha256"]:
            raise SystemExit(f"{name} 与 {tag} 的 SHA256SUMS.txt 不一致")
    # The app now preserves the published manifest byte for byte, so metadata
    # and dependency locks can also be checked against the release checksums.
    for relative, name in [
        ("manifest.json", "runtime-manifest.json"),
        ("font-index.json", "font-index.json"),
        ("requirements.txt", "runtime-dependencies.txt"),
    ]:
        with (resources / "runtime" / relative).open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if digests.get(name) != actual:
            raise SystemExit(f"{name} 与 {tag} 的 SHA256SUMS.txt 不一致")
    print(f"运行时清单与 {tag} 发布资源一致")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="baseless1119/CacerBrowser")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sums", type=Path)
    parser.add_argument("--resources", type=Path, default=REPO / "manager" / "src-tauri" / "resources")
    arguments = parser.parse_args()
    check(arguments.resources, arguments.repo, arguments.tag, arguments.sums)
