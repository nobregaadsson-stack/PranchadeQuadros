"""Formatação e interpretação de marcas de tempo.

As marcas são TRUNCADAS (nunca arredondadas para cima): um quadro exibido em
10,967 s aparece como 00:00:10, assim como em um reprodutor de vídeo. Desse modo a
legenda nunca indica um instante posterior ao real.
"""

from __future__ import annotations

import math
import re


class TimeParseError(ValueError):
    pass


def format_time(seconds: float | None, with_ms: bool = False) -> str:
    if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)):
        return "indisponível"
    negative = seconds < 0
    # Pequena tolerância para erros de ponto flutuante (ex.: 9.9999999999 -> 10.000)
    total_ms = int(math.floor(abs(seconds) * 1000 + 1e-6))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    text = f"{h:02d}:{m:02d}:{s:02d}"
    if with_ms:
        text += f".{ms:03d}"
    return ("-" if negative else "") + text


def format_seconds(seconds: float | None, decimals: int = 3) -> str:
    """Segundos com casas decimais fixas e vírgula decimal (padrão brasileiro)."""
    if seconds is None:
        return "indisponível"
    return f"{seconds:.{decimals}f}".replace(".", ",")


def format_duration_human(seconds: float | None) -> str:
    if seconds is None:
        return "indisponível"
    return f"{format_time(seconds, with_ms=True)} ({format_seconds(seconds)} s)"


_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:[.,]\d+)?)\s*$")


def parse_time(text: str) -> float:
    """Aceita 'HH:MM:SS', 'HH:MM:SS.mmm', 'MM:SS', 'SS' e 'SS,s'."""
    if text is None:
        raise TimeParseError("Tempo não informado.")
    m = _TIME_RE.match(str(text))
    if not m:
        raise TimeParseError(
            f"Tempo inválido: “{text}”. Use o formato HH:MM:SS (ex.: 00:01:30) ou segundos."
        )
    a, b, c = m.groups()
    sec = float(c.replace(",", "."))
    if a is not None and b is not None:
        h, mnt = int(a), int(b)
    elif a is not None:
        h, mnt = 0, int(a)
    else:
        h, mnt = 0, 0
    if (a is not None) and sec >= 60:
        raise TimeParseError(f"Segundos devem ser menores que 60 em “{text}”.")
    if a is not None and b is not None and mnt >= 60:
        raise TimeParseError(f"Minutos devem ser menores que 60 em “{text}”.")
    return h * 3600 + mnt * 60 + sec
