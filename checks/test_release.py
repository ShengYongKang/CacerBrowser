"""Regression checks for assembling current code with a fixed published runtime."""
import copy
import hashlib
import io
import json

import pytest

from tools import prepare_app_release as release
from tools.prepare_release import tree_id


@pytest.fixture
def published(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    (repo / "core").mkdir(parents=True)
    (repo / "core/cli.py").write_text("current code")
    monkeypatch.setattr(release, "REPO", repo)
    resources = tmp_path / "resources"
    browser = resources / "runtime/camoufox"
    browser.mkdir(parents=True)
    (browser / "camoufox.exe").write_bytes(b"engine")
    base = "https://github.com/owner/project/releases/download/runtime-1"

    def asset(name, payload):
        return {"file": name, "url": f"{base}/{name}",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload), "unpacked_size": len(payload)}

    manifest = {"schema": 2, "engine_id": tree_id(browser),
                "python": asset("python-runtime.zip", b"python"),
                "font_packs": [{"id": "base", **asset("fonts-base.zip", b"font")}],
                "font_index": {"files": {}}}
    responses = {"runtime-manifest.json": json.dumps(manifest).encode(),
                 "font-index.json": json.dumps(manifest["font_index"]).encode(),
                 "runtime-dependencies.txt": b"camoufox==0.5.8\n"}

    def fetch(url):
        assert url.startswith(base + "/")
        return responses[url.removeprefix(base + "/")]

    monkeypatch.setattr(release, "fetch", fetch)
    return resources, manifest, responses, base


def test_prepare_refreshes_existing_app_code_and_preserves_engine_pin(published):
    resources, manifest, _, _ = published
    (resources / "core").mkdir()
    (resources / "core/cli.py").write_text("stale code")
    (resources / "core/obsolete.py").write_text("removed module")
    result = release.prepare(None, resources, "owner/project", "runtime-1")
    assert result == manifest
    assert (resources / "core/cli.py").read_text() == "current code"
    assert not (resources / "core/obsolete.py").exists()
    assert json.loads((resources / "runtime/manifest.json").read_text()) == manifest


def test_prepare_rejects_engine_drift_instead_of_rewriting_pin(published):
    resources, _, _, _ = published
    (resources / "runtime/camoufox/camoufox.exe").write_bytes(b"newer incompatible engine")
    with pytest.raises(SystemExit, match="引擎与固定运行时不一致"):
        release.prepare(None, resources, "owner/project", "runtime-1")
    assert not (resources / "runtime/manifest.json").exists()


def test_prepare_rejects_mismatched_font_index(published):
    resources, _, responses, _ = published
    responses["font-index.json"] = b'{"files": {"unknown": {}}}'
    with pytest.raises(SystemExit, match="字体索引"):
        release.prepare(None, resources, "owner/project", "runtime-1")


@pytest.mark.parametrize("name", ["../payload.zip", "C:payload.zip", "fonts\\payload.zip"])
def test_asset_names_cannot_escape_download_directory(published, name):
    _, manifest, _, base = published
    manifest = copy.deepcopy(manifest)
    manifest["python"]["file"] = name
    manifest["python"]["url"] = f"{base}/{name}"
    with pytest.raises(SystemExit):
        release.validate(manifest, base)


def test_adjacent_runtime_tag_is_not_accepted_as_the_pinned_tag(published):
    _, manifest, _, base = published
    manifest["python"]["url"] = base + "0/python-runtime.zip"
    with pytest.raises(SystemExit):
        release.validate(manifest, base)


def test_download_rejects_same_size_tampering_and_repairs_corrupt_cache(published, tmp_path, monkeypatch):
    _, manifest, _, _ = published
    asset = manifest["python"]
    assets = tmp_path / "downloads"
    assets.mkdir()
    target = assets / asset["file"]
    target.write_bytes(b"broken")
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b"broken"))
    with pytest.raises(SystemExit, match="SHA256"):
        release.download_asset(asset, assets, retries=1)
    assert target.read_bytes() == b"broken"
    assert not target.with_suffix(".zip.partial").exists()
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b"python"))
    release.download_asset(asset, assets, retries=1)
    assert target.read_bytes() == b"python"
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("cache should be reused"))
    release.download_asset(asset, assets)


def test_smoke_assets_are_downloaded_from_the_fixed_release(published, tmp_path, monkeypatch):
    resources, manifest, _, base = published
    payloads = {f"{base}/python-runtime.zip": b"python",
                f"{base}/fonts-base.zip": b"font"}
    monkeypatch.setattr(release.urllib.request, "urlopen", lambda url, **kw: io.BytesIO(payloads[url]))
    assets = tmp_path / "downloads"
    release.prepare(None, resources, "owner/project", "runtime-1", assets)
    assert (assets / "python-runtime.zip").read_bytes() == b"python"
    assert (assets / "fonts-base.zip").read_bytes() == b"font"
    assert json.loads((assets / "runtime-manifest.json").read_text()) == manifest

@pytest.mark.parametrize("relative", ["manifest.json", "font-index.json", "requirements.txt"])
def test_manifest_check_rejects_changed_metadata(published, tmp_path, relative):
    from tools.check_runtime_manifest import check
    resources, manifest, _, _ = published
    release.prepare(None, resources, "owner/project", "runtime-1")
    lines = [f"{asset['sha256']}  {asset['file']}" for asset in release.runtime_assets(manifest)]
    for filename, name in [("manifest.json", "runtime-manifest.json"),
                           ("font-index.json", "font-index.json"),
                           ("requirements.txt", "runtime-dependencies.txt")]:
        digest = hashlib.sha256((resources / "runtime" / filename).read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}")
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text("\n".join(lines))
    check(resources, "owner/project", "runtime-1", sums)
    target = resources / "runtime" / relative
    # Whitespace preserves valid JSON while changing the published bytes.
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(SystemExit, match="SHA256SUMS"):
        check(resources, "owner/project", "runtime-1", sums)
