"""Fluxo completo pela interface (Qt em modo offscreen), incluindo os testes 3, 5, 7 e 8."""

import os
import socket
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageChops  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from prancha.gui import main_window as mw  # noqa: E402
from prancha.gui.qtutil import qimage_to_pil  # noqa: E402
from prancha.testvideo import read_frame_index  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def no_network(monkeypatch):
    """Teste 7: qualquer tentativa de abrir conexão de rede faz o teste falhar."""
    attempts = []

    class Blocked(socket.socket):
        def connect(self, *a, **k):
            attempts.append(a)
            raise OSError("rede bloqueada pelo teste")

    monkeypatch.setattr(socket, "socket", Blocked)
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: attempts.append(a) or (_ for _ in ()).throw(OSError("bloqueado")))
    yield attempts
    assert attempts == [], f"tentativas de acesso à rede: {attempts}"


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    msgs = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: msgs.append(("info", a[1:3]))))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: msgs.append(("warn", a[1:3]))))
    monkeypatch.setattr(mw, "error_box", lambda *a, **k: msgs.append(("erro", a[1:3])))
    monkeypatch.setattr(mw.MainWindow, "_export_done_dialog", lambda self, files, errors, plate: msgs.append(
        ("export", files, errors)))
    w = mw.MainWindow()
    w.msgs = msgs
    w.resize(1400, 900)
    w.show()
    yield w
    w.close()


def wait(app, cond, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("tempo esgotado")


def pause(app, s):
    t0 = time.time()
    wait(app, lambda: time.time() - t0 > s)


def load(app, w, path):
    w.load_video(path)
    wait(app, lambda: w.task is None and w.info is not None and w.info.path == os.path.abspath(path))
    pause(app, 0.5)


def test_full_flow(app, window, videos, tmp_path, monkeypatch, no_network):
    w = window
    load(app, w, videos["hd"])
    assert w.info_labels["duration"].text() == "00:02:05.000"
    assert w.info_labels["resolution"].text() == "1280 × 720 px"

    # Teste 1 pela interface: intervalo de 10 s
    w.rb_interval.setChecked(True)
    w.sp_interval.setValue(10)
    w.extract()
    wait(app, lambda: w.task is None)
    assert [r.effective_time for r in w.model.records] == [i * 10.0 for i in range(13)]

    # Teste 3: seleção manual pelo reprodutor, com remoção
    w.model.clear()
    w.rb_manual.setChecked(True)
    for t in (12.0, 33.3, 47.86, 90.0):
        w.player.seek(t)
        wait(app, lambda: w.player.canvas._img is not None and abs(w.player.current_time() - int(t * 25) / 25) < 1e-6)
        shown = read_frame_index(qimage_to_pil(w.player.canvas._img))
        w._on_capture_requested(w.player.current_time())
        wait(app, lambda: w.task is None)
        rec = max(w.model.records, key=lambda r: r.requested_time)
        assert read_frame_index(Image.open(rec.image_path)) == shown == int(t * 25)
    w.frames_view1.selectionModel().clearSelection()
    w._select_row(1)
    w.tabs.setCurrentIndex(0)
    w.remove_selected()
    assert [round(r.effective_time, 2) for r in w.model.records] == [12.0, 47.84, 90.0]

    # Teste 4/5: prancha com 3 colunas, exportação idêntica à prévia
    w.tabs.setCurrentIndex(1)
    w.plate_panel.sp_cols.setValue(3)
    wait(app, lambda: w._last_render is not None and len(w._last_render[2].cells) == 3)
    out = str(tmp_path / "saida.png")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    w.chk_txt.setChecked(True)
    w.chk_csv.setChecked(True)
    w.chk_frames.setChecked(True)
    w.chk_hash.setChecked(True)
    w.export_plate()
    wait(app, lambda: w.task is None)
    assert w.msgs[-1][0] == "export" and not w.msgs[-1][2]
    with Image.open(out) as im:
        assert ImageChops.difference(im.convert("RGB"), w._last_render[1]).getbbox() is None
    layout = w._last_render[2]
    assert (layout.columns, layout.rows) == (3, 1)
    txt = open(str(tmp_path / "saida_registro.txt"), encoding="utf-8-sig").read()
    assert "Quadro 03" in txt and "Quadro 04" not in txt
    assert "00:00:47.840" in txt
    assert len(os.listdir(tmp_path / "saida_quadros")) == 3


def test_invalid_file_does_not_crash(app, window, tmp_path):
    bad = tmp_path / "corrompido.mp4"
    bad.write_bytes(b"\x00\x01" * 5000)
    window.load_video(str(bad))
    wait(app, lambda: window.task is None)
    assert window.info is None
    assert window.msgs and window.msgs[-1][0] == "erro"
    assert "não pôde ser reconhecido" in window.msgs[-1][1][1]
    # o aplicativo continua utilizável
    assert window.act_open.isEnabled()


def test_extraction_can_be_cancelled(app, window, videos):
    w = window
    load(app, w, videos["hd"])
    w.rb_interval.setChecked(True)
    w.sp_interval.setValue(0.04)  # um quadro por quadro: operação longa
    w.extract()
    wait(app, lambda: w.task is not None)
    w.cancel_task()
    wait(app, lambda: w.task is None)
    assert w.model.records == []  # nada parcial é acrescentado
