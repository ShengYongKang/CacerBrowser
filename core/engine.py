"""Resolve the engine shipped alongside the packaged backend."""

from pathlib import Path
from typing import Optional


def bundled_executable() -> Optional[Path]:
    executable = Path(__file__).resolve().parent.parent / "runtime" / "camoufox" / "camoufox.exe"
    return executable if executable.is_file() else None


def get_path(name: str) -> str:
    executable = bundled_executable()
    if executable is not None:
        return str(executable.parent / name)

    from camoufox.pkgman import get_path as installed_path
    return installed_path(name)
