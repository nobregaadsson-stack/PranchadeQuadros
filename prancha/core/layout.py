"""Montagem da prancha: cálculo do layout e renderização determinística com Pillow.

A prévia e a exportação usam exatamente a mesma função ``render_plate`` com os mesmos
parâmetros, de modo que o arquivo exportado é idêntico, pixel a pixel, à prévia.

Elementos gráficos acrescentados (bordas, legendas, cabeçalho, nota) ficam sempre FORA
da área do quadro extraído, exceto quando o usuário escolhe explicitamente a legenda
sobreposta. As bordas são desenhadas ao redor da imagem, nunca sobre ela.
"""

from __future__ import annotations

import copy
import math
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Callable

from PIL import Image, ImageColor, ImageDraw

from .extraction import FrameRecord, load_display_image
from .fonts import get_font
from .timefmt import format_time

DEFAULT_CAPTION = "QUADRO {n} — TEMPO: {tempo}"
DEFAULT_FOOTER = ("Composição de quadros extraídos do arquivo de vídeo identificado. "
                  "Não constitui reprodução integral do vídeo nem certificação de autenticidade. "
                  "Bordas, legendas e textos foram acrescentados pelo aplicativo.")

MAX_PIXELS = 400_000_000  # limite de segurança de memória (~1,2 GB em RGB)
WARN_PIXELS = 80_000_000
JPEG_MAX_SIDE = 65_500

PAGE_PRESETS = {
    "A4 — 300 dpi": (2480, 3508),
    "A4 — 150 dpi": (1240, 1754),
    "Carta — 300 dpi": (2550, 3300),
    "Full HD (1920 × 1080)": (1080, 1920),
    "4K UHD (3840 × 2160)": (2160, 3840),
}  # armazenados em retrato (largura <= altura); a orientação define a troca

ASPECTS = {
    "16:9": 16 / 9,
    "4:3": 4 / 3,
    "3:2": 3 / 2,
    "1:1": 1.0,
    "9:16": 9 / 16,
    "3:4": 3 / 4,
}


@dataclass
class HeaderField:
    key: str
    label: str
    value: str = ""
    show: bool = True


def default_header_fields() -> list[HeaderField]:
    return [
        HeaderField("video_id", "Identificação do vídeo"),
        HeaderField("file_name", "Arquivo original"),
        HeaderField("analysis_dt", "Data e hora da análise"),
        HeaderField("procedure", "Procedimento / relatório / ocorrência"),
        HeaderField("analyst", "Responsável pela análise"),
        HeaderField("time_range", "Intervalo temporal analisado"),
        HeaderField("notes", "Observações"),
    ]


@dataclass
class PlateSettings:
    template: str = "Técnico simples"
    # grade
    grid_by: str = "columns"  # "columns": colunas fixas e linhas automáticas; "rows": linhas fixas
    columns: int = 3
    rows: int = 2
    # tamanho
    size_mode: str = "auto"  # "auto" (pela largura do quadro) | "fixed" (dimensões da imagem final)
    frame_width: int = 640
    canvas_width: int = 2480
    canvas_height: int = 3508
    orientation: str = "portrait"  # portrait | landscape (aplicado em size_mode == fixed)
    fit_mode: str = "original"  # "original": proporções do quadro | "box": área padronizada com margens
    box_aspect: float = 16 / 9
    # espaçamentos (px)
    spacing: int = 24
    row_spacing: int = 28
    margin: int = 48
    caption_gap: int = 8
    # textos
    caption_font_size: int = 20
    title_font_size: int = 32
    header_font_size: int = 18
    footer_font_size: int = 14
    caption_template: str = DEFAULT_CAPTION
    show_ms: bool = False
    caption_position: str = "below"  # below | above | overlay | none
    caption_bold: bool = True
    # cores
    background: str = "#FFFFFF"
    text_color: str = "#111111"
    box_color: str = "#E6E6E6"
    border_width: int = 1
    border_color: str = "#7F7F7F"
    # alinhamento
    h_align: str = "center"  # left | center | right (imagem e legenda dentro da célula)
    v_align: str = "center"  # top | center | bottom (imagem dentro da linha)
    last_row_align: str = "left"  # left | center
    # cabeçalho / rodapé
    header_enabled: bool = False
    title: str = "PRANCHA DE QUADROS DE VÍDEO"
    show_title: bool = True
    header_fields: list[HeaderField] = field(default_factory=default_header_fields)
    footer_enabled: bool = True
    footer_text: str = DEFAULT_FOOTER
    # geometria de exibição
    apply_geometry: bool = True
    dpi: int = 300

    def copy(self) -> "PlateSettings":
        return copy.deepcopy(self)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "PlateSettings":
        s = PlateSettings()
        for k, v in d.items():
            if k == "header_fields":
                s.header_fields = [HeaderField(**x) for x in v]
            elif hasattr(s, k):
                setattr(s, k, v)
        return s

    def canvas_size(self) -> tuple[int, int]:
        w, h = sorted((int(self.canvas_width), int(self.canvas_height)))
        return (h, w) if self.orientation == "landscape" else (w, h)


