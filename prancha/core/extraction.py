"""Planejamento e extração de quadros.

Regra temporal adotada (documentada no registro técnico):

* O **tempo solicitado** é um instante da linha do tempo do vídeo.
* O **quadro obtido** é o quadro que está em exibição nesse instante, isto é, o último
  quadro cuja marca de tempo (PTS) é menor ou igual ao tempo solicitado — o mesmo
  comportamento de um reprodutor pausado nesse ponto.
* O **tempo efetivo** é a marca de tempo (PTS) desse quadro convertida em segundos e
  medida a partir do início do arquivo. Ela pode ser um pouco anterior ao tempo
  solicitado (no máximo a duração de um quadro).
* Se o quadro em exibição começar antes do início do trecho escolhido, usa-se o quadro
  seguinte, para que nenhum quadro fique fora do trecho.
"""

from __future__ import annotations

import enum
import math
import os
import uuid
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable

import av
from PIL import Image

from .probe import VideoError, VideoInfo, open_container, time_origin_of
from .timefmt import format_seconds, format_time

EPS = 1e-6
CONTINUE_WINDOW = 4.0  # segundos: até esta distância decodifica adiante em vez de buscar (seek)


class Mode(str, enum.Enum):
    INTERVAL = "intervalo"
    COUNT = "quantidade"
    MANUAL = "manual"


class Distribution(str, enum.Enum):
    ENDPOINTS = "extremos"  # inclui o início e o fim do trecho
    CENTERED = "centros"  # centro de segmentos iguais


@dataclass
class ExtractionRequest:
    mode: Mode
    start: float
    end: float
    interval: float | None = None
    count: int | None = None
    distribution: Distribution = Distribution.ENDPOINTS

    def describe(self) -> str:
        trecho = f"trecho {format_time(self.start, True)} a {format_time(self.end, True)}"
        if self.mode is Mode.INTERVAL:
            return f"Intervalo de tempo: 1 quadro a cada {format_seconds(self.interval)} s; {trecho}"
        if self.mode is Mode.COUNT:
            dist = ("distribuição uniforme incluindo início e fim" if self.distribution is Distribution.ENDPOINTS
                    else "distribuição uniforme no centro de segmentos iguais")
            return f"Quantidade de quadros: {self.count}; {dist}; {trecho}"
        return "Seleção manual"


def validate_range(start: float, end: float, duration: float | None) -> None:
    if start < 0:
        raise VideoError("O tempo inicial não pode ser negativo.")
    if end <= start:
        raise VideoError("O tempo final deve ser maior que o tempo inicial.")
    if duration is not None and start >= duration + EPS:
        raise VideoError(f"O tempo inicial ultrapassa a duração do vídeo ({format_time(duration, True)}).")
    if duration is not None and end > duration + 0.0005:
        raise VideoError(f"O tempo final ultrapassa a duração do vídeo ({format_time(duration, True)}).",
                         hint="Informe um tempo final menor ou igual à duração.")


def plan_times(req: ExtractionRequest, duration: float | None) -> list[float]:
    """Instantes solicitados, sempre dentro de [início, fim]."""
    validate_range(req.start, req.end, duration)
    span = req.end - req.start
    if req.mode is Mode.INTERVAL:
        if not req.interval or req.interval <= 0:
            raise VideoError("O intervalo entre quadros deve ser maior que zero.")
        n = int(math.floor(span / req.interval + EPS)) + 1
        times = [req.start + i * req.interval for i in range(n)]
    elif req.mode is Mode.COUNT:
        if not req.count or req.count < 1:
            raise VideoError("A quantidade de quadros deve ser pelo menos 1.")
        n = req.count
        if req.distribution is Distribution.ENDPOINTS:
            if n == 1:
                times = [req.start]
            else:
                step = span / (n - 1)
                times = [req.start + i * step for i in range(n)]
                times[-1] = req.end
        else:
            step = span / n
            times = [req.start + (i + 0.5) * step for i in range(n)]
    else:
        raise VideoError("Modo manual não usa planejamento automático.")
    return [min(max(t, req.start), req.end) for t in times]


