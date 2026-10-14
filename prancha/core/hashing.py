"""Cálculo local de SHA-256 (somente leitura do arquivo)."""

from __future__ import annotations

import hashlib
import os
from typing import Callable

CHUNK = 4 * 1024 * 1024


class Cancelled(Exception):
    pass


def sha256_file(
    path: str,
    progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> str:
    total = os.path.getsize(path)
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as fh:  # somente leitura
        while True:
            if is_cancelled and is_cancelled():
                raise Cancelled()
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
            done += len(block)
            if progress:
                progress(done, total)
    return h.hexdigest()
