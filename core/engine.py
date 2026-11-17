"""Resolve the packaged engine or the writable runtime prepared by the GUI."""

import os
from pathlib import Path
from typing import Optional


def bundled_executable() -> Optional[Path]:
    custom = os.environ.get("CACER_ENGINE_DIR")
    if custom:
        executable = Path(custom) / "camoufox.exe"
        if not executable.is_file():
            raise FileNotFoundError(f"Prepared engine missing: {executable}")
        return executable
    executable = Path(__file__).resolve().parent.parent / "runtime" / "camoufox" / "camoufox.exe"
    return executable if executable.is_file() else None


def get_path(name: str) -> str:
    executable = bundled_executable()
    if executable is not None:
        return str(executable.parent / name)

    from camoufox.pkgman import get_path as installed_path
    return installed_path(name)