# --------------------------------------------------------------------------------------
@dataclass
class FrameRecord:
    image_path: str  # PNG sem perdas com os pixels decodificados (sem correção de exibição)
    width: int
    height: int
    requested_time: float | None
    effective_time: float | None
    pts: int | None
    time_base: Fraction | None
    time_source: str  # "PTS", "DTS" ou "estimado"
    origin: Mode
    criterion: str
    rotation: int = 0
    sar: Fraction | None = None
    key_frame: bool | None = None
    pict_type: str | None = None
    color_conversion: str = ""
    caption_override: str | None = None
    note: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    thumb: Image.Image | None = field(default=None, repr=False, compare=False)

    @property
    def time_estimated(self) -> bool:
        return self.time_source == "estimado"

    @property
    def offset(self) -> float | None:
        if self.requested_time is None or self.effective_time is None:
            return None
        return self.effective_time - self.requested_time

    def display_size(self, apply_geometry: bool = True) -> tuple[int, int]:
        w, h = self.width, self.height
        if not apply_geometry:
            return w, h
        if self.sar and self.sar != 1:
            w = int(round(w * float(self.sar)))
        if self.rotation % 180 != 0:
            w, h = h, w
        return w, h


def clockwise_degrees(rotation: int) -> int:
    """Converte a rotação da matriz de exibição (anti-horária) no giro horário a aplicar."""
    return (-int(rotation)) % 360


def apply_display_geometry(img: Image.Image, rotation: int, sar: Fraction | None) -> Image.Image:
    """Corrige proporção de pixel (anamórfico) e orientação, como um reprodutor faria."""
    if sar and sar != 1:
        w = int(round(img.width * float(sar)))
        img = img.resize((max(1, w), img.height), Image.Resampling.LANCZOS)
    cw = clockwise_degrees(rotation)
    if cw == 90:
        img = img.transpose(Image.Transpose.ROTATE_270)
    elif cw == 180:
        img = img.transpose(Image.Transpose.ROTATE_180)
    elif cw == 270:
        img = img.transpose(Image.Transpose.ROTATE_90)
    return img


def load_display_image(rec: FrameRecord, apply_geometry: bool = True) -> Image.Image:
    with Image.open(rec.image_path) as im:
        img = im.convert("RGB")
    if apply_geometry:
        img = apply_display_geometry(img, rec.rotation, rec.sar)
    return img


THUMB_SIZE = 220


def make_thumb(img: Image.Image, rotation: int, sar: Fraction | None) -> Image.Image:
    t = img.copy()
    t.thumbnail((THUMB_SIZE * 2, THUMB_SIZE * 2), Image.Resampling.BILINEAR)
    t = apply_display_geometry(t, rotation, sar)
    t.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
    return t


_PICT = {1: "I", 2: "P", 3: "B", 4: "S", 5: "SI", 6: "SP", 7: "BI"}


def frame_to_image(frame: av.VideoFrame) -> tuple[Image.Image, str]:
    """Converte para RGB sem redimensionar. Retorna a imagem e a descrição da conversão."""
    kwargs = {}
    cs = int(frame.colorspace or 2)
    desc_cs = None
    # 1 = BT.709, 5/6 = BT.601, 9/10 = BT.2020, 2 = não especificado
    if cs == 2:
        # Mesmo critério dos reprodutores: HD ou maior -> BT.709; SD -> BT.601
        if frame.height >= 720:
            kwargs["src_colorspace"] = "itu709"
            desc_cs = "BT.709 (presumido: não informado no arquivo, resolução HD)"
        else:
            kwargs["src_colorspace"] = "itu601"
            desc_cs = "BT.601 (presumido: não informado no arquivo, resolução SD)"
    else:
        names = {1: "BT.709", 5: "BT.601", 6: "BT.601", 9: "BT.2020", 10: "BT.2020", 7: "SMPTE 240M", 4: "FCC"}
        desc_cs = f"{names.get(cs, f'código {cs}')} (informado no arquivo)"
    rng = int(frame.color_range or 0)
    if rng in (1, 2):
        kwargs["src_color_range"] = rng
    fmt = frame.format.name if frame.format else "?"
    if fmt.startswith(("rgb", "bgr", "gbr", "argb", "abgr", "rgba", "bgra", "gray", "pal8")):
        desc = f"{fmt} → RGB (sem conversão de matriz de cor)"
        kwargs = {}
    else:
        desc = f"{fmt} → RGB, matriz {desc_cs}"
    try:
        img = frame.to_image(**kwargs)
    except Exception:
        img = frame.to_image()
        desc = f"{fmt} → RGB (conversão padrão do FFmpeg)"
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img, desc


# --------------------------------------------------------------------------------------
@dataclass
class Grabbed:
    frame: av.VideoFrame
    time: float | None
    pts: int | None
    source: str


