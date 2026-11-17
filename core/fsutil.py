"""Small filesystem helpers shared by the CLI, identity and proxy modules."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write a file in one atomic replace.

    The GUI runs commands in parallel with its polling loop, so a plain
    write_text can be observed half-written (`list` would then fail to parse
    the identity). A sibling temp file plus os.replace avoids that window.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
