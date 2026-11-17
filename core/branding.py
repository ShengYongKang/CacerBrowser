"""Apply Cacer's UI branding to the installed browser, preserving the engine."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import struct
import shutil
import tempfile
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)
ASSETS = Path(__file__).with_name("assets")


def _brand_text(name: str, data: bytes) -> bytes:
    text = data.decode("utf-8")
    if name.endswith(".ftl"):
        text = re.sub(
            r"^(-brand-(?:shorter|short|full|shortcut|product)-name\s*=)[^\r\n]*",
            r"\1 Cacer", text, flags=re.MULTILINE)
    elif name.endswith(".dtd"):
        text = re.sub(
            r'(<!ENTITY\s+brand(?:Shorter|Short|Full|Product)Name\s+")[^"]*',
            r"\1Cacer", text)
    else:
        text = re.sub(
            r"^(brand(?:Shorter|Short|Full|Product)Name=)[^\r\n]*",
            r"\1Cacer", text, flags=re.MULTILINE)
    return text.encode("utf-8")


def _apply_branding(engine: Path) -> None:
    """Rebuild UI resources once per engine/icon version; retain an original."""
    from PIL import Image

    png = (ASSETS / "icon.png").read_bytes()
    ico = (ASSETS / "icon.ico").read_bytes()
    revision = b"Cacer UI v1:" + hashlib.sha256(png + ico).hexdigest().encode("ascii")
    archive = engine / "browser" / "omni.ja"
    with zipfile.ZipFile(archive) as source:
        current = source.comment == revision
    if not current:
        # Keep this beside the versioned engine, never inside profile exports.
        backup = archive.with_name("omni.ja.cacer-original")
        if not backup.exists():
            shutil.copy2(archive, backup)
        image = Image.open(io.BytesIO(png)).convert("RGBA")
        icons = {}
        for size in (16, 32, 48, 64, 128):
            out = io.BytesIO()
            image.resize((size, size), Image.Resampling.LANCZOS).save(out, format="PNG")
            icons[f"chrome/browser/content/branding/icon{size}.png"] = out.getvalue()
        icons["chrome/browser/content/branding/about-logo.png"] = png
        icons["chrome/browser/content/branding/about-logo@2x.png"] = png
        with tempfile.TemporaryDirectory(prefix=".cacer-brand-", dir=archive.parent) as work:
            staged = Path(work) / "omni.ja"
            with zipfile.ZipFile(archive) as source, zipfile.ZipFile(staged, "w") as target:
                for entry in source.infolist():
                    data = source.read(entry)
                    name = entry.filename
                    if name.endswith(("/branding/brand.ftl", "/branding/brand.dtd",
                                      "/branding/brand.properties")):
                        data = _brand_text(name, data)
                    elif name in icons:
                        data = icons[name]
                    target.writestr(entry, data)
                target.comment = revision
            # A running engine may hold this open on Windows. In that case
            # replacement fails safely; ensure_browser_branding retries later.
            staged.replace(archive)


def _apply_windows_icon(engine: Path, ico: bytes) -> None:
    """Atomically replace the executable's app/window icons on Windows."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes as w

    executable = engine / "camoufox.exe"
    stamp = engine / ".cacer-icon-sha256"
    signature = hashlib.sha256(executable.read_bytes() + ico).hexdigest()
    if stamp.is_file() and stamp.read_text(encoding="ascii") == signature:
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [w.LPCWSTR, w.HANDLE, w.DWORD]
    kernel.LoadLibraryExW.restype = w.HMODULE
    kernel.FreeLibrary.argtypes = [w.HMODULE]
    callback_type = ctypes.WINFUNCTYPE(
        w.BOOL, w.HMODULE, ctypes.c_void_p, ctypes.c_void_p, w.WORD, w.LPARAM)
    kernel.EnumResourceLanguagesW.argtypes = [
        w.HMODULE, ctypes.c_void_p, ctypes.c_void_p, callback_type, w.LPARAM]
    languages = {}

    @callback_type
    def record_language(module, kind, name, language, param):
        languages.setdefault(name, []).append(language)
        return True

    module = kernel.LoadLibraryExW(str(executable), None, 2)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # 1 is the Explorer application icon; 32512 is Firefox's window icon.
        for name in (1, 32512):
            if not kernel.EnumResourceLanguagesW(module, 14, name, record_language, 0):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.FreeLibrary(module)
    reserved, kind, count = struct.unpack_from("<HHH", ico)
    if reserved != 0 or kind != 1 or not count:
        raise ValueError("Invalid Cacer ICO")
    group = bytearray(struct.pack("<HHH", 0, 1, count))
    images = []
    for index in range(count):
        entry = struct.unpack_from("<BBBBHHII", ico, 6 + index * 16)
        size, offset = entry[-2:]
        data = ico[offset:offset + size]
        if len(data) != size:
            raise ValueError("Truncated Cacer ICO")
        resource_id = 60000 + index  # Keep existing engine resource IDs intact.
        group.extend(struct.pack("<BBBBHHIH", *entry[:6], size, resource_id))
        images.append((resource_id, data))
    kernel.BeginUpdateResourceW.argtypes = [w.LPCWSTR, w.BOOL]
    kernel.BeginUpdateResourceW.restype = w.HANDLE
    kernel.UpdateResourceW.argtypes = [
        w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, w.WORD,
        ctypes.c_void_p, w.DWORD]
    kernel.EndUpdateResourceW.argtypes = [w.HANDLE, w.BOOL]
    backup = executable.with_name("camoufox.exe.cacer-original")
    if not backup.exists():
        shutil.copy2(executable, backup)
    with tempfile.TemporaryDirectory(prefix=".cacer-icon-", dir=engine) as work:
        staged = Path(work) / executable.name
        shutil.copy2(executable, staged)
        handle = kernel.BeginUpdateResourceW(str(staged), False)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            resources = [(3, name, lang, data)
                         for lang in set(sum(languages.values(), []))
                         for name, data in images]
            resources.extend((14, name, lang, bytes(group))
                             for name, langs in languages.items() for lang in langs)
            for resource_type, name, language, data in resources:
                buffer = ctypes.create_string_buffer(data)
                if not kernel.UpdateResourceW(
                        handle, resource_type, name, language, buffer, len(data)):
                    raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            kernel.EndUpdateResourceW(handle, True)
            raise
        if not kernel.EndUpdateResourceW(handle, False):
            raise ctypes.WinError(ctypes.get_last_error())
        staged.replace(executable)
    stamp.write_text(
        hashlib.sha256(executable.read_bytes() + ico).hexdigest(), encoding="ascii")


def ensure_browser_branding() -> None:
    """Reapply after engine upgrades without changing web-facing fingerprints."""
    try:
        from .engine import get_path
        engine = Path(get_path("camoufox.exe")).parent
        _apply_branding(engine)
        _apply_windows_icon(engine, (ASSETS / "icon.ico").read_bytes())
    except Exception:
        log.warning("Cacer browser branding could not be applied; retry on next launch",
                    exc_info=True)
