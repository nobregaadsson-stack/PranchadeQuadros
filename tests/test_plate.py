"""Testes 4, 5 e 9: composição, exportação e registro técnico."""

import csv
import io
import os

import pytest
from PIL import Image, ImageChops

from prancha.core.export import export_frames, save_image
from prancha.core.extraction import ExtractionRequest, Mode, extract_frames, plan_times
from prancha.core.hashing import sha256_file
from prancha.core.layout import (LayoutError, PlateSettings, caption_for, compute_layout, render_plate,
                                 template_settings)
from prancha.core.probe import VideoError, probe_video
from prancha.core.report import HashRecord, SessionLog, build_csv, build_txt, write_text


@pytest.fixture(scope="module")
def frames(videos, tmp_path_factory):
    d = str(tmp_path_factory.mktemp("quadros"))
    info = probe_video(videos["hd"])
    req = ExtractionRequest(Mode.INTERVAL, 0, 60, interval=10)
    res = extract_frames(info, plan_times(req, info.duration), d, req.mode, req.describe())
    return info, res.records


def test_4_three_columns_captions_below(frames):
    _, recs = frames
    s = PlateSettings(columns=3)
    layout = compute_layout(recs, s)
    assert (layout.columns, layout.rows) == (3, 3)
    xs = sorted({c.image_rect[0] for c in layout.cells})
    assert len(xs) == 3
    for c in layout.cells:
        assert c.caption is not None
        assert c.caption.y >= c.image_rect[3]  # legenda abaixo e fora da imagem
        assert c.caption.lines[0].startswith(f"QUADRO {c.index + 1:02d} — TEMPO: ")
    # numeração em ordem temporal
    assert [caption_for(r, i, len(recs), s) for i, r in enumerate(recs)][:3] == [
        "QUADRO 01 — TEMPO: 00:00:00", "QUADRO 02 — TEMPO: 00:00:10", "QUADRO 03 — TEMPO: 00:00:20"]


def test_frame_pixels_are_not_covered_by_graphics(frames):
    """Na largura nativa, a área do quadro na prancha é idêntica, pixel a pixel, à imagem extraída."""
    _, recs = frames
    s = PlateSettings(columns=2, frame_width=1280, border_width=6, caption_position="below")
    img, layout = render_plate(recs[:4], s)
    for c in layout.cells:
        x0, y0, x1, y1 = c.image_rect
        assert (x1 - x0, y1 - y0) == (1280, 720)
        with Image.open(recs[c.index].image_path) as src:
            assert ImageChops.difference(img.crop(c.image_rect), src.convert("RGB")).getbbox() is None


def test_aspect_ratio_preserved(frames):
    _, recs = frames
    for fit in ("original", "box"):
        s = PlateSettings(columns=3, frame_width=500, fit_mode=fit, box_aspect=1.0)
        layout = compute_layout(recs, s)
        for c in layout.cells:
            w, h = c.image_rect[2] - c.image_rect[0], c.image_rect[3] - c.image_rect[1]
            assert abs(w / h - 1280 / 720) < 0.01


def test_rows_mode_and_presets(frames):
    _, recs = frames
    layout = compute_layout(recs, PlateSettings(grid_by="rows", rows=2))
    assert (layout.columns, layout.rows) == (4, 2)
    for n in (2, 3, 4, 5):
        assert compute_layout(recs, PlateSettings(columns=n)).columns == n


def test_fixed_canvas_fits_and_respects_size(frames):
    _, recs = frames
    for orient in ("portrait", "landscape"):
        s = PlateSettings(size_mode="fixed", canvas_width=2480, canvas_height=3508, orientation=orient, columns=3,
                          header_enabled=True)
        s.header_fields[0].value = "Vídeo 1"
        img, layout = render_plate(recs, s)
        assert img.size == ((2480, 3508) if orient == "portrait" else (3508, 2480))
        for c in layout.cells:
            assert c.cell_rect[3] <= img.height and c.cell_rect[2] <= img.width


def test_fixed_canvas_too_small_is_reported_not_silently_reduced(frames):
    _, recs = frames
    with pytest.raises(LayoutError):
        compute_layout(recs * 20, PlateSettings(size_mode="fixed", canvas_width=400, canvas_height=300))


