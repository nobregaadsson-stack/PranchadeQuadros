"""Reprodutor simples para navegação e captura manual de quadros.

* Reprodução contínua: QtMultimedia (back-end FFmpeg local).
* Vídeo pausado (busca, barra, quadro anterior/seguinte): o quadro exibido é decodificado
  pelo MESMO mecanismo da extração (PyAV), com posicionamento exato. Assim o quadro que o
  usuário vê é exatamente o quadro capturado, com o mesmo tempo.
* Se o QtMultimedia não reproduzir o arquivo, resta o modo quadro a quadro (somente PyAV).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy, QSlider, QStyle, QToolButton, QVBoxLayout,
                               QWidget)

from ..core.timefmt import format_time
from .qtutil import pil_to_qimage

NO_VIDEO = "Nenhum vídeo carregado.\nClique em “Selecionar vídeo” ou arraste um arquivo para esta janela."


class VideoCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._img: QImage | None = None
        self._message = NO_VIDEO
        self.setMinimumSize(320, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def set_image(self, img: QImage | None):
        self._img = img
        self.update()

    def set_message(self, text: str):
        self._message = text
        self._img = None
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101214"))
        if self._img is not None and not self._img.isNull():
            iw, ih = self._img.width(), self._img.height()
            scale = min(self.width() / iw, self.height() / ih)
            w, h = iw * scale, ih * scale
            target = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(target, self._img)
        else:
            p.setPen(QColor("#9aa4ad"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
        p.end()


class ExactFrameWorker(QObject):
    """Decodifica, sob demanda, o quadro exato em um instante (mesma regra da extração)."""

    frame_ready = Signal(int, object, float)  # id do pedido, QImage, tempo efetivo
    failed = Signal(int, str)

    def __init__(self):
        super().__init__()
        self._grabber = None
        self._info = None
        self.latest = -1

    @Slot(object)
    def open(self, info):
        self.close_grabber()
        from ..core.extraction import FrameGrabber

        self._info = info
        try:
            self._grabber = FrameGrabber(info)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(-1, str(e))

    @Slot(int, float, str)
    def request(self, req_id: int, t: float, mode: str):
        if self._grabber is None or req_id != self.latest:
            return  # pedido superado por outro mais recente
        from ..core.extraction import apply_display_geometry, frame_to_image

        try:
            g = self._grabber.next_after(t) if mode == "next" else self._grabber.grab(t)
            img, _ = frame_to_image(g.frame)
            try:
                rot = int(round(g.frame.rotation or 0))
            except Exception:  # noqa: BLE001
                rot = self._info.rotation
            img = apply_display_geometry(img, rot, self._info.sar)
            self.frame_ready.emit(req_id, pil_to_qimage(img), g.time if g.time is not None else t)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(req_id, str(e))

    @Slot()
    def close_grabber(self):
        if self._grabber is not None:
            self._grabber.close()
            self._grabber = None


class PlayerWidget(QWidget):
    captureRequested = Signal(float)
    markStartRequested = Signal(float)
    markEndRequested = Signal(float)
    playbackProblem = Signal(str)
    _openExact = Signal(object)
    _requestExact = Signal(int, float, str)
    _closeExact = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.info = None
        self._duration_ms = 0
        self._frame_time: float | None = None  # início do quadro exibido (s)
        self._qt_ok = True  # QtMultimedia consegue reproduzir o arquivo
        self._exact_mode = True  # pausado: exibindo quadros decodificados pelo PyAV
        self._slider_dragging = False
        self._req_id = 0

        self.canvas = VideoCanvas(self)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.6)
        self.player.setAudioOutput(self.audio)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._on_video_frame)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        self._exact_thread = QThread(self)
        self._exact_worker = ExactFrameWorker()
        self._exact_worker.moveToThread(self._exact_thread)
        self._openExact.connect(self._exact_worker.open)
        self._requestExact.connect(self._exact_worker.request)
        self._closeExact.connect(self._exact_worker.close_grabber)
        self._exact_worker.frame_ready.connect(self._on_exact_frame)
        self._exact_worker.failed.connect(self._on_exact_failed)
        self._exact_thread.start()

        st = self.style()

        def btn(icon, tip, slot, text=None):
            b = QToolButton(self)
            if icon is not None:
                b.setIcon(st.standardIcon(icon))
            if text:
                b.setText(text)
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if icon else
                                     Qt.ToolButtonStyle.ToolButtonTextOnly)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        self.btn_back10 = btn(QStyle.StandardPixmap.SP_MediaSeekBackward, "Retroceder 10 segundos", self.back10, "10 s")
        self.btn_prev = btn(None, "Quadro anterior (←)", self.prev_frame, "◀ 1 quadro")
        self.btn_play = btn(QStyle.StandardPixmap.SP_MediaPlay, "Reproduzir / pausar (barra de espaço)",
                            self.toggle_play)
        self.btn_next = btn(None, "Quadro seguinte (→)", self.next_frame, "1 quadro ▶")
        self.btn_fwd10 = btn(QStyle.StandardPixmap.SP_MediaSeekForward, "Avançar 10 segundos", self.fwd10, "10 s")
        self.btn_mute = btn(QStyle.StandardPixmap.SP_MediaVolume, "Som ligado/desligado", self.toggle_mute)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.valueChanged.connect(self._on_slider_value)
        self.slider.setToolTip("Barra de navegação pela duração do vídeo")

        self.lbl_time = QLabel("00:00:00.000 / 00:00:00.000", self)
        self.lbl_time.setObjectName("timeLabel")
        self.lbl_time.setToolTip("Tempo do quadro exibido / duração total")
        self.lbl_mode = QLabel("", self)
        self.lbl_mode.setObjectName("hint")
        self.lbl_mode.setWordWrap(True)

        self.btn_capture = btn(QStyle.StandardPixmap.SP_DialogSaveButton,
                               "Captura o quadro exibido e o acrescenta à lista de quadros (modo manual)",
                               self._capture, "Capturar quadro exibido")
        self.btn_capture.setObjectName("primary")
        self.btn_start = btn(None, "Define o tempo inicial do trecho de análise na posição atual",
                             lambda: self.markStartRequested.emit(self.current_time()), "Marcar início")
        self.btn_end = btn(None, "Define o tempo final do trecho de análise na posição atual",
                           lambda: self.markEndRequested.emit(self.current_time()), "Marcar fim")

        row2 = QHBoxLayout()
        for b in (self.btn_back10, self.btn_prev, self.btn_play, self.btn_next, self.btn_fwd10, self.btn_mute):
            row2.addWidget(b)
        row2.addSpacing(8)
        row2.addWidget(self.lbl_time)
        row2.addStretch(1)
        row2.addWidget(self.btn_start)
        row2.addWidget(self.btn_end)
        row2.addWidget(self.btn_capture)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.slider)
        lay.addLayout(row2)
        lay.addWidget(self.lbl_mode)
        self._set_enabled(False)

    # ---------------------------------------------------------------- API
    def load(self, info):
        self.unload()
        self.info = info
        self._qt_ok = True
        self._exact_mode = True
        self._duration_ms = int(round((info.duration or 0) * 1000))
        self.slider.setRange(0, self._duration_ms)
        self.canvas.set_message("Carregando…")
        self._openExact.emit(info)
        self.player.setSource(QUrl.fromLocalFile(info.path))
        self._set_enabled(True)
        self.lbl_mode.setText("")
        self._show_exact(0.0)

    def unload(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self._closeExact.emit()
        self.info = None
        self._frame_time = None
        self.canvas.set_message(NO_VIDEO)
        self.slider.setRange(0, 0)
        self._update_label(0)
        self._set_enabled(False)

    def shutdown(self):
        self.player.stop()
        self._closeExact.emit()
        self._exact_thread.quit()
        self._exact_thread.wait(3000)

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def current_time(self) -> float:
        """Início do quadro exibido (quando conhecido) ou posição do reprodutor durante a reprodução."""
        if not self.is_playing() and self._frame_time is not None:
            return max(0.0, self._frame_time)
        return max(0.0, self.player.position() / 1000)

    def seek(self, seconds: float):
        if not self.info:
            return
        dur = self._duration_ms / 1000 if self._duration_ms else None
        seconds = max(0.0, min(seconds, dur) if dur else seconds)
        if self.is_playing():
            self.player.setPosition(int(round(seconds * 1000)))
        else:
            self._show_exact(seconds)

    # ---------------------------------------------------------------- controles
    @Slot()
    def toggle_play(self):
        if not self.info or not self._qt_ok:
            return
        if self.is_playing():
            self.player.pause()
        else:
            if self._frame_time is not None:
                self.player.setPosition(int(round(self._frame_time * 1000)))
            self._exact_mode = False
            self.player.play()

    @Slot()
    def toggle_mute(self):
        self.audio.setMuted(not self.audio.isMuted())
        self.btn_mute.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaVolumeMuted if self.audio.isMuted() else QStyle.StandardPixmap.SP_MediaVolume))

    @Slot()
    def back10(self):
        self.seek(self.current_time() - 10)

    @Slot()
    def fwd10(self):
        self.seek(self.current_time() + 10)

    def _pause(self):
        if self.is_playing():
            self.player.pause()

    @Slot()
    def prev_frame(self):
        if not self.info:
            return
        self._pause()
        t = self.current_time()
        # o quadro anterior é o que está em exibição imediatamente antes do início do atual
        self._show_exact(max(0.0, t - 0.0005) if t > 0 else 0.0)

    @Slot()
    def next_frame(self):
        if not self.info:
            return
        self._pause()
        self._show_exact(self.current_time() + 0.0002, mode="next")

    @Slot()
    def _capture(self):
        if self.info:
            self._pause()
            self.captureRequested.emit(self.current_time())

    # ---------------------------------------------------------------- quadro exato (PyAV)
    def _show_exact(self, seconds: float, mode: str = "at"):
        self._exact_mode = True
        self._req_id += 1
        self._exact_worker.latest = self._req_id
        self._set_slider(seconds)
        self._requestExact.emit(self._req_id, float(seconds), mode)

    @Slot(int, object, float)
    def _on_exact_frame(self, req_id, qimg, t):
        if req_id != self._req_id or self.is_playing():
            return
        self.canvas.set_image(qimg)
        self._frame_time = t
        self._set_slider(t)
        self._update_label(t)
        if self._qt_ok:
            self.player.setPosition(int(round(t * 1000)))  # reprodução continua deste ponto

    @Slot(int, str)
    def _on_exact_failed(self, req_id, text):
        if req_id in (-1, self._req_id):
            self.canvas.set_message(f"Não foi possível exibir o quadro.\n{text}")

    # ---------------------------------------------------------------- QtMultimedia
    @Slot(QVideoFrame)
    def _on_video_frame(self, frame: QVideoFrame):
        if self._exact_mode or not frame.isValid():
            return
        img = frame.toImage()
        if not img.isNull():
            self.canvas.set_image(img)
        st = frame.startTime()
        if st is not None and st >= 0:
            self._frame_time = st / 1_000_000
        if not self.is_playing():
            self._update_label(self.current_time())

    @Slot("qint64")
    def _on_position(self, pos: int):
        if self._exact_mode:
            return
        self._set_slider(pos / 1000)
        self._update_label(pos / 1000 if self.is_playing() else self.current_time())

    @Slot("qint64")
    def _on_duration(self, dur: int):
        if dur > 0 and not self._duration_ms:
            self._duration_ms = int(dur)
            self.slider.setRange(0, self._duration_ms)

    @Slot(QMediaPlayer.PlaybackState)
    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay))

    @Slot(QMediaPlayer.MediaStatus)
    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self._qt_ok:
            if not self.player.hasVideo():
                self._disable_qt("O componente de reprodução não exibiu a imagem deste vídeo.")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia and self.info:
            self._disable_qt("O componente de reprodução não reconheceu este arquivo.")

    @Slot(QMediaPlayer.Error, str)
    def _on_error(self, err, text):
        if self.info and err != QMediaPlayer.Error.NoError:
            self._disable_qt(text or "erro de reprodução")

    def _disable_qt(self, reason: str):
        if not self._qt_ok or not self.info:
            return
        self._qt_ok = False
        t = self.current_time()
        self.player.stop()
        self.player.setSource(QUrl())
        self.btn_play.setEnabled(False)
        self.btn_mute.setEnabled(False)
        self.lbl_mode.setText("Reprodução contínua indisponível para este arquivo — use a barra e os botões de "
                              "navegação (modo quadro a quadro). A extração não é afetada.")
        self.playbackProblem.emit(reason)
        self._show_exact(t)

    # ---------------------------------------------------------------- barra
    def _set_slider(self, seconds: float):
        if self._slider_dragging:
            return
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(seconds * 1000)))
        self.slider.blockSignals(False)

    @Slot()
    def _on_slider_pressed(self):
        self._slider_dragging = True

    @Slot()
    def _on_slider_released(self):
        self._slider_dragging = False
        self.seek(self.slider.value() / 1000)

    @Slot(int)
    def _on_slider_moved(self, value: int):
        self._update_label(value / 1000)
        if self.is_playing():
            self.player.setPosition(value)
        else:
            self._slider_dragging = False
            self._show_exact(value / 1000)
            self._slider_dragging = True

    @Slot(int)
    def _on_slider_value(self, value: int):
        # cliques na trilha da barra (sem arrastar)
        if not self._slider_dragging:
            self.seek(value / 1000)

    def _update_label(self, seconds: float):
        dur = self._duration_ms / 1000 if self._duration_ms else None
        self.lbl_time.setText(f"{format_time(seconds, True)} / {format_time(dur, True) if dur else '--:--:--'}")

    def _set_enabled(self, on: bool):
        for w in (self.btn_back10, self.btn_prev, self.btn_play, self.btn_next, self.btn_fwd10, self.btn_mute,
                  self.slider, self.btn_capture, self.btn_start, self.btn_end):
            w.setEnabled(on)
