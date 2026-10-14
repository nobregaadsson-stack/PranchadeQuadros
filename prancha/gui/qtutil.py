from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QImage


def pil_to_qimage(img: Image.Image) -> QImage:
    if img.mode != "RGB":
        img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    return qimg.copy()  # desvincula do buffer Python


def qimage_to_pil(qimg: QImage) -> Image.Image:
    q = qimg.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = q.width(), q.height(), q.bytesPerLine()
    buf = bytes(q.constBits())[: bpl * h]
    return Image.frombuffer("RGB", (w, h), buf, "raw", "RGB", bpl, 1).copy()
