"""Pasta temporária local para os quadros extraídos, removida ao encerrar."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

_dirs: list[str] = []


def new_session_dir() -> str:
    d = tempfile.mkdtemp(prefix="prancha_quadros_")
    _dirs.append(d)
    return d


def cleanup_all() -> None:
    while _dirs:
        d = _dirs.pop()
        shutil.rmtree(d, ignore_errors=True)


def remove_file(path: str) -> None:
    try:
        if any(os.path.commonpath([path, d]) == d for d in _dirs):
            os.remove(path)
    except (OSError, ValueError):
        pass


atexit.register(cleanup_all)