class FrameGrabber:
    """Obtém o quadro exibido em um dado instante, com busca (seek) e decodificação adiante."""

    def __init__(self, info: VideoInfo):
        self.info = info
        self.container = open_container(info.path)
        self.stream = self.container.streams.video[0]
        self.stream.thread_type = "AUTO"
        self.tb = Fraction(self.stream.time_base)
        self.origin = time_origin_of(self.container, self.stream)
        self.decode_errors = 0
        self._gen = None
        self._last: Grabbed | None = None
        self._pending: Grabbed | None = None
        self._seq_index = 0
        self._sequential = info.first_frame_time is None  # sem PTS -> contagem de quadros
        self._from_start = False
        self._eof = False

    def close(self):
        try:
            self.container.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # -- decodificação ---------------------------------------------------------------
    def _frames(self):
        for packet in self.container.demux(self.stream):
            try:
                frames = packet.decode()
            except av.error.InvalidDataError:
                self.decode_errors += 1
                continue
            except av.error.FFmpegError:
                self.decode_errors += 1
                continue
            for f in frames:
                yield f

    def _wrap(self, f: av.VideoFrame) -> Grabbed:
        if self._sequential:
            fps = self.info.fps or 0
            t = self._seq_index / fps if fps else None
            self._seq_index += 1
            return Grabbed(f, t, None, "estimado")
        if f.pts is not None:
            return Grabbed(f, float(f.pts * self.tb) - self.origin, f.pts, "PTS")
        if f.dts is not None:
            return Grabbed(f, float(f.dts * self.tb) - self.origin, f.dts, "DTS")
        return Grabbed(f, None, None, "estimado")

    def _next(self) -> Grabbed | None:
        if self._pending is not None:
            g, self._pending = self._pending, None
            return g
        if self._eof:
            return None
        try:
            f = next(self._gen)
        except StopIteration:
            self._eof = True
            return None
        except av.error.FFmpegError:
            self.decode_errors += 1
            self._eof = True
            return None
        return self._wrap(f)

    def _seek(self, t: float, from_start: bool = False):
        self._last = None
        self._pending = None
        self._eof = False
        self._from_start = from_start or self._sequential
        if self._sequential or from_start:
            # Volta ao início físico do arquivo (independe da origem das marcas de tempo)
            try:
                self.container.seek(-(1 << 40), backward=True, any_frame=False)
            except av.error.FFmpegError:
                self.container.seek(0)
            self._seq_index = 0
        else:
            target = int(math.floor((t + self.origin) / self.tb))
            try:
                self.container.seek(max(target, 0) if self.origin >= 0 else target,
                                    stream=self.stream, backward=True, any_frame=False)
            except av.error.FFmpegError:
                self.container.seek(0)
        self._gen = self._frames()

    def grab(self, t: float, min_time: float | None = None) -> Grabbed:
        """Quadro em exibição no instante ``t`` (segundos na linha do tempo do arquivo)."""
        need_seek = True
        if self._gen is not None and self._last is not None and self._last.time is not None:
            ahead = t - self._last.time
            if ahead >= -EPS and (ahead <= CONTINUE_WINDOW or self._sequential):
                need_seek = False
        if need_seek:
            self._seek(t)

        result = self._scan(t)
        back_off = 1.0
        while result == "overshoot":
            # A busca posicionou depois do instante desejado: recua e tenta novamente.
            if self._sequential or t - back_off <= 0 or back_off > 600:
                self._seek(0, from_start=True)
                result = self._scan(t)
                if result == "overshoot":  # t é anterior ao primeiro quadro decodificável
                    result = self._pending_or_raise(t)
                break
            self._seek(t - back_off)
            result = self._scan(t)
            back_off *= 4
        g: Grabbed = result
        if min_time is not None and g.time is not None and g.time < min_time - EPS:
            nxt = self._next()
            if nxt is not None:
                self._last = nxt
                g = nxt
        return g

    def next_after(self, t: float) -> Grabbed:
        """Quadro imediatamente seguinte ao quadro exibido em ``t`` (passo exato, inclusive em taxa variável)."""
        cur = self.grab(t)
        nxt = self._next()
        if nxt is None:
            return cur
        self._last = nxt
        return nxt

    def _pending_or_raise(self, t):
        if self._pending is not None:
            g = self._pending
            self._pending = None
            self._last = g
            return g
        raise VideoError(f"Não foi possível obter um quadro em {format_time(t, True)}.")

    def _scan(self, t: float):
        while True:
            g = self._next()
            if g is None:  # fim do arquivo: último quadro decodificado
                if self._last is not None:
                    return self._last
                if not self._from_start:
                    return "overshoot"  # a busca caiu além do último quadro
                raise VideoError(
                    f"Não há quadro decodificável em {format_time(t, True)} (fim do arquivo ou dados corrompidos)."
                )
            if g.time is None:
                self._last = g
                continue
            if g.time <= t + EPS:
                self._last = g
                continue
            # g está depois de t
            self._pending = g
            if self._last is None:
                if g.time is not None and self.info.first_frame_time is not None and \
                        g.time <= self.info.first_frame_time + EPS:
                    # t é anterior ao primeiro quadro do arquivo
                    self._pending = None
                    self._last = g
                    return g
                return "overshoot"
            return self._last


