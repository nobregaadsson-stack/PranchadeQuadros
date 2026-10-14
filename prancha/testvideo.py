"""Gerador de vídeos sintéticos para testes e autoteste.

Cada quadro traz seu próprio número codificado em blocos preto/branco (16 bits), o que
permite verificar, após a extração, exatamente qual quadro foi obtido.
"""

from __future__ import annotations

from fractions import Fraction

import av
from PIL import Image, ImageDraw

BITS = 16
BLOCK = 16


def make_frame_image(index: int, width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height), ((index * 7) % 200 + 30, 90, 160))
    d = ImageDraw.Draw(img)
    y0 = height // 2 - BLOCK // 2
    x0 = (width - BITS * BLOCK) // 2
    for b in range(BITS):
        on = (index >> (BITS - 1 - b)) & 1
        d.rectangle((x0 + b * BLOCK, y0, x0 + (b + 1) * BLOCK - 1, y0 + BLOCK - 1),
                    fill=(255, 255, 255) if on else (0, 0, 0))
    d.text((8, 8), f"#{index}", fill=(255, 255, 0))
    return img


def read_frame_index(img: Image.Image) -> int:
    img = img.convert("L")
    width, height = img.size
    y = height // 2
    x0 = (width - BITS * BLOCK) // 2
    v = 0
    for b in range(BITS):
        px = img.getpixel((x0 + b * BLOCK + BLOCK // 2, y))
        v = (v << 1) | (1 if px > 128 else 0)
    return v


def make_video(path: str, seconds: float = 12, fps: int = 25, width: int = 320, height: int = 240,
               codec: str = "libx264", gop: int = 50, pix_fmt: str = "yuv420p",
               rotation: int | None = None) -> int:
    n = int(round(seconds * fps))
    with av.open(path, "w") as c:
        s = c.add_stream(codec, rate=Fraction(fps))
        s.width, s.height = width, height
        s.pix_fmt = pix_fmt
        try:
            s.codec_context.gop_size = gop
        except Exception:
            pass
        if codec == "libx264":
            s.codec_context.options = {"crf": "18", "preset": "veryfast", "bf": "2"}
        for i in range(n):
            f = av.VideoFrame.from_image(make_frame_image(i, width, height))
            f.pts = i
            f.time_base = Fraction(1, fps)
            for p in s.encode(f):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    return n
