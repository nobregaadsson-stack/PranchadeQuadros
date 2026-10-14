"""Leitura das informações técnicas do vídeo (equivalente ao FFprobe, via bibliotecas FFmpeg do PyAV).

O arquivo é aberto exclusivamente para leitura. Nenhum valor é estimado: o que não
puder ser obtido fica como ``None`` e é exibido como “indisponível”.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass, field
from fractions import Fraction

import av

VIDEO_EXTENSIONS = (
    ".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".asf", ".flv", ".mpg",
    ".mpeg", ".m2ts", ".mts", ".ts", ".3gp", ".3g2", ".ogv", ".vob", ".dav", ".h264",
    ".h265", ".hevc", ".mjpeg", ".mxf", ".dv", ".f4v", ".rm", ".rmvb",
)


class VideoError(Exception):
    """Erro com mensagem em português destinada ao usuário (``str(e)``) e detalhe técnico."""

    def __init__(self, message: str, technical: str = "", hint: str = ""):
        super().__init__(message)
        self.technical = technical
        self.hint = hint

    def full_text(self) -> str:
        parts = [str(self)]
        if self.hint:
            parts.append(f"Como resolver: {self.hint}")
        if self.technical:
            parts.append(f"Detalhe técnico: {self.technical}")
        return "\n\n".join(parts)


@dataclass
class VideoInfo:
    path: str
    file_name: str
    file_size: int
    created: _dt.datetime | None
    modified: _dt.datetime | None
    format_name: str | None
    format_long_name: str | None
    duration: float | None
    duration_source: str
    width: int | None
    height: int | None
    fps: float | None
    fps_text: str | None
    fps_source: str
    codec: str | None
    codec_long: str | None
    pix_fmt: str | None
    sar: Fraction | None
    rotation: int  # graus anti-horários da matriz de exibição (0 se ausente)
    stream_index: int
    time_base: Fraction
    time_origin: float  # segundos subtraídos do PTS para obter a posição na linha do tempo
    first_frame_time: float | None  # posição do 1º quadro decodificado
    frame_count: int | None  # informado pelo contêiner (pode faltar)
    bit_rate: int | None
    has_audio: bool
    container_start: float | None
    warnings: list[str] = field(default_factory=list)

    @property
    def extension(self) -> str:
        return os.path.splitext(self.file_name)[1].lower()

    @property
    def display_size(self) -> tuple[int, int] | None:
        """Dimensões de exibição (após proporção de pixel e rotação)."""
        if not self.width or not self.height:
            return None
        w, h = self.width, self.height
        if self.sar and self.sar > 0 and self.sar != 1:
            w = int(round(w * float(self.sar)))
        if self.rotation % 180 != 0:
            w, h = h, w
        return w, h


def _ts(st, attr: str) -> _dt.datetime | None:
    val = getattr(st, attr, None)
    if val is None:
        return None
    try:
        return _dt.datetime.fromtimestamp(val)
    except (OverflowError, OSError, ValueError):
        return None


def _fraction(value) -> Fraction | None:
    if value is None:
        return None
    try:
        fr = Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return fr if fr > 0 else None


def open_container(path: str):
    """Abre o contêiner em modo leitura, traduzindo erros para português."""
    if not os.path.exists(path):
        raise VideoError("O arquivo não foi encontrado.", path,
                         "Verifique se o arquivo foi movido, renomeado ou se a unidade está conectada.")
    if os.path.isdir(path):
        raise VideoError("O caminho selecionado é uma pasta, não um arquivo de vídeo.", path)
    if os.path.getsize(path) == 0:
        raise VideoError("O arquivo está vazio (0 bytes).", path,
                         "Selecione uma cópia íntegra do vídeo.")
    try:
        return av.open(path, mode="r")
    except PermissionError as e:
        raise VideoError("Sem permissão para ler o arquivo.", str(e),
                         "Verifique se o arquivo está aberto em outro programa ou se há restrição de acesso.") from e
    except av.error.InvalidDataError as e:
        raise VideoError("O arquivo não pôde ser reconhecido como vídeo (formato inválido ou dados corrompidos).",
                         str(e), "Confirme se o arquivo é realmente um vídeo e se não está corrompido ou incompleto.") from e
    except av.error.FFmpegError as e:
        raise VideoError("Não foi possível abrir o arquivo de vídeo.", str(e),
                         "O formato pode não ser suportado. Tente converter uma CÓPIA do vídeo em outro programa.") from e
    except OSError as e:
        raise VideoError("Erro de leitura do arquivo.", str(e)) from e


def time_origin_of(container, stream) -> float:
    if container.start_time is not None:
        return container.start_time / 1_000_000
    if stream.start_time is not None and stream.time_base:
        return float(stream.start_time * stream.time_base)
    return 0.0


def probe_video(path: str) -> VideoInfo:
    path = os.path.abspath(path)
    container = open_container(path)
    try:
        st = os.stat(path)
        if not container.streams.video:
            raise VideoError("O arquivo não contém trilha de vídeo (pode ser somente áudio ou outro tipo de mídia).",
                             f"streams={len(container.streams)}")
        stream = container.streams.video[0]
        cc = stream.codec_context
        warnings: list[str] = []

        if stream.time_base is None:
            raise VideoError("O vídeo não informa a base de tempo dos quadros.", "time_base ausente")
        tb = Fraction(stream.time_base)

        duration = None
        duration_source = "indisponível"
        if container.duration is not None and container.duration > 0:
            duration = container.duration / 1_000_000
            duration_source = "contêiner"
        elif stream.duration is not None and stream.duration > 0:
            duration = float(stream.duration * tb)
            duration_source = "trilha de vídeo"
        else:
            warnings.append("A duração não é informada pelo arquivo.")

        fps = None
        fps_text = None
        fps_source = "indisponível"
        avg = _fraction(stream.average_rate)
        if avg:
            fps, fps_source = float(avg), "taxa média informada pelo contêiner"
        else:
            guessed = _fraction(getattr(stream, "guessed_rate", None))
            if guessed:
                fps, fps_source = float(guessed), "taxa nominal da trilha (estimativa do FFmpeg)"
        if fps:
            fps_text = f"{fps:.3f}".rstrip("0").rstrip(".").replace(".", ",") + " q/s"

        sar = _fraction(cc.sample_aspect_ratio) or _fraction(stream.sample_aspect_ratio)

        codec = cc.name if cc else None
        codec_long = None
        try:
            codec_long = cc.codec.long_name
        except Exception:
            pass

        origin = time_origin_of(container, stream)

        # Decodifica o primeiro quadro: confirma compatibilidade do codec e obtém a rotação.
        rotation = 0
        first_time = None
        try:
            container.seek(0)
        except av.error.FFmpegError:
            pass
        decoded = None
        try:
            for packet in container.demux(stream):
                try:
                    frames = packet.decode()
                except av.error.FFmpegError:
                    continue
                if frames:
                    decoded = frames[0]
                    break
        except av.error.FFmpegError as e:
            raise VideoError("Erro ao ler os dados do vídeo.", str(e),
                             "O arquivo pode estar corrompido ou incompleto.") from e
        if decoded is None:
            raise VideoError(
                "Não foi possível decodificar nenhum quadro deste vídeo (codec não suportado ou dados corrompidos).",
                f"codec={codec}",
                "Tente converter uma CÓPIA do vídeo para MP4 (H.264) em outro programa e carregue a cópia.",
            )
        try:
            rotation = int(round(decoded.rotation or 0))
        except Exception:
            rotation = 0
        if decoded.pts is not None:
            first_time = float(decoded.pts * tb) - origin
        else:
            warnings.append("Os quadros não informam marca de tempo (PTS); os tempos serão estimados pela contagem de quadros.")

        width = cc.width or decoded.width or None
        height = cc.height or decoded.height or None

        has_audio = bool(container.streams.audio)
        frame_count = stream.frames if stream.frames else None
        bit_rate = container.bit_rate or None
        container_start = container.start_time / 1_000_000 if container.start_time is not None else None

        return VideoInfo(
            path=path,
            file_name=os.path.basename(path),
            file_size=st.st_size,
            created=_ts(st, "st_birthtime"),
            modified=_ts(st, "st_mtime"),
            format_name=container.format.name if container.format else None,
            format_long_name=container.format.long_name if container.format else None,
            duration=duration,
            duration_source=duration_source,
            width=width,
            height=height,
            fps=fps,
            fps_text=fps_text,
            fps_source=fps_source,
            codec=codec,
            codec_long=codec_long,
            pix_fmt=cc.format.name if cc and cc.format else None,
            sar=sar,
            rotation=rotation,
            stream_index=stream.index,
            time_base=tb,
            time_origin=origin,
            first_frame_time=first_time,
            frame_count=frame_count,
            bit_rate=bit_rate,
            has_audio=has_audio,
            container_start=container_start,
            warnings=warnings,
        )
    finally:
        container.close()


def human_size(n: int | None) -> str:
    if n is None:
        return "indisponível"
    units = ["bytes", "KB", "MB", "GB", "TB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            if u == "bytes":
                return f"{n} bytes"
            return f"{v:.2f} {u}".replace(".", ",") + f" ({n:,} bytes)".replace(",", ".")
        v /= 1024
    return str(n)
