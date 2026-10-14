"""Localização de fontes TrueType locais (sem download)."""

from __future__ import annotations

import os
import sys
from functools import lru_cache

from PIL import ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))


def _candidates(bold: bool) -> list[str]:
    bundled = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(_HERE)), "assets", "fonts")
    names_regular = ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "segoeui.ttf", "LiberationSans-Regular.ttf",
                     "Helvetica.ttc", "Arial Unicode.ttf"]
    names_bold = ["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "segoeuib.ttf",
                  "LiberationSans-Bold.ttf", "Helvetica.ttc"]
    names = names_bold if bold else names_regular
    dirs = [bundled]
    windir = os.environ.get("WINDIR", r"C:\Windows")
    dirs.append(os.path.join(windir, "Fonts"))
    dirs += ["/System/Library/Fonts/Supplemental", "/System/Library/Fonts", "/Library/Fonts",
             "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
             "/usr/share/fonts/TTF"]
    return [os.path.join(d, n) for d in dirs for n in names]


@lru_cache(maxsize=None)
def font_path(bold: bool = False) -> str | None:
    for p in _candidates(bold):
        if os.path.isfile(p):
            return p
    if bold:
        return font_path(False)
    return None


@lru_cache(maxsize=256)
def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    size = max(4, int(size))
    p = font_path(bold)
    if p:
        return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)
