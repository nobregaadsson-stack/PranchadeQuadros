"""Autoteste do fluxo completo, sem interface gráfica (``PranchaQuadros.exe --autoteste``).

Gera um vídeo sintético localmente e executa: leitura, extração por intervalo, por
quantidade e manual, composição em 3 colunas, exportação PNG/JPEG/PDF, conferência
pixel a pixel da exportação, preservação do original (SHA-256), tratamento de arquivo
inválido e registro técnico. Útil para validar o executável em máquinas sem internet.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback


def _check_qt_player(video: str) -> bool:
    """Confirma que os componentes de vídeo do Qt foram empacotados (exibe quadro exato e reproduz)."""
    import time

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from .core.probe import probe_video
    from .gui.player import PlayerWidget
    from .gui.qtutil import qimage_to_pil
    from .testvideo import read_frame_index

    app = QApplication.instance() or QApplication([])
    p = PlayerWidget()
    p.resize(640, 400)
    p.show()

    def wait(cond, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return False

    try:
        p.load(probe_video(video))
        p.seek(10.0)
        exact = wait(lambda: p.canvas._img is not None and abs(p.current_time() - 10.0) < 1e-6)
        exact = exact and read_frame_index(qimage_to_pil(p.canvas._img)) == 250
        wait(lambda: p.player.mediaStatus() == p.player.MediaStatus.LoadedMedia)
        p.toggle_play()
        played = wait(lambda: p.player.position() > 10_400)
        p.toggle_play()
        return bool(exact and played and p._qt_ok)
    finally:
        p.shutdown()
        p.deleteLater()


def run_selftest(out=None) -> int:
    from PIL import Image, ImageChops

    from .core.export import save_image
    from .core.extraction import ExtractionRequest, Mode, extract_frames, plan_times
    from .core.hashing import sha256_file
    from .core.layout import PlateSettings, render_plate
    from .core.probe import VideoError, probe_video
    from .core.report import SessionLog, build_csv, build_txt
    from .testvideo import make_video, read_frame_index

    lines = []

    def say(msg):
        lines.append(msg)
        try:
            print(msg, flush=True)
        except Exception:  # noqa: BLE001 - executável sem console
            pass

    work = tempfile.mkdtemp(prefix="prancha_autoteste_")
    ok = True
    try:
        def check(cond, name):
            nonlocal ok
            say(f"[{'OK' if cond else 'FALHA'}] {name}")
            ok = ok and bool(cond)

        video = os.path.join(work, "teste.mp4")
        make_video(video, seconds=65, fps=25, width=640, height=360)
        h0 = sha256_file(video)
        info = probe_video(video)
        check(abs(info.duration - 65) < 0.05 and info.width == 640, "Leitura do vídeo (duração e resolução)")

        req = ExtractionRequest(Mode.INTERVAL, 0, info.duration, interval=10)
        res = extract_frames(info, plan_times(req, info.duration), work, req.mode, req.describe())
        times = [r.effective_time for r in res.records]
        check(times == [0, 10, 20, 30, 40, 50, 60], "Teste 1 — extração a cada 10 s")
        check(all(read_frame_index(Image.open(r.image_path)) == round(r.effective_time * 25) for r in res.records),
              "Teste 1 — conteúdo de cada quadro corresponde ao tempo informado")

        req = ExtractionRequest(Mode.COUNT, 5, 35, count=12)
        res12 = extract_frames(info, plan_times(req, info.duration), work, req.mode, req.describe(),
                               range_start=5, range_end=35)
        check(len(res12.records) <= 12 and len(res12.records) == 12, "Teste 2 — 12 quadros solicitados")
        check(all(5 <= r.effective_time <= 35 for r in res12.records), "Teste 2 — nenhum quadro fora do trecho")

        manual = extract_frames(info, [3.3, 17.71, 44.0, 52.5], work, Mode.MANUAL, "manual").records
        del manual[1]  # usuário remove uma captura
        check([round(r.effective_time, 2) for r in manual] == [3.28, 44.0, 52.48], "Teste 3 — seleção manual")

        s = PlateSettings(columns=3)
        img, layout = render_plate(manual + res.records[:3], s)
        check(layout.columns == 3 and layout.rows == 2, "Teste 4 — grade de 3 colunas")
        check(all(c.caption and c.caption.y >= c.image_rect[3] for c in layout.cells),
              "Teste 4 — legenda abaixo de cada quadro, fora da imagem")

        png = os.path.join(work, "prancha.png")
        ef = save_image(img, png, "PNG", protected=[video])
        with Image.open(png) as im:
            same = ImageChops.difference(im.convert("RGB"), img).getbbox() is None
        check(same, "Teste 5 — PNG exportado idêntico à prévia (pixel a pixel)")
        save_image(img, os.path.join(work, "prancha.jpg"), "JPEG", protected=[video])
        save_image(img, os.path.join(work, "prancha.pdf"), "PDF", protected=[video])
        check(os.path.getsize(os.path.join(work, "prancha.pdf")) > 0, "Exportação JPEG e PDF")
        try:
            save_image(img, video, "PNG", protected=[video])
            check(False, "Teste 6 — recusa gravar sobre o vídeo original")
        except VideoError:
            check(True, "Teste 6 — recusa gravar sobre o vídeo original")
        check(sha256_file(video) == h0, "Teste 6 — SHA-256 do original inalterado após todo o processamento")

        bad = os.path.join(work, "invalido.mp4")
        with open(bad, "wb") as fh:
            fh.write(b"isto nao e um video" * 100)
        try:
            probe_video(bad)
            check(False, "Teste 8 — arquivo inválido gera mensagem de erro")
        except VideoError as e:
            check("não pôde ser reconhecido" in str(e), "Teste 8 — arquivo inválido gera mensagem de erro")

        log = SessionLog(info=info)
        recs = manual + res.records[:3]
        txt = build_txt(log, recs, s, layout, ef)
        csv_text = build_csv(log, recs, s, layout, ef)
        check("Quadro 01" in txt and "00:00:03.280" in txt and len(csv_text.strip().splitlines()) == len(recs) + 1,
              "Teste 9 — registro técnico com numeração e tempos")
        check(_check_qt_player(video), "Reprodutor (QtMultimedia) e navegação com quadro exato")
    except Exception:  # noqa: BLE001
        ok = False
        say("FALHA inesperada:\n" + traceback.format_exc())
    finally:
        shutil.rmtree(work, ignore_errors=True)
    say("RESULTADO: " + ("APROVADO" if ok else "REPROVADO"))
    try:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        os.makedirs(os.path.join(base, "PranchaQuadros"), exist_ok=True)
        with open(os.path.join(base, "PranchaQuadros", "autoteste.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_selftest())