def test_templates_and_header(frames):
    info, recs = frames
    for name in ("Técnico simples", "Relatório investigativo", "Alta densidade"):
        s = template_settings(name)
        img, layout = render_plate(recs, s)
        assert img.width > 0
    s = template_settings("Relatório investigativo")
    s.header_fields[3].value = "Ocorrência 123/2026"
    layout = compute_layout(recs, s)
    texts = " ".join(" ".join(t.lines) for t in layout.texts)
    assert "Ocorrência 123/2026" in texts
    assert "Responsável" not in texts  # campo vazio não aparece; nada é inventado


def test_caption_override_and_ms(frames):
    _, recs = frames
    s = PlateSettings(show_ms=True)
    r = recs[1]
    assert caption_for(r, 1, len(recs), s) == "QUADRO 02 — TEMPO: 00:00:10.000"
    r2 = type(r)(**{**r.__dict__, "caption_override": "Pessoa entra no quadro"})
    assert caption_for(r2, 1, len(recs), s) == "Pessoa entra no quadro"


def test_5_export_png_identical_to_preview(frames, tmp_path):
    info, recs = frames
    s = PlateSettings(columns=3)
    preview, _ = render_plate(recs, s)
    again, _ = render_plate(recs, s)  # renderização determinística
    assert preview.tobytes() == again.tobytes()
    out = str(tmp_path / "prancha.png")
    ef = save_image(preview, out, "PNG", protected=[info.path], dpi=300)
    with Image.open(out) as im:
        assert im.size == preview.size
        assert im.convert("RGB").tobytes() == preview.tobytes()
        assert "Composição de quadros" in im.info.get("Description", "")
    assert ef.sha256 == sha256_file(out)
    jpg = str(tmp_path / "prancha.jpg")
    save_image(preview, jpg, "JPEG", protected=[info.path])
    with Image.open(jpg) as im:
        assert im.size == preview.size and im.format == "JPEG"
    pdf = str(tmp_path / "prancha.pdf")
    save_image(preview, pdf, "PDF", protected=[info.path])
    assert open(pdf, "rb").read(5) == b"%PDF-"


def test_export_refuses_to_overwrite_original(frames):
    info, recs = frames
    img, _ = render_plate(recs[:2], PlateSettings())
    before = sha256_file(info.path)
    with pytest.raises(VideoError):
        save_image(img, info.path, "PNG", protected=[info.path])
    assert sha256_file(info.path) == before


def test_individual_frames_export(frames, tmp_path):
    info, recs = frames
    out = export_frames(recs, str(tmp_path / "q"), "caso", apply_geometry=True, protected=[info.path])
    assert [n for n, _, _ in out] == list(range(1, len(recs) + 1))
    for n, rec, ef in out:
        assert os.path.basename(ef.path) == f"caso_quadro_{n:02d}.png"
        with Image.open(ef.path) as a, Image.open(rec.image_path) as b:
            assert a.convert("RGB").tobytes() == b.convert("RGB").tobytes()  # sem alteração de pixels


def test_9_report_consistent(frames, tmp_path):
    info, recs = frames
    s = PlateSettings(columns=3)
    img, layout = render_plate(recs, s)
    plate = save_image(img, str(tmp_path / "p.png"), "PNG")
    log = SessionLog(info=info, file_state_at_load=(os.path.getsize(info.path), os.stat(info.path).st_mtime))
    log.video_hashes.append(HashRecord(sha256_file(info.path), __import__("datetime").datetime.now(), "teste"))
    txt = build_txt(log, recs, s, layout, plate)
    assert "não constitui certificação" in txt.lower() or "Não constitui certificação" in txt
    assert info.file_name in txt and info.path in txt
    assert "00:02:05.000" in txt  # duração
    assert "1280 × 720" in txt
    assert plate.sha256 in txt
    assert "iguais aos observados no carregamento" in txt
    for i, r in enumerate(recs):
        assert f"Quadro {i + 1:02d}" in txt
        assert caption_for(r, i, len(recs), s) in txt
    rows = list(csv.reader(io.StringIO(build_csv(log, recs, s, layout, plate)), delimiter=";"))
    header, data = rows[0], rows[1:]
    assert len(data) == len(recs)
    col = {k: header.index(k) for k in header}
    for i, row in enumerate(data):
        assert row[col["numero"]] == f"{i + 1:02d}"
        assert row[col["legenda"]] == caption_for(recs[i], i, len(recs), s)
        assert float(row[col["tempo_efetivo_s"]].replace(",", ".")) == pytest.approx(recs[i].effective_time)
        assert row[col["sha256_prancha"]] == plate.sha256
    p = str(tmp_path / "registro.txt")
    write_text(p, txt, [info.path])
    assert open(p, encoding="utf-8-sig").read() == txt