def template_settings(name: str, base: PlateSettings | None = None) -> PlateSettings:
    """Modelos predefinidos. Os campos do cabeçalho preenchidos pelo usuário são preservados."""
    s = PlateSettings()
    if base is not None:
        s.header_fields = copy.deepcopy(base.header_fields)
        s.title = base.title
        s.caption_template = base.caption_template
        s.apply_geometry = base.apply_geometry
    s.template = name
    if name == "Técnico simples":
        s.columns, s.frame_width, s.header_enabled = 3, 640, False
        s.border_width, s.border_color, s.spacing, s.margin = 1, "#7F7F7F", 20, 40
    elif name == "Relatório investigativo":
        s.columns, s.frame_width, s.header_enabled = 2, 900, True
        s.margin, s.spacing, s.row_spacing = 80, 32, 36
        s.caption_font_size, s.title_font_size, s.header_font_size = 26, 40, 24
        s.border_width, s.border_color = 2, "#404040"
        s.footer_font_size = 18
    elif name == "Alta densidade":
        s.columns, s.frame_width, s.header_enabled = 6, 400, False
        s.spacing, s.row_spacing, s.margin, s.caption_gap = 10, 12, 24, 4
        s.caption_font_size, s.footer_font_size = 14, 12
        s.caption_template = "Q{n} — {tempo}"
        s.border_width = 1
    return s


TEMPLATES = ["Técnico simples", "Relatório investigativo", "Alta densidade", "Personalizado"]


# --------------------------------------------------------------------------------------
def number_width(total: int) -> int:
    return max(2, len(str(total)))


def caption_for(rec: FrameRecord, index: int, total: int, s: PlateSettings) -> str:
    if rec.caption_override is not None and rec.caption_override.strip():
        return rec.caption_override
    return default_caption(rec, index, total, s)


def default_caption(rec: FrameRecord, index: int, total: int, s: PlateSettings) -> str:
    n = str(index + 1).zfill(number_width(total))
    tempo = format_time(rec.effective_time, with_ms=s.show_ms)
    if rec.time_estimated and rec.effective_time is not None:
        tempo += " (estimado)"
    try:
        return s.caption_template.format(n=n, tempo=tempo, arquivo="", total=total)
    except (KeyError, IndexError, ValueError):
        return DEFAULT_CAPTION.format(n=n, tempo=tempo)


