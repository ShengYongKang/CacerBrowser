"""Browser UI branding must preserve the engine and stay cheap on relaunch."""

import zipfile

import pytest

from core import branding


def make_engine(tmp_path):
    archive = tmp_path / "browser" / "omni.ja"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("localization/zh-CN/branding/brand.ftl",
                        "-brand-short-name = Firefox\n-vendor-short-name = Mozilla\n")
        target.writestr("chrome/en-US/locale/branding/brand.dtd",
                        '<!ENTITY brandFullName "Camoufox">\n')
        target.writestr("chrome/en-US/locale/branding/brand.properties",
                        "brandShortName=Camoufox\nvendorShortName=Camoufox\n")
        target.writestr("chrome/browser/content/branding/icon32.png", b"old icon")
        target.writestr("unrelated/engine.js", b"unchanged engine code")
    return archive


def test_browser_branding_preserves_original_and_is_idempotent(tmp_path):
    archive = make_engine(tmp_path)
    original = archive.read_bytes()
    branding._apply_branding(tmp_path)
    assert archive.with_name("omni.ja.cacer-original").read_bytes() == original
    with zipfile.ZipFile(archive) as result:
        assert result.read("localization/zh-CN/branding/brand.ftl") == (
            b"-brand-short-name = Cacer\n-vendor-short-name = Mozilla\n")
        assert result.read("chrome/en-US/locale/branding/brand.dtd") == (
            b'<!ENTITY brandFullName "Cacer">\n')
        assert result.read("chrome/en-US/locale/branding/brand.properties") == (
            b"brandShortName=Cacer\nvendorShortName=Camoufox\n")
        assert result.read("unrelated/engine.js") == b"unchanged engine code"
        assert result.read("chrome/browser/content/branding/icon32.png").startswith(
            b"\x89PNG\r\n\x1a\n")
    first_mtime = archive.stat().st_mtime_ns
    first_bytes = archive.read_bytes()
    branding._apply_branding(tmp_path)
    assert archive.stat().st_mtime_ns == first_mtime
    assert archive.read_bytes() == first_bytes


def test_failed_replacement_leaves_engine_intact(tmp_path, monkeypatch):
    archive = make_engine(tmp_path)
    original = archive.read_bytes()

    def locked(*args):
        raise PermissionError("engine in use")

    monkeypatch.setattr(type(archive), "replace", locked)
    with pytest.raises(PermissionError, match="engine in use"):
        branding._apply_branding(tmp_path)
    assert archive.read_bytes() == original
    assert archive.with_name("omni.ja.cacer-original").read_bytes() == original
    assert not list(archive.parent.glob(".cacer-brand-*"))
