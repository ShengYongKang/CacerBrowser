"""Regression tests for restore rollback and slow command preparation."""

import json
import os
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from core import cli, extensions, proxy
from core.identity import Geo, Identity, Launcher


def make_identity():
    return Identity(
        id="environment1", name="Test", created_at="2026-11-17",
        engine_os="windows", geo=Geo(country="US", region=None,
        locale="en-US", timezone="America/New_York", languages=["en-US"]),
        fingerprint={}, launcher=Launcher(maxTouchPoints=0, hardwareConcurrency=8),
        network_mode="direct",
    )


def archive_at(tmp_path, entries):
    archive = tmp_path / "restore.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for name, data in entries:
            handle.writestr(name, data)
    return archive


def restore(tmp_path, entries):
    archive = archive_at(tmp_path, entries)
    return cli.main(["--profiles", str(tmp_path / "data" / "profiles"),
                     "import-all", "--archive", str(archive)])


@pytest.mark.parametrize("bad_path", [
    "../outside", "profiles/../../outside", "profiles/../settings.json",
    "profiles\\..\\..\\outside", "profiles/a/file:stream",
    ".shadowfox.lock", "mihomo/cores/config.yaml",
])
def test_invalid_archive_never_overwrites_earlier_files(tmp_path, bad_path):
    root = tmp_path / "data"
    root.mkdir()
    original = root / "settings.json"
    original.write_bytes(b"original")
    assert restore(tmp_path, [("settings.json", b"changed"), (bad_path, b"bad")]) == 1
    assert original.read_bytes() == b"original"
    assert not (tmp_path / "outside").exists()
    assert not list(tmp_path.glob(".shadowfox-restore-*"))


def test_restore_success_preserves_unrelated_files_and_skips_runtime(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "settings.json").write_bytes(b"old")
    (root / "unrelated.txt").write_bytes(b"keep")
    assert restore(tmp_path, [
        ("settings.json", b"new"), ("profiles/a/profile/cookies.sqlite", b"cookies"),
        ("profiles/a/runtime.json", b"ignore"), ("history.jsonl", b"history"),
    ]) == 0
    assert (root / "settings.json").read_bytes() == b"new"
    assert (root / "profiles/a/profile/cookies.sqlite").read_bytes() == b"cookies"
    assert not (root / "profiles/a/runtime.json").exists()
    assert (root / "unrelated.txt").read_bytes() == b"keep"


def test_restore_rolls_back_overwrites_and_new_files(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / "settings.json").write_bytes(b"original")
    replace = os.replace

    def fail_last(src, dst):
        if "staged" in Path(src).parts and Path(dst).name == "history.jsonl":
            raise PermissionError("simulated locked destination")
        return replace(src, dst)

    monkeypatch.setattr(cli.os, "replace", fail_last)
    assert restore(tmp_path, [
        ("settings.json", b"new"), ("profiles/new/profile/file", b"new"),
        ("history.jsonl", b"fail"),
    ]) == 1
    assert (root / "settings.json").read_bytes() == b"original"
    assert not (root / "profiles").exists()
    assert not (root / "history.jsonl").exists()
    assert not list(tmp_path.glob(".shadowfox-restore-*"))