# --------------------------------------------------------------------------------------
@dataclass
class ExtractionResult:
    records: list[FrameRecord]
    errors: list[str]
    merged: list[tuple[float, float]]  # (tempo solicitado, tempo efetivo) unificados com quadro já obtido
    cancelled: bool = False
    decode_errors: int = 0


def save_frame_png(img: Image.Image, folder: str) -> str:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"q_{uuid.uuid4().hex}.png")
    img.save(path, format="PNG", compress_level=1)
    return path


def extract_frames(
    info: VideoInfo,
    times: list[float],
    out_dir: str,
    origin: Mode,
    criterion: str,
    range_start: float | None = None,
    range_end: float | None = None,
    progress: Callable[[int, int, FrameRecord | None], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> ExtractionResult:
    records: list[FrameRecord] = []
    errors: list[str] = []
    merged: list[tuple[float, float]] = []
    seen: dict[tuple, FrameRecord] = {}
    total = len(times)
    cancelled = False
    order = sorted(range(total), key=lambda i: times[i])
    grabber = FrameGrabber(info)
    try:
        for done, i in enumerate(order, start=1):
            if is_cancelled and is_cancelled():
                cancelled = True
                break
            t = times[i]
            rec = None
            try:
                g = grabber.grab(t, min_time=range_start)
                if g.time is not None and range_end is not None and g.time > range_end + EPS:
                    errors.append(f"Nenhum quadro do vídeo cai dentro do trecho em {format_time(t, True)}.")
                elif g.time is not None and range_start is not None and g.time < range_start - EPS:
                    errors.append(f"Nenhum quadro do vídeo cai dentro do trecho em {format_time(t, True)}.")
                else:
                    key = (g.pts, g.source) if g.pts is not None else (round(g.time or -1, 6), g.source)
                    if key in seen:
                        merged.append((t, seen[key].effective_time))
                    else:
                        img, conv = frame_to_image(g.frame)
                        path = save_frame_png(img, out_dir)
                        sar = info.sar
                        rotation = info.rotation
                        try:
                            rotation = int(round(g.frame.rotation or 0))
                        except Exception:
                            pass
                        rec = FrameRecord(
                            image_path=path, width=img.width, height=img.height,
                            requested_time=t, effective_time=g.time, pts=g.pts,
                            time_base=grabber.tb if g.pts is not None else None,
                            time_source=g.source, origin=origin, criterion=criterion,
                            rotation=rotation, sar=sar,
                            key_frame=bool(g.frame.key_frame),
                            pict_type=_PICT.get(int(g.frame.pict_type or 0)),
                            color_conversion=conv,
                        )
                        rec.thumb = make_thumb(img, rotation, sar)
                        if g.frame.is_corrupt:
                            rec.note = "O decodificador marcou este quadro como possivelmente corrompido."
                        seen[key] = rec
                        records.append(rec)
            except VideoError as e:
                errors.append(f"{format_time(t, True)}: {e}")
            except av.error.FFmpegError as e:
                errors.append(f"{format_time(t, True)}: erro de decodificação ({e}).")
            except OSError as e:
                errors.append(f"{format_time(t, True)}: erro ao gravar arquivo temporário ({e}).")
            if progress:
                progress(done, total, rec)
    finally:
        decode_errors = grabber.decode_errors
        grabber.close()
    records.sort(key=lambda r: (r.effective_time if r.effective_time is not None else math.inf))
    return ExtractionResult(records, errors, merged, cancelled, decode_errors)


def grab_single(info: VideoInfo, t: float, out_dir: str, criterion: str = "Seleção manual") -> FrameRecord:
    res = extract_frames(info, [t], out_dir, Mode.MANUAL, criterion)
    if not res.records:
        raise VideoError(res.errors[0] if res.errors else f"Não foi possível capturar o quadro em {format_time(t, True)}.")
    return res.records[0]
