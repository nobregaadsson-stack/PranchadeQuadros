"""Exportação da prancha (PNG/JPEG/PDF) e dos quadros individuais.

Toda gravação é feita em arquivo temporário na pasta de destino e depois renomeada,
para nunca deixar arquivo parcial. É recusada a gravação sobre o vídeo de origem.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from PIL import Image, PngImagePlugin

from .. import APP_NAME, APP_VERSION
from .extraction import FrameRecord, load_display_image
from .hashing import sha256_file
from .layout import JPEG_MAX_SIDE
from .probe import VideoError

DESCRIPTION = ("Composição de quadros extraídos de arquivo de vídeo. Não constitui reprodução integral do "
               "vídeo nem certificação de autenticidade.")


def _same_file(a: str, b: str) -> bool:
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def check_destination(path: str, protected: list[str]) -> None:
    for p in protected:
        if p and _same_file(path, p):
            raise VideoError("O destino escolhido é o próprio arquivo de vídeo original. "
                             "Escolha outro nome: o original nunca é sobrescrito.")
    folder = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(folder):
        raise VideoError(f"A pasta de destino não existe: {folder}")


def _atomic_save(path: str, saver) -> None:
    folder = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".~prancha_", suffix=os.path.splitext(path)[1], dir=folder)
    os.close(fd)
    try:
        saver(tmp)
        os.replace(tmp, path)
    except PermissionError as e:
        _silent_remove(tmp)
        raise VideoError("Sem permissão para gravar no destino (o arquivo pode estar aberto em outro programa).",
                         str(e)) from e
    except OSError as e:
        _silent_remove(tmp)
        raise VideoError("Falha ao gravar o arquivo (disco cheio ou destino indisponível?).", str(e)) from e
    except BaseException:
        _silent_remove(tmp)
        raise


def _silent_remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


@dataclass
class ExportedFile:
    path: str
    sha256: str | None
    width: int
    height: int


def save_image(img: Image.Image, path: str, fmt: str, *, dpi: int = 300, jpeg_quality: int = 95,
               protected: list[str] | None = None, compute_hash: bool = True,
               description: str = DESCRIPTION) -> ExportedFile:
    fmt = fmt.upper()
    check_destination(path, protected or [])
    if fmt == "JPEG" and max(img.size) > JPEG_MAX_SIDE:
        raise VideoError("A imagem excede o limite de 65.500 px do formato JPEG. Use PNG ou reduza a prancha.")

    def saver(tmp):
        if fmt == "PNG":
            info = PngImagePlugin.PngInfo()
            info.add_text("Software", f"{APP_NAME} {APP_VERSION}")
            info.add_itxt("Description", description)
            img.save(tmp, format="PNG", pnginfo=info, dpi=(dpi, dpi), compress_level=6)
        elif fmt == "JPEG":
            img.save(tmp, format="JPEG", quality=int(jpeg_quality), subsampling=0, optimize=True,
                     dpi=(dpi, dpi), comment=description.encode("utf-8"))
        elif fmt == "PDF":
            img.save(tmp, format="PDF", resolution=float(dpi), title="Prancha de quadros de vídeo",
                     author="", subject=description, creator=f"{APP_NAME} {APP_VERSION}")
        else:
            raise VideoError(f"Formato não suportado: {fmt}")

    _atomic_save(path, saver)
    return ExportedFile(path, sha256_file(path) if compute_hash else None, img.width, img.height)


def export_frames(records: list[FrameRecord], folder: str, base_name: str, *, apply_geometry: bool,
                  protected: list[str] | None = None, progress=None, is_cancelled=None,
                  number_width: int = 2) -> list[tuple[int, FrameRecord, ExportedFile]]:
    """Grava cada quadro (PNG sem perdas) com o número usado na prancha."""
    os.makedirs(folder, exist_ok=True)
    out = []
    for i, rec in enumerate(records):
        if is_cancelled and is_cancelled():
            break
        n = str(i + 1).zfill(number_width)
        path = os.path.join(folder, f"{base_name}_quadro_{n}.png")
        check_destination(path, protected or [])
        if apply_geometry and (rec.rotation % 360 or (rec.sar and rec.sar != 1)):
            img = load_display_image(rec, True)
        else:
            img = None  # cópia exata do PNG extraído (pixels decodificados)
        if img is None:
            with Image.open(rec.image_path) as im:
                img = im.convert("RGB")
        ef = save_image(img, path, "PNG", protected=protected,
                        description=f"Quadro {n} extraído de arquivo de vídeo pelo {APP_NAME}.")
        out.append((i + 1, rec, ef))
        if progress:
            progress(i + 1, len(records))
    return out