def test_restore_keeps_backup_when_rollback_fails(tmp_path, monkeypatch, capsys):
    root = tmp_path / "data"
    root.mkdir()
    (root / "settings.json").write_bytes(b"original")
    replace = os.replace

    def fail_commit_and_rollback(src, dst):
        if Path(dst).name == "history.jsonl" or "backups" in Path(src).parts:
            raise PermissionError("simulated IO failure")
        return replace(src, dst)

    monkeypatch.setattr(cli.os, "replace", fail_commit_and_rollback)
    assert restore(tmp_path, [("settings.json", b"new"), ("history.jsonl", b"fail")]) == 1
    backups = list(tmp_path.glob(".shadowfox-restore-*/backups/settings.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"original"
    assert str(backups[0].parent) in json.loads(capsys.readouterr().out)["error"]


def test_restore_rejects_duplicate_targets_before_commit(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "settings.json").write_bytes(b"original")
    assert restore(tmp_path, [("settings.json", b"new"),
                              ("profiles/a/file", b"first"), ("profiles/A/file", b"other")]) == 1
    assert (root / "settings.json").read_bytes() == b"original"


def test_create_generates_unlocked_and_saves_locked(tmp_path, monkeypatch):
    held = False
    identity = make_identity()

    @contextmanager
    def lock(_profiles):
        nonlocal held
        assert not held
        held = True
        try:
            yield
        finally:
            held = False

    def generate(*args, **kwargs):
        assert not held and kwargs["persist"] is False
        return identity

    def save(self, profiles):
        assert held and self.sort_order == 7

    monkeypatch.setattr(cli, "_mutation_lock", lock)
    monkeypatch.setattr(cli, "create_identity", generate)
    monkeypatch.setattr(cli, "next_sort_order", lambda _: 7)
    monkeypatch.setattr(Identity, "save", save)
    assert cli.main(["--profiles", str(tmp_path / "data/profiles"),
                     "create", "Test"]) == 0


def test_rebuild_refuses_to_overwrite_edits_during_generation(tmp_path, monkeypatch):
    profiles = tmp_path / "data/profiles"
    original = make_identity()
    original.save(profiles)

    def generate(*args, **kwargs):
        assert kwargs["persist"] is False
        updated = make_identity()
        updated.name = "Edited meanwhile"
        updated.save(profiles)
        return make_identity()

    monkeypatch.setattr(cli, "create_identity", generate)
    assert cli.main(["--profiles", str(profiles), "rebuild", original.id]) == 1
    assert Identity.load(profiles / original.id / "identity.json").name == "Edited meanwhile"
    assert not (profiles.parent / "backups").exists()


@pytest.mark.parametrize("fail_save", [False, True])
def test_rebuild_preserves_backup_and_rolls_back_failed_save(tmp_path, monkeypatch, fail_save):
    profiles = tmp_path / "data/profiles"
    original = make_identity()
    original.save(profiles)
    cookies = profiles / original.id / "profile/cookies.sqlite"
    cookies.parent.mkdir()
    cookies.write_bytes(b"original cookies")
    rebuilt = make_identity()
    rebuilt.id = "unpublished"
    monkeypatch.setattr(cli, "create_identity", lambda *a, **k: rebuilt)
    save = Identity.save

    def maybe_fail(self, root):
        if self is rebuilt and fail_save:
            raise PermissionError("simulated save failure")
        return save(self, root)

    monkeypatch.setattr(Identity, "save", maybe_fail)
    result = cli.main(["--profiles", str(profiles), "rebuild", original.id])
    assert result == int(fail_save)
    assert not (profiles / "unpublished").exists()
    assert (profiles / original.id / "identity.json").is_file()
    if fail_save:
        assert cookies.read_bytes() == b"original cookies"
    else:
        backups = list((profiles.parent / "backups").glob("*/profile/cookies.sqlite"))
        assert len(backups) == 1 and backups[0].read_bytes() == b"original cookies"
        assert not cookies.exists()


def test_corrupt_archive_does_not_commit_earlier_entries(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "settings.json").write_bytes(b"original")
    archive = archive_at(tmp_path, [
        ("settings.json", b"new"), ("history.jsonl", b"unique-payload-to-corrupt"),
    ])
    archive.write_bytes(archive.read_bytes().replace(b"unique-payload-to-corrupt",
                                                   b"broken-payload-to-corrupt"))
    assert cli.main(["--profiles", str(root / "profiles"), "import-all",
                     "--archive", str(archive)]) == 1
    assert (root / "settings.json").read_bytes() == b"original"


def test_subscription_download_is_unlocked_and_commit_is_locked(tmp_path, monkeypatch):
    held = False

    @contextmanager
    def lock(_profiles):
        nonlocal held
        assert not held
        held = True
        try:
            yield
        finally:
            held = False

    def fetch(_):
        assert not held
        return b"proxies: [{name: test, type: socks5, server: 127.0.0.1, port: 1234}]"

    write = proxy.write_text_atomic

    def save(path, content):
        assert held
        return write(path, content)

    monkeypatch.setattr(cli, "_mutation_lock", lock)
    monkeypatch.setattr(proxy, "_fetch", fetch)
    monkeypatch.setattr(proxy, "write_text_atomic", save)
    assert cli.main(["--profiles", str(tmp_path / "data/profiles"), "proxy-import",
                     "--kind", "url", "--value", "https://example.test/sub",
                     "--name", "test", "--label", "Test"]) == 0
    assert (tmp_path / "data/subscriptions/test.yaml").is_file()


def test_extension_download_is_unlocked_and_registry_commit_is_locked(tmp_path, monkeypatch):
    held = False
    profiles = tmp_path / "data/profiles"

    @contextmanager
    def lock(_profiles):
        nonlocal held
        assert not held
        held = True
        try:
            yield
        finally:
            held = False

    def detail(_):
        assert not held
        return {"current_version": {"version": "1", "file": {"url": "fixture"}}}

    def download(_, destination):
        assert not held
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("manifest.json", json.dumps({
                "manifest_version": 2, "name": "Test", "version": "1",
                "browser_specific_settings": {"gecko": {"id": "test@example.test"}},
            }))

    upsert = extensions._upsert

    def save(root, entry):
        assert held
        return upsert(root, entry)

    monkeypatch.setattr(cli, "_mutation_lock", lock)
    monkeypatch.setattr(extensions, "_get_json", detail)
    monkeypatch.setattr(extensions, "_download", download)
    monkeypatch.setattr(extensions, "_upsert", save)
    assert cli.main(["--profiles", str(profiles), "ext-install", "--slug", "test"]) == 0
    target = profiles.parent / "extensions/test/1/manifest.json"
    assert target.is_file()

    def failed_download(*_):
        raise TimeoutError("simulated")

    monkeypatch.setattr(extensions, "_download", failed_download)
    assert cli.main(["--profiles", str(profiles), "ext-install", "--slug", "test"]) == 1
    assert target.is_file()
