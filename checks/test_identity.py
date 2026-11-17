"""Phase 1 acceptance tests: identity model, validator, launcher mapping."""

import json
from pathlib import Path

import pytest

from core.identity import Geo, Identity, Launcher, _extract_geo, create_identity
from core.launcher import build_launch_options


def _base_fingerprint():
    """A coherent macOS/FR fpgen-style fingerprint (hand-built for validator
    tests; the draw tests below use the real generator)."""
    return {
        "browser": "Firefox",
        "navigator": {
            "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:156.0) Gecko/20100101 Firefox/156.0",
            "platform": "MacIntel",
            "oscpu": "Intel Mac OS X 10.15",
            "languages": ["fr", "fr-FR", "en-US", "en"],
            "language": "fr",
            "maxTouchPoints": 0,
            "hardwareConcurrency": 8,
        },
        "screen": {
            "width": 2560, "height": 1440,
            "availWidth": 2560, "availHeight": 1414,
            "colorDepth": 30, "pixelDepth": 30,
        },
        "window": {"outerWidth": 2560, "outerHeight": 1409, "screenX": 0, "screenY": 31},
        "gpu": {"vendor": "Apple Inc.", "renderer": "Apple M1, or similar"},
        "location": {"country": "FR", "region": "Île-de-France"},
        "intl": {"locale": "fr-FR", "timeZone": "Europe/Paris"},
    }


def make_identity(fp=None, geo=None, launcher=None, engine_os="macos", network_mode="direct"):
    fp = fp or _base_fingerprint()
    return Identity(
        id="test0001",
        name="test",
        created_at="2026-10-13T00:00:00+0800",
        engine_os=engine_os,
        geo=geo or _extract_geo(fp),
        fingerprint=fp,
        launcher=launcher or Launcher(maxTouchPoints=0, hardwareConcurrency=20),
        network_mode=network_mode,
    )


# ------------------------------------------------------------- validator


def test_baseline_is_coherent():
    assert make_identity().violations() == []


def test_windows_identity_with_non_angle_gpu_is_caught():
    fp = _base_fingerprint()
    fp["navigator"]["userAgent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) Gecko/20100101 Firefox/156.0"
    )
    fp["navigator"]["platform"] = "Win32"
    fp["navigator"]["oscpu"] = "Windows NT 10.0; Win64; x64"
    fp["gpu"] = {"vendor": "Apple Inc.", "renderer": "Apple M1, or similar"}
    ident = make_identity(fp=fp, engine_os="windows")
    v = ident.violations()
    assert any("ANGLE" in msg for msg in v), v


def test_macos_with_touchscreen_is_caught():
    ident = make_identity(launcher=Launcher(maxTouchPoints=5, hardwareConcurrency=20))
    v = ident.violations()
    assert any("maxTouchPoints" in msg for msg in v), v


def test_locale_country_mismatch_is_caught():
    ident = make_identity(geo=Geo(country="DE", region=None, locale="fr-FR",
                                  timezone="Europe/Paris", languages=["fr", "fr-FR"]))
    v = ident.violations()
    assert any("locale" in msg and "country" in msg for msg in v), v


def test_timezone_country_mismatch_is_caught():
    ident = make_identity(geo=Geo(country="FR", region=None, locale="fr-FR",
                                  timezone="America/New_York", languages=["fr", "fr-FR"]))
    v = ident.violations()
    assert any("timezone" in msg for msg in v), v


def test_primary_language_contradicts_locale_is_caught():
    ident = make_identity(geo=Geo(country="FR", region=None, locale="fr-FR",
                                  timezone="Europe/Paris", languages=["ja", "en-US"]))
    v = ident.violations()
    assert any("language" in msg and "locale" in msg for msg in v), v


def test_portrait_screen_is_caught():
    fp = _base_fingerprint()
    fp["screen"] = {"width": 1080, "height": 1920, "availWidth": 1080,
                    "availHeight": 1880, "colorDepth": 24, "pixelDepth": 24}
    v = make_identity(fp=fp).violations()
    assert any("portrait" in msg for msg in v), v


def test_window_larger_than_screen_warns_not_blocks():
    fp = _base_fingerprint()
    fp["window"] = {"outerWidth": 3840, "outerHeight": 2160, "screenX": 0, "screenY": 0}
    ident = make_identity(fp=fp)
    # camoufox clamps these at launch; they must not gate the identity
    assert ident.violations() == []
    assert any("outerWidth" in w for w in ident.warnings())


# --------------------------------------------------- real draws (fpgen)


def test_create_identity_draw_roundtrip(tmp_path):
    ident = create_identity("roundtrip", os="macos", profiles_dir=tmp_path)
    stored = json.loads((tmp_path / ident.id / "identity.json").read_text(encoding="utf-8"))
    assert stored["id"] == ident.id
    assert stored["fingerprint"] == ident.fingerprint
    loaded = Identity.load(tmp_path / ident.id / "identity.json")
    assert loaded.fingerprint == ident.fingerprint
    assert loaded.geo.timezone == ident.geo.timezone
    assert loaded.violations() == []