def _wrap(text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            trial = w if not cur else cur + " " + w
            if font.getlength(trial) <= max_w or not cur:
                if font.getlength(trial) > max_w and not cur:
                    # palavra maior que a largura: quebra por caracteres
                    piece = ""
                    for ch in w:
                        if font.getlength(piece + ch) > max_w and piece:
                            lines.append(piece)
                            piece = ch
                        else:
                            piece += ch
                    cur = piece
                else:
                    cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _line_h(font) -> int:
    asc, desc = font.getmetrics()
    return int(math.ceil((asc + desc) * 1.15))


@dataclass
class TextBlock:
    lines: list[str]
    bold: bool
    size: int
    x: int
    y: int
    width: int
    align: str  # left | center | right

    @property
    def height(self) -> int:
        return _line_h(get_font(self.size, self.bold)) * len(self.lines)


@dataclass
class Cell:
    index: int
    record_id: str
    cell_rect: tuple[int, int, int, int]  # x0, y0, x1, y1 (área total, para clique na prévia)
    box_rect: tuple[int, int, int, int] | None  # área padronizada (modo "box")
    image_rect: tuple[int, int, int, int]  # onde a imagem extraída é colada
    caption: TextBlock | None


@dataclass
class PlateLayout:
    width: int
    height: int
    columns: int
    rows: int
    frame_width: int  # largura usada para a área de cada quadro
    cells: list[Cell]
    texts: list[TextBlock]
    separators: list[tuple[int, int, int, int]]
    warnings: list[str]

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1e6


class LayoutError(Exception):
    pass


def grid_shape(n: int, s: PlateSettings) -> tuple[int, int]:
    if n <= 0:
        return 0, 0
    if s.grid_by == "rows":
        rows = max(1, min(int(s.rows), n))
        cols = math.ceil(n / rows)
    else:
        cols = max(1, min(int(s.columns), n))
        rows = math.ceil(n / cols)
    return cols, rows


def _header_texts(s: PlateSettings, width: int) -> list[tuple[str, bool, int, str]]:
    """(texto, negrito, tamanho, alinhamento)"""
    out = []
    if not s.header_enabled:
        return out
    if s.show_title and s.title.strip():
        out.append((s.title.strip(), True, s.title_font_size, "center"))
    for f in s.header_fields:
        if f.show and f.value.strip():
            out.append((f"{f.label}: {f.value.strip()}", False, s.header_font_size, "left"))
    return out


def compute_layout(records: list[FrameRecord], s: PlateSettings) -> PlateLayout:
    n = len(records)
    if n == 0:
        raise LayoutError("Nenhum quadro selecionado para compor a prancha.")
    cols, rows = grid_shape(n, s)
    bw = max(0, int(s.border_width))
    margin = max(0, int(s.margin))
    hsp = max(0, int(s.spacing))
    vsp = max(0, int(s.row_spacing))
    cap_font = get_font(s.caption_font_size, s.caption_bold)
    cap_lh = _line_h(cap_font)
    warnings: list[str] = []

    aspects = []  # altura/largura de exibição
    for r in records:
        w, h = r.display_size(s.apply_geometry)
        aspects.append(h / w if w else 1.0)

    def inv_aspect_for(i: int) -> float:
        return (1 / s.box_aspect) if s.fit_mode == "box" else aspects[i]

    def caption_lines(fw: int) -> list[list[str]]:
        res = []
        for i, r in enumerate(records):
            if s.caption_position == "none":
                res.append([])
            else:
                txt = caption_for(r, i, n, s)
                res.append(_wrap(txt, cap_font, max(20, fw if s.caption_position != "overlay" else fw - 12)))
        return res

    # ---- largura do quadro
    if s.size_mode == "fixed":
        cw, ch = s.canvas_size()
        avail_w = cw - 2 * margin
        if avail_w < 50:
            raise LayoutError("As margens são maiores que a largura da imagem final.")
        head = _measure_header(s, avail_w)
        foot = _measure_footer(s, avail_w)
        avail_h = ch - 2 * margin - head - foot
        # largura máxima pelo eixo horizontal
        fw_w = (avail_w - (cols - 1) * hsp - cols * 2 * bw) / cols
        # pelo eixo vertical: soma das alturas das linhas (estimativa de legenda com 1 linha, refinada abaixo)
        fw = int(math.floor(fw_w))
        for _ in range(6):
            caps = caption_lines(max(fw, 20))
            row_inv, row_cap = _rows_metrics(n, cols, rows, inv_aspect_for, caps, cap_lh, s)
            fixed_v = sum(row_cap) + (rows - 1) * vsp + rows * 2 * bw
            if s.caption_position not in ("none", "overlay"):
                fixed_v += rows * s.caption_gap
            fw_h = (avail_h - fixed_v) / sum(row_inv) if sum(row_inv) > 0 else fw_w
            new_fw = int(math.floor(min(fw_w, fw_h)))
            if new_fw == fw:
                break
            fw = new_fw
        if fw < 40:
            raise LayoutError(
                f"Os {n} quadros não cabem na imagem de {cw} × {ch} px com {cols} colunas "
                f"(cada quadro ficaria com {max(fw, 0)} px de largura). Aumente as dimensões, "
                "reduza margens e espaçamentos, altere o número de colunas ou divida a seleção."
            )
        if fw < 160:
            warnings.append(f"Cada quadro ficará com apenas {fw} px de largura; os detalhes podem ficar ilegíveis.")
        canvas_w, canvas_h = cw, ch
    else:
        fw = max(40, int(s.frame_width))
        canvas_w = None
        canvas_h = None

    caps = caption_lines(fw)
    # ---- geometria das linhas
    content_w = cols * (fw + 2 * bw) + (cols - 1) * hsp
    if canvas_w is None:
        canvas_w = content_w + 2 * margin
    x_start = margin + max(0, ((canvas_w - 2 * margin) - content_w) // 2)

    texts: list[TextBlock] = []
    separators = []
    y = margin
    inner_w = canvas_w - 2 * margin
    # cabeçalho
    for txt, bold, size, align in _header_texts(s, inner_w):
        f = get_font(size, bold)
        tb = TextBlock(_wrap(txt, f, inner_w), bold, size, margin, y, inner_w, align)
        texts.append(tb)
        y += tb.height + (size // 3)
    if texts:
        y += max(6, s.header_font_size // 2)
        separators.append((margin, y, canvas_w - margin, y))
        y += max(12, s.header_font_size)

    cells: list[Cell] = []
    for r in range(rows):
        idxs = list(range(r * cols, min(n, (r + 1) * cols)))
        img_hs = [int(round(fw * inv_aspect_for(i))) for i in idxs]
        box_h = max(img_hs)
        cap_n = max((len(caps[i]) for i in idxs), default=0)
        cap_h = cap_n * cap_lh if s.caption_position in ("below", "above") else 0
        gap = s.caption_gap if cap_h else 0
        row_h = box_h + 2 * bw + gap + cap_h
        row_x = x_start
        if s.last_row_align == "center" and len(idxs) < cols:
            row_x += ((cols - len(idxs)) * (fw + 2 * bw + hsp)) // 2
        for k, i in enumerate(idxs):
            cx0 = row_x + k * (fw + 2 * bw + hsp)
            cell_rect = (cx0, y, cx0 + fw + 2 * bw, y + row_h)
            img_top = y + (cap_h + gap if s.caption_position == "above" else 0) + bw
            # tamanho da imagem dentro da área (fw × box_h ou fw × caixa padronizada)
            dw, dh = records[i].display_size(s.apply_geometry)
            if s.fit_mode == "box":
                bh = int(round(fw / s.box_aspect))
                scale = min(fw / dw, bh / dh)
                iw, ih = max(1, int(round(dw * scale))), max(1, int(round(dh * scale)))
                bx0 = cx0 + bw
                by0 = img_top
                box_rect = (bx0, by0, bx0 + fw, by0 + bh)
                ix = bx0 + {"left": 0, "right": fw - iw}.get(s.h_align, (fw - iw) // 2)
                iy = by0 + {"top": 0, "bottom": bh - ih}.get(s.v_align, (bh - ih) // 2)
            else:
                iw = fw
                ih = max(1, int(round(fw * dh / dw)))
                box_rect = None
                ix = cx0 + bw
                # alinhamento vertical dentro da linha (quando os quadros têm alturas diferentes)
                iy = img_top + {"top": 0, "bottom": box_h - ih}.get(s.v_align, (box_h - ih) // 2)
            image_rect = (ix, iy, ix + iw, iy + ih)
            cap_block = None
            if caps[i]:
                if s.caption_position == "below":
                    cap_y = y + 2 * bw + box_h + gap
                    cap_block = TextBlock(caps[i], s.caption_bold, s.caption_font_size, cx0, cap_y,
                                          fw + 2 * bw, s.h_align)
                elif s.caption_position == "above":
                    cap_block = TextBlock(caps[i], s.caption_bold, s.caption_font_size, cx0, y,
                                          fw + 2 * bw, s.h_align)
                elif s.caption_position == "overlay":
                    h_txt = len(caps[i]) * cap_lh
                    cap_block = TextBlock(caps[i], s.caption_bold, s.caption_font_size, ix + 6,
                                          image_rect[3] - h_txt - 6, iw - 12, s.h_align)
            cells.append(Cell(i, records[i].id, cell_rect, box_rect, image_rect, cap_block))
        y += row_h + (vsp if r < rows - 1 else 0)

    # rodapé
    if s.footer_enabled and s.footer_text.strip():
        y += max(16, s.footer_font_size)
        f = get_font(s.footer_font_size, False)
        tb = TextBlock(_wrap(s.footer_text.strip(), f, inner_w), False, s.footer_font_size, margin, y,
                       inner_w, "left")
        texts.append(tb)
        y += tb.height
    y += margin
    if canvas_h is None:
        canvas_h = y
    elif y > canvas_h + 1:
        raise LayoutError("O conteúdo excede a altura da imagem final. Aumente a altura ou reduza o conteúdo.")

    total_px = canvas_w * canvas_h
    if total_px > MAX_PIXELS:
        raise LayoutError(
            f"A prancha teria {canvas_w} × {canvas_h} px ({total_px / 1e6:.0f} megapixels), acima do limite "
            f"seguro de {MAX_PIXELS / 1e6:.0f} megapixels. Reduza a largura dos quadros, aumente o número de "
            "colunas ou diminua a quantidade de quadros."
        )
    if total_px > WARN_PIXELS:
        warnings.append(f"Prancha muito grande ({total_px / 1e6:.0f} megapixels): a geração e a abertura do "
                        "arquivo podem ser lentas.")
    if max(canvas_w, canvas_h) > JPEG_MAX_SIDE:
        warnings.append("Dimensão acima de 65.500 px: o formato JPEG não poderá ser usado (somente PNG).")
    if s.fit_mode == "original" and len(set(round(a, 3) for a in aspects)) > 1:
        warnings.append("Os quadros têm proporções diferentes; as linhas usam a altura do maior quadro.")
    return PlateLayout(canvas_w, canvas_h, cols, rows, fw, cells, texts, separators, warnings)


def _rows_metrics(n, cols, rows, inv_aspect_for, caps, cap_lh, s):
    row_inv, row_cap = [], []
    for r in range(rows):
        idxs = list(range(r * cols, min(n, (r + 1) * cols)))
        row_inv.append(max(inv_aspect_for(i) for i in idxs))
        if s.caption_position in ("below", "above"):
            row_cap.append(max(len(caps[i]) for i in idxs) * cap_lh)
        else:
            row_cap.append(0)
    return row_inv, row_cap


def _measure_header(s: PlateSettings, inner_w: int) -> int:
    texts = _header_texts(s, inner_w)
    if not texts:
        return 0
    h = 0
    for txt, bold, size, _ in texts:
        f = get_font(size, bold)
        h += len(_wrap(txt, f, inner_w)) * _line_h(f) + size // 3
    h += max(6, s.header_font_size // 2) + max(12, s.header_font_size)
    return h


def _measure_footer(s: PlateSettings, inner_w: int) -> int:
    if not (s.footer_enabled and s.footer_text.strip()):
        return 0
    f = get_font(s.footer_font_size, False)
    return max(16, s.footer_font_size) + len(_wrap(s.footer_text.strip(), f, inner_w)) * _line_h(f)


# --------------------------------------------------------------------------------------
class ImageCache:
    """Cache LRU de imagens de exibição redimensionadas (evita reprocessar a cada ajuste)."""

    def __init__(self, max_items: int = 400):
        self._d: OrderedDict = OrderedDict()
        self.max_items = max_items

    def get(self, rec: FrameRecord, size: tuple[int, int], apply_geometry: bool) -> Image.Image:
        key = (rec.id, rec.image_path, size, apply_geometry)
        img = self._d.get(key)
        if img is not None:
            self._d.move_to_end(key)
            return img
        src = load_display_image(rec, apply_geometry)
        if src.size != size:
            img = src.resize(size, Image.Resampling.LANCZOS)
        else:
            img = src
        self._d[key] = img
        while len(self._d) > self.max_items:
            self._d.popitem(last=False)
        return img

    def clear(self):
        self._d.clear()


_default_cache = ImageCache()


def _rgb(color: str) -> tuple[int, int, int]:
    try:
        return ImageColor.getrgb(color)[:3]
    except ValueError:
        return (255, 255, 255)


def _draw_text(draw: ImageDraw.ImageDraw, tb: TextBlock, color):
    f = get_font(tb.size, tb.bold)
    lh = _line_h(f)
    for k, line in enumerate(tb.lines):
        w = f.getlength(line)
        if tb.align == "center":
            x = tb.x + (tb.width - w) / 2
        elif tb.align == "right":
            x = tb.x + tb.width - w
        else:
            x = tb.x
        draw.text((round(x), tb.y + k * lh), line, font=f, fill=color)


def render_plate(
    records: list[FrameRecord],
    s: PlateSettings,
    layout: PlateLayout | None = None,
    cache: ImageCache | None = None,
    progress: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[Image.Image, PlateLayout]:
    layout = layout or compute_layout(records, s)
    cache = cache or _default_cache
    canvas = Image.new("RGB", (layout.width, layout.height), _rgb(s.background))
    draw = ImageDraw.Draw(canvas)
    text_rgb = _rgb(s.text_color)
    for tb in layout.texts:
        _draw_text(draw, tb, text_rgb)
    for x0, y0, x1, y1 in layout.separators:
        draw.line((x0, y0, x1, y0), fill=_rgb(s.border_color), width=max(1, s.border_width))
    bw = max(0, int(s.border_width))
    total = len(layout.cells)
    for k, cell in enumerate(layout.cells):
        if is_cancelled and is_cancelled():
            raise InterruptedError()
        rec = records[cell.index]
        if cell.box_rect:
            draw.rectangle((cell.box_rect[0], cell.box_rect[1], cell.box_rect[2] - 1, cell.box_rect[3] - 1),
                           fill=_rgb(s.box_color))
        x0, y0, x1, y1 = cell.image_rect
        img = cache.get(rec, (x1 - x0, y1 - y0), s.apply_geometry)
        canvas.paste(img, (x0, y0))
        if bw:
            # borda externa: não cobre nenhum pixel do quadro extraído
            draw.rectangle((x0 - bw, y0 - bw, x1 - 1 + bw, y1 - 1 + bw), outline=_rgb(s.border_color), width=bw)
            canvas.paste(img, (x0, y0))  # garante integridade da área do quadro
        if cell.caption:
            if s.caption_position == "overlay":
                f = get_font(cell.caption.size, cell.caption.bold)
                h = cell.caption.height
                overlay = Image.new("RGBA", (x1 - x0, h + 12), (0, 0, 0, 150))
                canvas.paste(overlay, (x0, y1 - h - 12), overlay)
                _draw_text(draw, cell.caption, (255, 255, 255))
            else:
                _draw_text(draw, cell.caption, text_rgb)
        if progress:
            progress(k + 1, total)
    return canvas, layout
