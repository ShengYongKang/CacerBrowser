"""Verify language font packs and embedded Python with an empty user directory."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


def verify(resources: Path, assets: Path) -> None:
    resources, assets = resources.resolve(), assets.resolve()
    manifest = json.loads((resources / "runtime/manifest.json").read_text(encoding="utf-8"))
    try:
        from tools.prepare_release import tree_id
    except ModuleNotFoundError:
        from prepare_release import tree_id
    assert manifest["schema"] == 2
    assert tree_id(resources / "runtime/camoufox") == manifest["engine_id"], "Browser engine differs from the runtime pin"
    assert not (resources / "runtime/python/python.exe").exists()
    assert not (resources / "runtime/camoufox/fonts").exists()
    assert json.loads((assets / "font-index.json").read_text(encoding="utf-8")) == manifest["font_index"]
    print("Verifying runtime archive hashes and font coverage...", flush=True)
    seen = set()
    for asset in [manifest["python"], *manifest["font_packs"]]:
        path = assets / asset["file"]
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == asset["sha256"]
        with zipfile.ZipFile(path) as archive:
            assert sum(entry.file_size for entry in archive.infolist()) == asset["unpacked_size"]
            if asset is not manifest["python"]:
                for entry in archive.infolist():
                    assert entry.filename not in seen, entry.filename
                    seen.add(entry.filename)
                    indexed = manifest["font_index"]["files"][entry.filename]
                    assert indexed["group"] == asset["id"]
                    assert indexed["size"] == entry.file_size
    assert seen == manifest["font_index"]["files"].keys()
    with tempfile.TemporaryDirectory(prefix="cacer-release-smoke-") as temporary:
        root = Path(temporary)
        python = root / "python"
        engine = root / "engine"
        print("Copying the browser and extracting embedded Python...", flush=True)
        shutil.copytree(resources / "runtime/camoufox", engine)
        with zipfile.ZipFile(assets / manifest["python"]["file"]) as archive:
            archive.extractall(python)
        interpreter = python / "python.exe"
        env = dict(os.environ, LOCALAPPDATA=str(root / "user"), CACER_ENGINE_DIR=str(engine),
                   CACER_TEST_RESOURCES=str(resources), CACER_TEST_ROOT=str(root),
                   CACER_TEST_ASSETS=str(assets), PYTHONIOENCODING="utf-8")
        profiles = root / "data/profiles"

        def cli(*arguments):
            process = subprocess.run([str(interpreter), str(resources / "core/bootstrap.py"),
                                      "--profiles", str(profiles), *arguments],
                                     env=env, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=180)
            assert process.returncode == 0, process.stdout + process.stderr
            return json.loads(process.stdout)

        assert cli("list") == []
        # A fresh fonts directory for each case catches accidental reliance on
        # fonts cached by an earlier country or another OS.
        cases = [("windows", "US"), ("macos", "JP"), ("linux", "IN"),
                 ("windows", "CN"), ("macos", "TW"), ("linux", "KR")]
        for target_os, country in cases:
            print(f"Launching language smoke case: {target_os} / {country}", flush=True)
            source = """
import json, os, sys, shutil, zipfile
from pathlib import Path
sys.path.insert(0, os.environ['CACER_TEST_RESOURCES'])
from core.identity import create_identity
from core.launcher import build_launch_options, required_font_families
from camoufox.sync_api import Camoufox
root = Path(os.environ['CACER_TEST_ROOT'])
engine = Path(os.environ['CACER_ENGINE_DIR'])
assets = Path(os.environ['CACER_TEST_ASSETS'])
manifest = json.loads((Path(os.environ['CACER_TEST_RESOURCES']) / 'runtime/manifest.json').read_text(encoding='utf-8'))
index = manifest['font_index']
identity = create_identity(name='Release check', os=sys.argv[1], country=sys.argv[2], max_draws=80)
selected = {'base'}
locales = [identity.geo.locale, *identity.geo.languages, identity.launcher.ui_locale or identity.geo.locale]
for locale in locales:
    parts = locale.split('-')
    while parts:
        match = next((value for key, value in index['locales'].items() if key.lower() == '-'.join(parts).lower()), None)
        if match is not None:
            selected.update(match)
            break
        parts.pop()
    else:
        selected.update(pack['id'] for pack in manifest['font_packs'])
for family in required_font_families(identity):
    selected.update(index['families'].get(family.lower(), []))
fonts = engine / 'fonts'
if fonts.exists():
    shutil.rmtree(fonts)
for pack in manifest['font_packs']:
    if pack['id'] in selected:
        with zipfile.ZipFile(assets / pack['file']) as archive:
            archive.extractall(fonts)
# The largest optional programming-font family should not be a mandatory locale dependency.
assert 'latin-code' not in selected or any('iosevka' in family.lower() for family in required_font_families(identity))
options = build_launch_options(identity, profiles_dir=root / 'headless')
assert Path(options['executable_path']) == engine / 'camoufox.exe'
options['headless'] = True
with Camoufox(**options) as browser:
    page = browser.pages[0] if browser.pages else browser.new_page()
    page.set_content('<title>Cacer release check</title><p>中文 English 日本語 한국어 हिन्दी 🙂</p>')
    assert page.title() == 'Cacer release check'
    assert page.locator('p').bounding_box()['width'] > 0
print('Language-pack smoke OK:', sys.argv[1], sys.argv[2], sorted(selected))
"""
            subprocess.run([str(interpreter), "-c", source, target_os, country],
                           env=env, cwd=root, check=True, timeout=240)
        # Prepare all packs for the independent detached-process check.
        for pack in manifest["font_packs"]:
            with zipfile.ZipFile(assets / pack["file"]) as archive:
                archive.extractall(engine / "fonts")
        identity = cli("create", "Detached release check", "--os", "windows", "--country", "US", "--max-draws", "80")
        requirements = cli("font-requirements", identity["id"])
        assert requirements["fonts"] and requirements["country"] == "US"
        try:
            cli("launch", identity["id"])
            print("Detached embedded Python launch OK")
        finally:
            cli("stop", identity["id"])
        print("Language pack coverage, hashes and separate runtimes verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args()
    verify(args.resources, args.assets)