def test_two_identities_differ(tmp_path):
    a = create_identity("a", os="macos", profiles_dir=tmp_path)
    b = create_identity("b", os="macos", profiles_dir=tmp_path)
    assert a.fingerprint != b.fingerprint
    assert a.id != b.id


def test_country_filter_and_geo_coherence(tmp_path):
    ident = create_identity("fr", os="windows", country="FR", profiles_dir=tmp_path)
    assert ident.geo.country == "FR"
    assert ident.engine_os == "windows"
    assert ident.violations() == []
    # locale region must match FR
    assert ident.geo.locale.rsplit("-", 1)[-1] == "FR"


# ------------------------------------------------------------ launcher


def test_bundled_engine_is_used_for_launch_and_resources(tmp_path, monkeypatch):
    from core import engine, branding, extensions, launcher
    resources = tmp_path / "installed app" / "resources"
    executable = resources / "runtime" / "camoufox" / "camoufox.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(engine, "__file__", str(resources / "core" / "engine.py"))
    monkeypatch.setattr(branding, "ensure_browser_branding", lambda: None)
    monkeypatch.setattr(extensions, "sync_profile_extensions", lambda *args: None)
    monkeypatch.setattr(launcher, "_silence_gpu_probe", lambda *args: None)

    assert engine.get_path("properties.json") == str(executable.parent / "properties.json")
    opts = build_launch_options(make_identity(), profiles_dir=tmp_path / "profiles")
    assert opts["executable_path"] == str(executable)


def test_development_engine_uses_camoufox_installation(tmp_path, monkeypatch):
    from core import engine
    import camoufox.pkgman
    monkeypatch.setattr(engine, "__file__", str(tmp_path / "core" / "engine.py"))
    monkeypatch.setattr(camoufox.pkgman, "get_path", lambda name: f"installed/{name}")

    assert engine.bundled_executable() is None
    assert engine.get_path("properties.json") == "installed/properties.json"


def test_launch_options_mapping(tmp_path):
    ident = make_identity(network_mode="proxy")
    ident.proxy_server = "socks5://127.0.0.1:9150"
    opts = build_launch_options(ident, profiles_dir=tmp_path)
    assert opts["fingerprint"] is ident.fingerprint
    assert opts["config"]["navigator.maxTouchPoints"] == 0
    assert opts["config"]["navigator.hardwareConcurrency"] == 20
    assert opts["config"]["timezone"] == "Europe/Paris"
    assert opts["locale"] == ["fr-FR", "fr", "en-US", "en"]  # regional entry first
    assert opts["proxy"] == {"server": "socks5://127.0.0.1:9150"}
    assert opts["persistent_context"] is True
    assert opts["headless"] is False
    assert opts["user_data_dir"].replace("\\", "/").endswith(f"{ident.id}/profile")
    assert Path(opts["user_data_dir"]).is_dir()


@pytest.mark.parametrize("previous_proxy_type", [1, 2, 5])
def test_launch_options_direct_mode(tmp_path, previous_proxy_type):
    ident = make_identity(network_mode="direct")
    # Existing profiles may retain manual, PAC or system proxy settings.
    profile = tmp_path / ident.id / "profile"
    profile.mkdir(parents=True)
    previous = f'user_pref("network.proxy.type", {previous_proxy_type});\n'
    (profile / "prefs.js").write_text(previous, encoding="utf-8")
    (profile / "user.js").write_text(previous, encoding="utf-8")
    opts = build_launch_options(ident, profiles_dir=tmp_path)
    assert "proxy" not in opts
    assert opts["firefox_user_prefs"]["network.proxy.type"] == 0
    assert 'user_pref("network.proxy.type", 0);' in (
        profile / "user.js").read_text(encoding="utf-8")


def test_launch_options_subscription_proxy(tmp_path):
    ident = make_identity(network_mode="proxy")
    opts = build_launch_options(
        ident, profiles_dir=tmp_path, proxy_override="socks5://127.0.0.1:19150")
    assert opts["proxy"] == {"server": "socks5://127.0.0.1:19150"}
    assert "network.proxy.type" not in opts["firefox_user_prefs"]


def test_launch_options_refuse_proxy_without_server(tmp_path):
    """A proxy identity must never silently fall back to a direct connection."""
    ident = make_identity(network_mode="proxy")
    with pytest.raises(ValueError, match="requires a proxy"):
        build_launch_options(ident, profiles_dir=tmp_path)


def test_legacy_tor_mode_loads_as_direct(tmp_path):
    """Old files could store the removed `tor` mode; it must not leak direct."""
    ident = make_identity()
    payload = ident.to_dict()
    payload["network"]["mode"] = "tor"
    (tmp_path / "identity.json").write_text(json.dumps(payload), encoding="utf-8")
    loaded = Identity.load(tmp_path / "identity.json")
    assert loaded.network_mode == "direct"


def test_launch_options_refuse_incoherent_identity(tmp_path):
    ident = make_identity(launcher=Launcher(maxTouchPoints=5, hardwareConcurrency=20))
    with pytest.raises(ValueError, match="coherence violations"):
        build_launch_options(ident, profiles_dir=tmp_path)
