"""Registro técnico complementar (TXT e CSV).

O registro documenta o que o aplicativo efetivamente fez. Ele NÃO é uma certificação de
autenticidade ou integridade do vídeo.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import os
import platform
from dataclasses import dataclass, field

import av

from .. import APP_NAME, APP_VERSION
from .export import ExportedFile
from .extraction import FrameRecord
from .layout import PlateLayout, PlateSettings, caption_for, number_width
from .probe import VideoInfo, human_size
from .timefmt import format_seconds, format_time

DISCLAIMER = (
    "Este registro contém dados anotados automaticamente pelo aplicativo durante o processamento. "
    "Não constitui certificação de autenticidade ou de integridade do vídeo, e a prancha não é uma "
    "reprodução integral do vídeo. Bordas, legendas, cabeçalho e notas da prancha foram acrescentados "
    "pelo aplicativo e não fazem parte do conteúdo original."
)

TIME_RULE = (
    "Regra temporal: para cada instante solicitado foi usado o quadro em exibição nesse instante "
    "(o último quadro com marca de tempo PTS menor ou igual ao instante). O tempo efetivo é o PTS do "
    "quadro convertido em segundos, medido a partir do início do arquivo; pode ser anterior ao "
    "solicitado em até a duração de um quadro. Nas legendas o tempo é truncado (HH:MM:SS), nunca "
    "arredondado para cima. A precisão máxima é a da base de tempo informada pelo arquivo."
)


@dataclass
class HashRecord:
    sha256: str
    computed_at: _dt.datetime
    context: str  # ex.: "ao carregar", "após a extração"


@dataclass
class SessionLog:
    info: VideoInfo | None = None
    loaded_at: _dt.datetime | None = None
    file_state_at_load: tuple[int, float] | None = None  # (tamanho, mtime)
    video_hashes: list[HashRecord] = field(default_factory=list)
    events: list[tuple[_dt.datetime, str]] = field(default_factory=list)

    def add(self, text: str):
        self.events.append((_dt.datetime.now(), text))


def _dt_text(d: _dt.datetime | None) -> str:
    return d.strftime("%d/%m/%Y %H:%M:%S") if d else "indisponível"


def file_state_note(log: SessionLog) -> str:
    info = log.info
    if not info or not log.file_state_at_load:
        return "indisponível"
    try:
        st = os.stat(info.path)
    except OSError:
        return "Arquivo original não encontrado no momento da geração do registro."
    size0, mtime0 = log.file_state_at_load
    if st.st_size == size0 and abs(st.st_mtime - mtime0) < 1e-6:
        return ("Tamanho e data de modificação do arquivo original iguais aos observados no carregamento "
                "(o aplicativo abre o vídeo somente para leitura).")
    return ("ATENÇÃO: o tamanho ou a data de modificação do arquivo original mudou desde o carregamento "
            "(alteração externa ao aplicativo).")


def build_txt(log: SessionLog, records: list[FrameRecord], settings: PlateSettings,
              layout: PlateLayout | None, plate: ExportedFile | None,
              frame_files: list[tuple[int, FrameRecord, ExportedFile]] | None = None,
              extra_outputs: list[ExportedFile] | None = None) -> str:
    info = log.info
    now = _dt.datetime.now()
    out = io.StringIO()
    w = out.write
    w(f"REGISTRO TÉCNICO DE EXTRAÇÃO DE QUADROS — {APP_NAME} {APP_VERSION}\n")
    w("=" * 78 + "\n")
    w(DISCLAIMER + "\n\n")
    w(f"Data e hora do registro (relógio do computador): {_dt_text(now)}\n")
    w(f"Sistema: {platform.system()} {platform.release()} | Biblioteca de vídeo: PyAV {av.__version__} "
      f"(FFmpeg libavcodec {'.'.join(map(str, av.library_versions.get('libavcodec', ())))})\n")
    w("Processamento: integralmente local, sem conexão com serviços externos.\n\n")

    w("1. ARQUIVO DE VÍDEO DE ORIGEM\n" + "-" * 78 + "\n")
    if info:
        w(f"Nome: {info.file_name}\nCaminho: {info.path}\n")
        w(f"Tamanho: {human_size(info.file_size)}\n")
        w(f"Criação (sistema de arquivos): {_dt_text(info.created)}\n")
        w(f"Modificação (sistema de arquivos): {_dt_text(info.modified)}\n")
        w(f"Formato (contêiner): {info.format_long_name or 'indisponível'} [{info.format_name or '-'}]\n")
        w(f"Codec de vídeo: {info.codec_long or 'indisponível'} [{info.codec or '-'}]; pixel: {info.pix_fmt or 'indisponível'}\n")
        w(f"Duração informada pela ferramenta de leitura: "
          f"{format_time(info.duration, True) if info.duration is not None else 'indisponível'}"
          f"{f' ({format_seconds(info.duration)} s; fonte: {info.duration_source})' if info.duration is not None else ''}\n")
        w(f"Resolução (pixels armazenados): {f'{info.width} × {info.height}' if info.width else 'indisponível'}\n")
        ds = info.display_size
        if ds and ds != (info.width, info.height):
            w(f"Dimensões de exibição (proporção de pixel/rotação): {ds[0]} × {ds[1]}\n")
        w(f"Proporção de pixel (SAR): {info.sar if info.sar else 'não informada (considerada 1:1)'}\n")
        w(f"Rotação de exibição (metadado): {info.rotation}°\n")
        w(f"Taxa de quadros: {info.fps_text or 'indisponível'}"
          f"{f' ({info.fps_source})' if info.fps else ''}\n")
        w(f"Base de tempo da trilha: {info.time_base} s | Origem da linha do tempo: {format_seconds(info.time_origin, 6)} s\n")
        w(f"Quadros informados pelo contêiner: {info.frame_count if info.frame_count else 'indisponível'}\n")
        w(f"Carregado em: {_dt_text(log.loaded_at)}\n")
        w(f"Verificação de preservação: {file_state_note(log)}\n")
        if log.video_hashes:
            for hr in log.video_hashes:
                w(f"SHA-256 do arquivo original ({hr.context}, calculado em {_dt_text(hr.computed_at)}): {hr.sha256}\n")
            if len({h.sha256 for h in log.video_hashes}) > 1:
                w("ATENÇÃO: os valores de SHA-256 calculados em momentos diferentes NÃO coincidem.\n")
        else:
            w("SHA-256 do arquivo original: não calculado pelo aplicativo.\n")
        for wmsg in info.warnings:
            w(f"Observação da leitura: {wmsg}\n")
    else:
        w("Nenhum vídeo carregado.\n")

    w("\n2. CRITÉRIOS DE EXTRAÇÃO UTILIZADOS\n" + "-" * 78 + "\n")
    crits = []
    for r in records:
        if r.criterion not in crits:
            crits.append(r.criterion)
    for c in crits:
        w(f"- {c}\n")
    if not crits:
        w("- nenhum\n")
    times = [r.effective_time for r in records if r.effective_time is not None]
    if times:
        w(f"Intervalo efetivamente coberto pelos quadros: {format_time(min(times), True)} a {format_time(max(times), True)}\n")
    w(f"Quantidade de quadros na composição: {len(records)}\n")
    w(TIME_RULE + "\n")

    w("\n3. QUADROS (numeração idêntica à da prancha)\n" + "-" * 78 + "\n")
    nw = number_width(len(records))
    cells = {c.index: c for c in layout.cells} if layout else {}
    files = {n: ef for n, _, ef in (frame_files or [])}
    for i, r in enumerate(records):
        n = str(i + 1).zfill(nw)
        w(f"Quadro {n}\n")
        w(f"  Legenda na prancha: {caption_for(r, i, len(records), settings).replace(chr(10), ' / ')}\n")
        if r.caption_override:
            w("  (legenda editada manualmente pelo usuário)\n")
        w(f"  Origem: {r.origin.value} — {r.criterion}\n")
        w(f"  Tempo solicitado: {format_time(r.requested_time, True)} ({format_seconds(r.requested_time, 6)} s)\n")
        w(f"  Tempo efetivo do quadro: {format_time(r.effective_time, True)} ({format_seconds(r.effective_time, 6)} s)"
          f" — fonte: {r.time_source}\n")
        if r.offset is not None and abs(r.offset) > 0.0005:
            w(f"  Diferença efetivo − solicitado: {format_seconds(r.offset, 6)} s\n")
        if r.pts is not None:
            w(f"  PTS: {r.pts} × {r.time_base} s\n")
        w(f"  Tipo de quadro: {r.pict_type or 'indisponível'}{' (quadro-chave)' if r.key_frame else ''}\n")
        w(f"  Dimensões extraídas: {r.width} × {r.height} px; conversão de cor: {r.color_conversion}\n")
        if settings.apply_geometry and (r.rotation % 360 or (r.sar and r.sar != 1)):
            dw, dh = r.display_size(True)
            w(f"  Correção de exibição aplicada na prancha: rotação {r.rotation}°, SAR {r.sar or 1} → {dw} × {dh} px\n")
        if i in cells:
            x0, y0, x1, y1 = cells[i].image_rect
            w(f"  Na prancha: posição ({x0}, {y0}), {x1 - x0} × {y1 - y0} px\n")
        if (i + 1) in files:
            ef = files[i + 1]
            w(f"  Arquivo individual: {os.path.basename(ef.path)}  SHA-256: {ef.sha256}\n")
        if r.note:
            w(f"  Observação: {r.note}\n")

    w("\n4. PRANCHA GERADA\n" + "-" * 78 + "\n")
    if plate:
        w(f"Arquivo: {os.path.basename(plate.path)}\nCaminho: {plate.path}\n")
        w(f"Dimensões: {plate.width} × {plate.height} px\n")
        if plate.sha256:
            w(f"SHA-256: {plate.sha256}\n")
    elif layout:
        w(f"(prancha ainda não exportada) Dimensões previstas: {layout.width} × {layout.height} px\n")
    for ef in extra_outputs or []:
        w(f"Arquivo adicional: {os.path.basename(ef.path)}  SHA-256: {ef.sha256}\n")
    if layout:
        w(f"Grade: {layout.columns} coluna(s) × {layout.rows} linha(s); largura de cada quadro na prancha: {layout.frame_width} px\n")
    w(f"Modelo: {settings.template}; ajuste: {'proporções originais' if settings.fit_mode == 'original' else 'área padronizada com margens'}\n")
    w(f"Correção de orientação/proporção de exibição: {'sim' if settings.apply_geometry else 'não'}\n")
    w("Nenhum filtro de cor, nitidez ou contraste foi aplicado aos quadros. Redimensionamento na prancha: "
      "LANCZOS, preservando a proporção.\n")

    if log.events:
        w("\n5. EVENTOS DO PROCESSAMENTO\n" + "-" * 78 + "\n")
        for t, e in log.events:
            w(f"[{_dt_text(t)}] {e}\n")
    return out.getvalue()


CSV_COLUMNS = [
    "numero", "legenda", "legenda_editada", "origem", "criterio", "tempo_solicitado", "tempo_solicitado_s",
    "tempo_efetivo", "tempo_efetivo_s", "diferenca_s", "fonte_tempo", "pts", "base_tempo", "tipo_quadro",
    "quadro_chave", "largura_extraida", "altura_extraida", "rotacao_metadado", "sar", "largura_na_prancha",
    "altura_na_prancha", "arquivo_individual", "sha256_arquivo_individual", "video_origem", "caminho_video",
    "sha256_video", "prancha", "sha256_prancha", "observacao",
]


def build_csv(log: SessionLog, records: list[FrameRecord], settings: PlateSettings,
              layout: PlateLayout | None, plate: ExportedFile | None,
              frame_files: list[tuple[int, FrameRecord, ExportedFile]] | None = None) -> str:
    out = io.StringIO()
    wr = csv.writer(out, delimiter=";", lineterminator="\r\n")
    wr.writerow(CSV_COLUMNS)
    nw = number_width(len(records))
    cells = {c.index: c for c in layout.cells} if layout else {}
    files = {n: ef for n, _, ef in (frame_files or [])}
    info = log.info
    vhash = log.video_hashes[-1].sha256 if log.video_hashes else ""

    def num(v, d=6):
        return "" if v is None else f"{v:.{d}f}".replace(".", ",")

    for i, r in enumerate(records):
        cell = cells.get(i)
        ef = files.get(i + 1)
        wr.writerow([
            str(i + 1).zfill(nw), caption_for(r, i, len(records), settings).replace("\n", " / "),
            "sim" if r.caption_override else "não", r.origin.value, r.criterion,
            format_time(r.requested_time, True), num(r.requested_time),
            format_time(r.effective_time, True), num(r.effective_time), num(r.offset),
            r.time_source, "" if r.pts is None else r.pts, "" if r.time_base is None else str(r.time_base),
            r.pict_type or "", "sim" if r.key_frame else "não", r.width, r.height, r.rotation,
            str(r.sar) if r.sar else "",
            (cell.image_rect[2] - cell.image_rect[0]) if cell else "",
            (cell.image_rect[3] - cell.image_rect[1]) if cell else "",
            os.path.basename(ef.path) if ef else "", ef.sha256 if ef else "",
            info.file_name if info else "", info.path if info else "", vhash,
            os.path.basename(plate.path) if plate else "", plate.sha256 if plate and plate.sha256 else "",
            r.note,
        ])
    return out.getvalue()


def write_text(path: str, text: str, protected: list[str] | None = None) -> None:
    from .export import check_destination, _atomic_save

    check_destination(path, protected or [])

    def saver(tmp):
        # UTF-8 com BOM: abre corretamente no Bloco de Notas e no Excel
        with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(text)

    _atomic_save(path, saver)
