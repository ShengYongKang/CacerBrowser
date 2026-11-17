"""Verify separately packaged Python/fonts with an empty user directory."""
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
    resources = resources.resolve()
    manifest = json.loads((resources / "runtime/manifest.json").read_text(encoding="utf-8"))
    assert not (resources / "runtime/python/python.exe").exists()
    assert not (resources / "runtime/camoufox/fonts").exists()
    with tempfile.TemporaryDirectory(prefix="cacer-release-smoke-") as temporary:
        root = Path(temporary)
        python = root / "python"
        engine = root / "engine"
        shutil.copytree(resources / "runtime/camoufox", engine)
        for key, destination in (("python", python), ("fonts", engine / "fonts")):
            asset = manifest[key]
            path = assets / asset["file"]
            with path.open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == asset["sha256"]
            with zipfile.ZipFile(path) as archive:
                assert sum(entry.file_size for entry in archive.infolist()) == asset["unpacked_size"]
                archive.extractall(destination)
        interpreter = python / "python.exe"
        env = dict(os.environ, LOCALAPPDATA=str(root / "user"), CACER_ENGINE_DIR=str(engine),
                   CACER_TEST_RESOURCES=str(resources), CACER_TEST_ROOT=str(root),
                   PYTHONIOENCODING="utf-8")
        # The bootstrap must work from a different cwd with the isolated
        # embedded interpreter, including its detached browser owner.
        profiles = root / "data/profiles"
        def cli(*arguments):
            process = subprocess.run([str(interpreter), str(resources / "core/bootstrap.py"),
                                      "--profiles", str(profiles), *arguments],
                                     env=env, cwd=root, capture_output=True, text=True, timeout=180)
            assert process.returncode == 0, process.stdout + process.stderr
            return json.loads(process.stdout)
        assert cli("list") == []
        for target_os in ("windows", "macos", "linux"):
            source = """
import os, sys
from pathlib import Path
sys.path.insert(0, os.environ['CACER_TEST_RESOURCES'])
from core.identity import create_identity
from core.launcher import build_launch_options
from camoufox.sync_api import Camoufox
root = Path(os.environ['CACER_TEST_ROOT'])
identity = create_identity(name='Release check', os=sys.argv[1], country='US', max_draws=80)
options = build_launch_options(identity, profiles_dir=root / 'headless')
assert Path(options['executable_path']) == Path(os.environ['CACER_ENGINE_DIR']) / 'camoufox.exe'
options['headless'] = True
with Camoufox(**options) as browser:
    page = browser.pages[0] if browser.pages else browser.new_page()
    page.set_content('<title>Cacer release check</title><p>中文 English 🙂</p>')
    assert page.title() == 'Cacer release check'
print('Browser smoke OK:', sys.argv[1])
"""
            subprocess.run([str(interpreter), "-c", source, target_os], env=env, cwd=root, check=True, timeout=240)
        identity = cli("create", "Detached release check", "--os", "windows", "--country", "US", "--max-draws", "80")
        try:
            cli("launch", identity["id"])
            print("Detached embedded Python launch OK")
        finally:
            cli("stop", identity["id"])
        print("Separate runtime assets verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args()
    verify(args.resources, args.assets)
