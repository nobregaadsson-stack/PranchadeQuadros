"""Janela principal do aplicativo."""

from __future__ import annotations

import copy
import datetime as _dt
import json
import os

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, APP_VERSION, ORG_NAME
from ..core import tempstore
from ..core.export import ExportedFile, export_frames, save_image
from ..core.extraction import (Distribution, ExtractionRequest, Mode, extract_frames, plan_times)
from ..core.hashing import sha256_file
from ..core.layout import (ImageCache, LayoutError, PlateSettings, compute_layout, number_width, render_plate,
                           template_settings)
from ..core.probe import VIDEO_EXTENSIONS, VideoError, human_size, probe_video
from ..core.report import HashRecord, SessionLog, build_csv, build_txt, write_text
from ..core.timefmt import TimeParseError, format_seconds, format_time, parse_time
from .dialogs import TimeDialog, error_box, show_help
from .frames_model import FramesModel, make_frames_view
from .plate_panel import PlatePreview, PlateSettingsPanel
from .player import PlayerWidget
from .workers import RenderWorker, start_task

LARGE_EXTRACTION = 300


def _label(text="", hint=False, wrap=True, select=False):
    l = QLabel(text)
    l.setWordWrap(wrap)
    if hint:
        l.setObjectName("hint")
    if select:
        l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return l


class MainWindow(QMainWindow):
    _renderRequest = Signal(int, object, object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — extração de quadros e pranchas de vídeo (offline)")
        self.setAcceptDrops(True)
        self.qs = QSettings(ORG_NAME, "PranchaQuadros")
        self.info = None
        self.session_dir = tempstore.new_session_dir()
        self.log = SessionLog()
        self.task = None
        self._task_cb = {}
        self._last_exports: dict = {}
        self._render_gen = 0
        self._last_render = None  # (chave, PIL, layout)
        self._current_layout = None
        self._pending_key = None
        self._last_range: tuple[float, float] | None = None

        self.plate_panel = PlateSettingsPanel()
        self.model = FramesModel(self.plate_panel.settings, self)
        self.model.framesChanged.connect(self._on_frames_changed)
        self.plate_panel.changed.connect(self._on_plate_settings_changed)
        self.plate_panel.resetRequested.connect(self._reset_layout)

        self._build_ui()
        self._build_render_thread()
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(180)
        self._render_timer.timeout.connect(self._do_render)
        self._update_actions()
        self._schedule_render()

    # ================================================================ construção da interface
    def _build_ui(self):
        tb = self.addToolBar("Principal")
        tb.setMovable(False)
        tb.setObjectName("mainToolbar")
        self.act_open = QAction("Selecionar vídeo", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self.select_video)
        tb.addAction(self.act_open)
        self.act_hash = QAction("Calcular SHA-256 do vídeo", self)
        self.act_hash.triggered.connect(self.hash_video)
        tb.addAction(self.act_hash)
        self.act_export = QAction("Exportar prancha…", self)
        self.act_export.setShortcut(QKeySequence("Ctrl+E"))
        self.act_export.triggered.connect(self.export_plate)
        tb.addAction(self.act_export)
        self.act_help = QAction("Ajuda", self)
        self.act_help.setShortcut(QKeySequence.StandardKey.HelpContents)
        self.act_help.triggered.connect(lambda: show_help(self))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        badge = QLabel("🔒  Processamento 100% local — nada é enviado pela internet")
        badge.setObjectName("offlineBadge")
        badge.setToolTip("Todo o processamento ocorre neste computador. Não há conexão com servidores, "
                         "contas, telemetria ou serviços em nuvem.")
        tb.addWidget(badge)
        tb.addAction(self.act_help)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tab_video(), "1 · Vídeo e extração")
        self.tabs.addTab(self._build_tab_plate(), "2 · Prancha e exportação")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        sb = self.statusBar()
        self.lbl_status = QLabel("Pronto. Selecione um vídeo para começar.")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(260)
        self.progress.setVisible(False)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_task)
        sb.addWidget(self.lbl_status, 1)
        sb.addPermanentWidget(self.progress)
        sb.addPermanentWidget(self.btn_cancel)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self._sc_play)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=self._sc_prev)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=self._sc_next)

    def _build_tab_video(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(6, 6, 6, 6)
        vsplit = QSplitter(Qt.Orientation.Vertical)
        hsplit = QSplitter(Qt.Orientation.Horizontal)

        # reprodutor
        self.player = PlayerWidget()
        self.player.captureRequested.connect(self._on_capture_requested)
        self.player.markStartRequested.connect(self._on_mark_start)
        self.player.markEndRequested.connect(self._on_mark_end)
        self.player.playbackProblem.connect(self._on_playback_problem)
        pbox = QGroupBox("Pré-visualização do vídeo")
        pl = QVBoxLayout(pbox)
        pl.addWidget(self.player)
        hsplit.addWidget(pbox)

        # painel direito
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        btn_sel = QPushButton("Selecionar vídeo")
        btn_sel.setObjectName("primary")
        btn_sel.clicked.connect(self.select_video)
        rl.addWidget(btn_sel)

        # informações
        g = QGroupBox("Informações do arquivo")
        grid = QGridLayout(g)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.info_labels: dict[str, QLabel] = {}
        # (chave, rótulo, linha, coluna, ocupa a linha inteira)
        fields = [("name", "Nome", 0, 0, True), ("path", "Caminho", 1, 0, True), ("format", "Formato", 2, 0, True),
                  ("codec", "Codec", 3, 0, True), ("resolution", "Resolução", 4, 0, True),
                  ("duration", "Duração", 5, 0, False), ("fps", "Taxa", 5, 2, False),
                  ("size", "Tamanho", 6, 0, True),
                  ("created", "Criação", 7, 0, False), ("modified", "Modificação", 7, 2, False),
                  ("sha", "SHA-256", 8, 0, True)]
        for key, text, row, col, full in fields:
            cap = QLabel(text + ":")
            cap.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            l = _label("—", select=True)
            self.info_labels[key] = l
            grid.addWidget(cap, row, col)
            grid.addWidget(l, row, col + 1, 1, 3 if full else 1)
        rl.addWidget(g)

        # trecho
        g = QGroupBox("Trecho de análise")
        gl = QFormLayout(g)
        self.ed_start = QLineEdit("00:00:00.000")
        self.ed_end = QLineEdit("00:00:00.000")
        for ed in (self.ed_start, self.ed_end):
            ed.setPlaceholderText("HH:MM:SS.mmm")
            ed.editingFinished.connect(self._update_estimate)
        h1 = QHBoxLayout()
        h1.addWidget(self.ed_start, 1)
        b = QPushButton("Início do vídeo")
        b.clicked.connect(lambda: (self.ed_start.setText("00:00:00.000"), self._update_estimate()))
        h1.addWidget(b)
        h2 = QHBoxLayout()
        h2.addWidget(self.ed_end, 1)
        b = QPushButton("Fim do vídeo")
        b.clicked.connect(self._set_end_to_duration)
        h2.addWidget(b)
        gl.addRow("Tempo inicial:", h1)
        gl.addRow("Tempo final:", h2)
        g.setToolTip("Dica: use “Marcar início” e “Marcar fim” no reprodutor.")
        rl.addWidget(g)

        # critério
        g = QGroupBox("Critério de extração")
        gv = QVBoxLayout(g)
        self.rb_interval = QRadioButton("A — Intervalo de tempo")
        self.rb_count = QRadioButton("B — Quantidade de quadros")
        self.rb_manual = QRadioButton("C — Seleção manual")
        self.rb_interval.setChecked(True)
        grp = QButtonGroup(self)
        for rb in (self.rb_interval, self.rb_count, self.rb_manual):
            grp.addButton(rb)
            rb.toggled.connect(self._on_mode_changed)
        for rb in (self.rb_interval, self.rb_count, self.rb_manual):
            gv.addWidget(rb)
        self.mode_stack = QStackedWidget()
        # A
        wa = QWidget()
        fa = QFormLayout(wa)
        self.cmb_interval = QComboBox()
        self._interval_presets = [("1 segundo", 1), ("5 segundos", 5), ("10 segundos", 10), ("30 segundos", 30),
                                  ("1 minuto", 60), ("Personalizado", None)]
        self.cmb_interval.addItems([p[0] for p in self._interval_presets])
        self.cmb_interval.setCurrentIndex(2)
        self.cmb_interval.currentIndexChanged.connect(self._on_interval_preset)
        self.sp_interval = QDoubleSpinBox()
        self.sp_interval.setRange(0.001, 86400)
        self.sp_interval.setDecimals(3)
        self.sp_interval.setValue(10)
        self.sp_interval.setSuffix(" s")
        self.sp_interval.valueChanged.connect(self._on_interval_value)
        fa.addRow("Um quadro a cada:", self.cmb_interval)
        fa.addRow("Intervalo (segundos):", self.sp_interval)
        self.mode_stack.addWidget(wa)
        # B
        wb = QWidget()
        fb = QFormLayout(wb)
        self.cmb_count = QComboBox()
        self._count_presets = [("6 quadros", 6), ("12 quadros", 12), ("20 quadros", 20), ("30 quadros", 30),
                               ("Personalizada", None)]
        self.cmb_count.addItems([p[0] for p in self._count_presets])
        self.cmb_count.setCurrentIndex(1)
        self.cmb_count.currentIndexChanged.connect(self._on_count_preset)
        self.sp_count = QSpinBox()
        self.sp_count.setRange(1, 5000)
        self.sp_count.setValue(12)
        self.sp_count.valueChanged.connect(self._on_count_value)
        self.cmb_dist = QComboBox()
        self.cmb_dist.addItems(["Uniforme, incluindo o início e o fim do trecho",
                                "Uniforme, no centro de segmentos iguais"])
        self.cmb_dist.currentIndexChanged.connect(self._update_estimate)
        fb.addRow("Quantidade:", self.cmb_count)
        fb.addRow("Quantidade personalizada:", self.sp_count)
        fb.addRow("Distribuição:", self.cmb_dist)
        self.mode_stack.addWidget(wb)
        # C
        wc = QWidget()
        lc = QVBoxLayout(wc)
        lc.addWidget(_label("Navegue pelo vídeo e clique em “Capturar quadro exibido” para cada momento desejado. "
                            "Cada captura entra na lista de quadros abaixo, onde pode ser removida, reordenada ou "
                            "substituída."))
        self.mode_stack.addWidget(wc)
        gv.addWidget(self.mode_stack)
        self.chk_append = QCheckBox("Acrescentar aos quadros já existentes (em vez de substituí-los)")
        footer = QWidget()
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(4, 4, 4, 0)
        fv.addWidget(self.chk_append)
        self.lbl_estimate = _label("", hint=True)
        fv.addWidget(self.lbl_estimate)
        self.btn_extract = QPushButton("Gerar quadros")
        self.btn_extract.setObjectName("primary")
        self.btn_extract.clicked.connect(self.extract)
        fv.addWidget(self.btn_extract)
        rl.addWidget(g)
        rl.addStretch(1)

        for w in right.findChildren(QComboBox):
            w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(right)
        scroll.setMinimumWidth(430)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rightcol = QWidget()
        rc = QVBoxLayout(rightcol)
        rc.setContentsMargins(0, 0, 0, 0)
        rc.addWidget(scroll, 1)
        rc.addWidget(footer)
        hsplit.addWidget(rightcol)
        hsplit.setStretchFactor(0, 3)
        hsplit.setStretchFactor(1, 2)
        hsplit.setSizes([1000, 480])
        vsplit.addWidget(hsplit)

        # lista de quadros
        fbox = QGroupBox("Quadros selecionados (ordem = numeração na prancha)")
        fl = QVBoxLayout(fbox)
        fl.addLayout(self._frames_toolbar(horizontal=True))
        self.frames_view1 = make_frames_view(self.model, True)
        self.frames_view1.doubleClicked.connect(lambda idx: self.edit_caption(idx.row()))
        self.frames_view1.setMinimumHeight(150)
        fl.addWidget(self.frames_view1)
        vsplit.addWidget(fbox)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 1)
        vsplit.setSizes([760, 190])
        outer.addWidget(vsplit)
        return page

    def _frames_toolbar(self, horizontal: bool):
        h = QHBoxLayout()

        def mk(text, tip, slot):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            h.addWidget(b)
            return b

        mk("Remover", "Remove os quadros selecionados (Delete)", self.remove_selected)
        mk("◀ Mover", "Move o quadro selecionado uma posição para trás", lambda: self.move_selected(-1))
        mk("Mover ▶", "Move o quadro selecionado uma posição para frente", lambda: self.move_selected(1))
        mk("Ordenar por tempo", "Restaura a ordem temporal", self.sort_frames)
        mk("Editar legenda", "Corrige a legenda do quadro selecionado (duplo clique)",
           lambda: self.edit_caption(self._selected_rows()[0] if self._selected_rows() else -1))
        mk("Substituir…", "Substitui o quadro selecionado por outra captura", self.replace_selected)
        mk("Acrescentar…", "Acrescenta um quadro de um instante informado", self.add_at_time)
        mk("Ver no reprodutor", "Posiciona o reprodutor no tempo do quadro selecionado", self.show_in_player)
        mk("Limpar lista", "Remove todos os quadros da lista", self.clear_frames)
        h.addStretch(1)
        lbl = _label("", hint=True, wrap=False)
        if horizontal:
            self.lbl_count1 = lbl
        else:
            self.lbl_count2 = lbl
        h.addWidget(lbl)
        return h

    def _build_tab_plate(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(6, 6, 6, 6)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.plate_panel.setMinimumWidth(400)
        split.addWidget(self.plate_panel)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()

        def mk(text, tip, slot):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
            return b

        self.preview = PlatePreview()
        mk("−", "Reduzir a visualização (Ctrl + roda do mouse)", lambda: self.preview.zoom(1 / 1.25))
        mk("+", "Ampliar a visualização", lambda: self.preview.zoom(1.25))
        mk("Ajustar", "Ajustar a prancha à janela", self.preview.fit)
        mk("100%", "Tamanho real (1 pixel da tela = 1 pixel da imagem)", self.preview.actual_size)
        self.lbl_zoom = _label("", hint=True, wrap=False)
        bar.addWidget(self.lbl_zoom)
        bar.addSpacing(16)
        mk("Colunas −", "Diminuir o número de colunas", lambda: self.plate_panel.adjust(columns_delta=-1))
        mk("Colunas +", "Aumentar o número de colunas", lambda: self.plate_panel.adjust(columns_delta=1))
        mk("Quadros −", "Diminuir o tamanho dos quadros", lambda: self.plate_panel.adjust(width_factor=1 / 1.15))
        mk("Quadros +", "Aumentar o tamanho dos quadros", lambda: self.plate_panel.adjust(width_factor=1.15))
        mk("Espaço −", "Diminuir o espaçamento", lambda: self.plate_panel.adjust(spacing_delta=-4))
        mk("Espaço +", "Aumentar o espaçamento", lambda: self.plate_panel.adjust(spacing_delta=4))
        bar.addStretch(1)
        cl.addLayout(bar)
        self.preview.zoomChanged.connect(lambda z: self.lbl_zoom.setText(f"{z * 100:.0f}%"))
        self.preview.cellClicked.connect(self._on_preview_cell_clicked)
        self.preview.cellDoubleClicked.connect(self.edit_caption)
        cl.addWidget(self.preview, 1)
        self.lbl_dims = _label("", wrap=True, select=True)
        self.lbl_dims.setObjectName("dims")
        cl.addWidget(self.lbl_dims)
        self.lbl_warn = _label("", wrap=True)
        self.lbl_warn.setObjectName("warn")
        self.lbl_warn.setVisible(False)
        cl.addWidget(self.lbl_warn)
        split.addWidget(center)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        fbox = QGroupBox("Quadros da prancha")
        fl = QVBoxLayout(fbox)
        tb = self._frames_toolbar(horizontal=False)
        # barra vertical compacta: reorganiza os botões em duas linhas
        wrap = QWidget()
        grid = QVBoxLayout(wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        rows_l = [QHBoxLayout(), QHBoxLayout(), QHBoxLayout()]
        items = [tb.itemAt(i).widget() for i in range(tb.count()) if tb.itemAt(i).widget()]
        for i, w in enumerate(items[:-1]):
            rows_l[min(i // 3, 2)].addWidget(w, 1)
        for rl_ in rows_l:
            grid.addLayout(rl_)
        grid.addWidget(items[-1])
        fl.addWidget(wrap)
        self.frames_view2 = make_frames_view(self.model, False)
        self.frames_view2.doubleClicked.connect(lambda idx: self.edit_caption(idx.row()))
        self.frames_view2.selectionModel().currentChanged.connect(
            lambda cur, _prev: self.preview.select_cell(cur.row()))
        fl.addWidget(self.frames_view2, 1)
        rl.addWidget(fbox, 1)

        ebox = QGroupBox("Exportação")
        ef = QFormLayout(ebox)
        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["PNG (recomendado, sem perdas)", "JPEG (arquivo menor)"])
        self.cmb_format.currentIndexChanged.connect(lambda i: self.sp_quality.setEnabled(i == 1))
        ef.addRow("Formato:", self.cmb_format)
        self.sp_quality = QSpinBox()
        self.sp_quality.setRange(50, 100)
        self.sp_quality.setValue(95)
        self.sp_quality.setEnabled(False)
        ef.addRow("Qualidade JPEG:", self.sp_quality)
        self.chk_pdf = QCheckBox("Gerar também versão PDF")
        self.chk_frames = QCheckBox("Exportar quadros individuais (PNG)")
        self.chk_txt = QCheckBox("Salvar registro técnico (TXT)")
        self.chk_txt.setChecked(True)
        self.chk_csv = QCheckBox("Salvar registro técnico (CSV)")
        self.chk_hash = QCheckBox("Calcular SHA-256 do vídeo original")
        self.chk_hash.setToolTip("Calcula localmente o SHA-256 dos bytes do arquivo de vídeo no momento da exportação. "
                                 "Os arquivos gerados sempre têm o SHA-256 registrado.")
        for c in (self.chk_pdf, self.chk_frames, self.chk_txt, self.chk_csv, self.chk_hash):
            ef.addRow(c)
        self.btn_export = QPushButton("Exportar prancha…")
        self.btn_export.setObjectName("primary")
        self.btn_export.clicked.connect(self.export_plate)
        ef.addRow(self.btn_export)
        self.btn_save_log = QPushButton("Salvar somente o registro técnico…")
        self.btn_save_log.clicked.connect(self.save_log_only)
        ef.addRow(self.btn_save_log)
        rl.addWidget(ebox)
        right.setMinimumWidth(360)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([410, 860, 370])
        outer.addWidget(split)
        return page

    def _build_render_thread(self):
        self._render_thread = QThread(self)
        self._render_worker = RenderWorker()
        self._render_worker.moveToThread(self._render_thread)
        self._renderRequest.connect(self._render_worker.render)
        self._render_worker.rendered.connect(self._on_rendered)
        self._render_worker.failed.connect(self._on_render_failed)
        self._render_thread.start()

    # ================================================================ tarefas em segundo plano
    def run_task(self, title: str, fn, on_success=None, on_item=None, on_cancel=None, cancellable=True) -> bool:
        if self.task is not None:
            QMessageBox.information(self, "Aguarde", f"Há uma operação em andamento: {self.task.title}.")
            return False
        h = start_task(fn, title, self)
        self.task = h
        self._task_cb = {"success": on_success, "item": on_item, "cancel": on_cancel, "title": title}
        h.worker.progress.connect(self._on_task_progress)
        h.worker.item.connect(self._on_task_item)
        h.worker.succeeded.connect(self._on_task_success)
        h.worker.failed.connect(self._on_task_failed)
        h.worker.cancelled.connect(self._on_task_cancelled)
        h.worker.done.connect(self._on_task_done)
        self.lbl_status.setText(f"{title}…")
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.btn_cancel.setVisible(cancellable)
        self.btn_cancel.setEnabled(True)
        self._update_actions()
        h.thread.start()
        return True

    @Slot()
    def cancel_task(self):
        if self.task:
            self.task.cancel()
            self.btn_cancel.setEnabled(False)
            self.lbl_status.setText(f"Cancelando: {self.task.title}…")

    @Slot(int, int, str)
    def _on_task_progress(self, done, total, text):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        title = self._task_cb.get("title", "")
        self.lbl_status.setText(f"{title}: {text}" if text else f"{title}: {done} de {total}")

    @Slot(object)
    def _on_task_item(self, obj):
        cb = self._task_cb.get("item")
        if cb:
            cb(obj)

    @Slot(object)
    def _on_task_success(self, result):
        cb = self._task_cb.get("success")
        self.lbl_status.setText(f"{self._task_cb.get('title', '')}: concluído.")
        if cb:
            try:
                cb(result)
            except Exception as e:  # noqa: BLE001
                self._show_exception("Erro", e)

    @Slot(object)
    def _on_task_failed(self, exc):
        self.lbl_status.setText(f"{self._task_cb.get('title', '')}: falhou.")
        self._show_exception(self._task_cb.get("title", "Erro"), exc)

    @Slot()
    def _on_task_cancelled(self):
        self.lbl_status.setText(f"{self._task_cb.get('title', '')}: cancelado pelo usuário. "
                                "O arquivo original não foi alterado.")
        cb = self._task_cb.get("cancel")
        if cb:
            cb()

    @Slot()
    def _on_task_done(self):
        self.task = None
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self._update_actions()

    def _show_exception(self, title, exc):
        if isinstance(exc, VideoError):
            error_box(self, title, str(exc) + (f"\n\nComo resolver: {exc.hint}" if exc.hint else ""),
                      exc.technical)
        elif isinstance(exc, LayoutError):
            error_box(self, title, str(exc))
        elif isinstance(exc, MemoryError):
            error_box(self, title, "Memória insuficiente para concluir a operação. Reduza o tamanho da prancha "
                                   "(largura dos quadros) ou a quantidade de quadros.")
        elif isinstance(exc, PermissionError):
            error_box(self, title, "Sem permissão para acessar o arquivo ou a pasta. Verifique se o arquivo está "
                                   "aberto em outro programa.", str(exc))
        elif isinstance(exc, OSError):
            error_box(self, title, "Erro de leitura ou gravação de arquivo.", str(exc))
        else:
            error_box(self, title, "Ocorreu um erro inesperado. A operação foi interrompida com segurança e o "
                                   "arquivo original não foi alterado.",
                      getattr(exc, "traceback_text", "") or repr(exc))

    def _update_actions(self):
        busy = self.task is not None
        has_video = self.info is not None
        has_frames = len(self.model.records) > 0
        self.act_open.setEnabled(not busy)
        self.act_hash.setEnabled(has_video and not busy)
        self.btn_extract.setEnabled(has_video and not busy and not self.rb_manual.isChecked())
        self.act_export.setEnabled(has_frames and not busy)
        self.btn_export.setEnabled(has_frames and not busy)
        self.btn_save_log.setEnabled(has_video and not busy)
        n = len(self.model.records)
        txt = f"{n} quadro(s)" if n else "Nenhum quadro — gere ou capture quadros."
        self.lbl_count1.setText(txt)
        self.lbl_count2.setText(txt)

    # ================================================================ vídeo
    @Slot()
    def select_video(self):
        exts = " ".join(f"*{e}" for e in VIDEO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar vídeo", self.qs.value("last_video_dir", ""),
                                              f"Vídeos ({exts});;Todos os arquivos (*.*)")
        if path:
            self.load_video(path)

    def load_video(self, path: str):
        if self.task is not None:
            QMessageBox.information(self, "Aguarde", "Aguarde a operação em andamento terminar.")
            return
        if self.model.records:
            r = QMessageBox.question(self, "Carregar outro vídeo",
                                     f"Os {len(self.model.records)} quadros atuais pertencem ao vídeo carregado e "
                                     "serão descartados. Deseja continuar?")
            if r != QMessageBox.StandardButton.Yes:
                return
        self.qs.setValue("last_video_dir", os.path.dirname(path))

        def job(ctx):
            ctx.progress(0, 0, "lendo informações do arquivo")
            return probe_video(path)

        self.run_task("Abrindo vídeo", job, on_success=self._on_video_loaded, cancellable=False)

    def _on_video_loaded(self, info):
        # descarta a sessão anterior
        self.player.unload()
        self.model.clear()
        tempstore.cleanup_all()
        self.session_dir = tempstore.new_session_dir()
        self._last_exports = {}
        self._last_range = None
        self.info = info
        st = os.stat(info.path)
        self.log = SessionLog(info=info, loaded_at=_dt.datetime.now(), file_state_at_load=(st.st_size, st.st_mtime))
        self.log.add(f"Vídeo carregado (somente leitura): {info.path}")
        for w in info.warnings:
            self.log.add(f"Observação da leitura: {w}")
        self._show_info(info)
        self.player.load(info)
        self.ed_start.setText(format_time(0, True))
        self._set_end_to_duration()
        self.plate_panel.set_native_width((info.display_size or (info.width, info.height))[0])
        self.plate_panel.set_header_value("file_name", info.file_name)
        self.plate_panel.set_header_value("analysis_dt", _dt.datetime.now().strftime("%d/%m/%Y %H:%M"))
        self.plate_panel.update_auto_time_range("")
        self.lbl_status.setText(f"Vídeo carregado: {info.file_name}")
        self._update_actions()
        self._update_estimate()
        if info.warnings:
            QMessageBox.information(self, "Observações sobre o vídeo", "\n".join(info.warnings))

    @staticmethod
    def _elide_path(path: str, limit: int = 52) -> str:
        if len(path) <= limit:
            return path
        return path[:22] + "…" + path[-(limit - 23):]

    def _show_info(self, info):
        L = self.info_labels
        L["name"].setText(info.file_name)
        L["path"].setText(self._elide_path(info.path))
        L["path"].setToolTip(info.path)
        L["format"].setText(f"{info.extension.lstrip('.').upper() or '—'} — {info.format_long_name or 'indisponível'}")
        L["codec"].setText(f"{info.codec_long or info.codec or 'indisponível'}"
                           f"{' + áudio' if info.has_audio else ' (sem áudio)'}")
        L["duration"].setText(format_time(info.duration, True) if info.duration is not None else "indisponível")
        if info.width:
            res = f"{info.width} × {info.height} px"
            ds = info.display_size
            if ds and ds != (info.width, info.height):
                res += f" (exibição {ds[0]} × {ds[1]}"
                res += f", rotação {info.rotation}°" if info.rotation else ""
                res += ")"
            L["resolution"].setText(res)
        else:
            L["resolution"].setText("indisponível")
        L["fps"].setText(info.fps_text or "indisponível")
        if info.fps:
            L["fps"].setToolTip(info.fps_source)
        L["size"].setText(human_size(info.file_size))
        L["created"].setText(info.created.strftime("%d/%m/%Y %H:%M:%S") if info.created else "indisponível")
        L["modified"].setText(info.modified.strftime("%d/%m/%Y %H:%M:%S") if info.modified else "indisponível")
        L["sha"].setText("não calculado (opcional)")

    @Slot()
    def hash_video(self, then=None, context="a pedido do usuário"):
        if not self.info:
            return
        path = self.info.path

        def job(ctx):
            return sha256_file(path, progress=lambda d, t: ctx.progress(d // 1_048_576, max(1, t // 1_048_576),
                                                                         f"{d // 1_048_576} de {t // 1_048_576} MB"),
                               is_cancelled=ctx.is_cancelled)

        def ok(digest):
            hr = HashRecord(digest, _dt.datetime.now(), context)
            self.log.video_hashes.append(hr)
            self.log.add(f"SHA-256 do vídeo calculado ({context}): {digest}")
            self.info_labels["sha"].setText(f"{digest[:32]}\n{digest[32:]}\n(calculado em {hr.computed_at.strftime('%d/%m/%Y %H:%M:%S')})")
            if len({h.sha256 for h in self.log.video_hashes}) > 1:
                QMessageBox.warning(self, "SHA-256 divergente",
                                    "O SHA-256 do vídeo mudou desde o cálculo anterior: o arquivo foi alterado por "
                                    "outro programa. (Este aplicativo abre o vídeo somente para leitura.)")
            if then:
                then()

        self.run_task("Calculando SHA-256 do vídeo", job, on_success=ok)

    @Slot(str)
    def _on_playback_problem(self, reason):
        self.log.add(f"Reprodução contínua indisponível ({reason}); usado o modo quadro a quadro.")

    # ================================================================ trecho e critério
    def _set_end_to_duration(self):
        if self.info and self.info.duration is not None:
            self.ed_end.setText(format_time(self.info.duration, True))
        self._update_estimate()

    @Slot(float)
    def _on_mark_start(self, t):
        self.ed_start.setText(format_time(t, True))
        self._update_estimate()

    @Slot(float)
    def _on_mark_end(self, t):
        self.ed_end.setText(format_time(t, True))
        self._update_estimate()

    @Slot()
    def _on_mode_changed(self, *_):
        if self.rb_interval.isChecked():
            self.mode_stack.setCurrentIndex(0)
        elif self.rb_count.isChecked():
            self.mode_stack.setCurrentIndex(1)
        else:
            self.mode_stack.setCurrentIndex(2)
        self._update_actions()
        self._update_estimate()

    @Slot(int)
    def _on_interval_preset(self, i):
        v = self._interval_presets[i][1]
        if v is not None:
            self.sp_interval.blockSignals(True)
            self.sp_interval.setValue(v)
            self.sp_interval.blockSignals(False)
        self._update_estimate()

    @Slot(float)
    def _on_interval_value(self, v):
        idx = next((i for i, p in enumerate(self._interval_presets) if p[1] == v), len(self._interval_presets) - 1)
        self.cmb_interval.blockSignals(True)
        self.cmb_interval.setCurrentIndex(idx)
        self.cmb_interval.blockSignals(False)
        self._update_estimate()

    @Slot(int)
    def _on_count_preset(self, i):
        v = self._count_presets[i][1]
        if v is not None:
            self.sp_count.blockSignals(True)
            self.sp_count.setValue(v)
            self.sp_count.blockSignals(False)
        self._update_estimate()

    @Slot(int)
    def _on_count_value(self, v):
        idx = next((i for i, p in enumerate(self._count_presets) if p[1] == v), len(self._count_presets) - 1)
        self.cmb_count.blockSignals(True)
        self.cmb_count.setCurrentIndex(idx)
        self.cmb_count.blockSignals(False)
        self._update_estimate()

    def _build_request(self) -> ExtractionRequest:
        try:
            start = parse_time(self.ed_start.text())
            end = parse_time(self.ed_end.text())
        except TimeParseError as e:
            raise VideoError(str(e)) from e
        if self.rb_interval.isChecked():
            return ExtractionRequest(Mode.INTERVAL, start, end, interval=self.sp_interval.value())
        dist = Distribution.ENDPOINTS if self.cmb_dist.currentIndex() == 0 else Distribution.CENTERED
        return ExtractionRequest(Mode.COUNT, start, end, count=self.sp_count.value(), distribution=dist)

    @Slot()
    def _update_estimate(self, *_):
        if not self.info:
            self.lbl_estimate.setText("Carregue um vídeo para definir a extração.")
            return
        if self.rb_manual.isChecked():
            self.lbl_estimate.setText(f"{len(self.model.records)} quadro(s) na lista.")
            return
        try:
            req = self._build_request()
            times = plan_times(req, self.info.duration)
            self.lbl_estimate.setText(
                f"Serão extraídos até {len(times)} quadro(s) entre {format_time(req.start, True)} e "
                f"{format_time(req.end, True)}.")
            self.lbl_estimate.setObjectName("hint")
        except VideoError as e:
            self.lbl_estimate.setText(f"⚠ {e}")
        self.lbl_estimate.style().unpolish(self.lbl_estimate)
        self.lbl_estimate.style().polish(self.lbl_estimate)

    # ================================================================ extração
    @Slot()
    def extract(self):
        if not self.info:
            return
        try:
            req = self._build_request()
            times = plan_times(req, self.info.duration)
        except VideoError as e:
            QMessageBox.warning(self, "Parâmetros de extração", str(e) + (f"\n\n{e.hint}" if e.hint else ""))
            return
        if len(times) > LARGE_EXTRACTION:
            r = QMessageBox.question(
                self, "Muitos quadros",
                f"A configuração atual gera {len(times)} quadros. Isso pode demorar, ocupar bastante espaço "
                "temporário em disco e produzir uma prancha muito grande.\n\nDeseja continuar?")
            if r != QMessageBox.StandardButton.Yes:
                return
        replace = not self.chk_append.isChecked()
        if replace and self.model.records:
            r = QMessageBox.question(self, "Substituir quadros",
                                     f"Os {len(self.model.records)} quadros atuais serão substituídos pelos novos. "
                                     "Continuar? (Para manter, marque “Acrescentar aos quadros já existentes”.)")
            if r != QMessageBox.StandardButton.Yes:
                return
        info, out = self.info, self.session_dir
        criterion = req.describe()

        def job(ctx):
            return extract_frames(
                info, times, out, req.mode, criterion, range_start=req.start, range_end=req.end,
                progress=lambda d, t, rec: ctx.progress(d, t, f"quadro {d} de {t}"),
                is_cancelled=ctx.is_cancelled)

        def ok(res):
            self._last_range = (req.start, req.end)
            self.model.add(res.records, replace=replace)
            self.log.add(f"Extração — {criterion}: {len(times)} instante(s) solicitado(s), "
                         f"{len(res.records)} quadro(s) obtido(s)"
                         f"{', ' + str(len(res.merged)) + ' instante(s) unificado(s) com quadro já obtido' if res.merged else ''}"
                         f"{', ' + str(len(res.errors)) + ' falha(s)' if res.errors else ''}.")
            for e in res.errors:
                self.log.add(f"Falha de extração: {e}")
            if res.decode_errors:
                self.log.add(f"O decodificador relatou {res.decode_errors} pacote(s) com erro durante a leitura.")
            msgs = []
            if res.merged:
                msgs.append(f"{len(res.merged)} instante(s) solicitado(s) correspondem ao mesmo quadro de outro "
                            "instante (intervalo menor que a duração de um quadro) e não foram duplicados.")
            if res.errors:
                msgs.append("Não foi possível extrair alguns quadros:\n• " + "\n• ".join(res.errors[:15]) +
                            ("\n…" if len(res.errors) > 15 else ""))
            if res.decode_errors:
                msgs.append(f"O decodificador encontrou {res.decode_errors} trecho(s) com dados danificados no "
                            "arquivo. Confira visualmente os quadros obtidos.")
            self.lbl_status.setText(f"Extração concluída: {len(res.records)} quadro(s).")
            if msgs:
                QMessageBox.warning(self, "Extração concluída com observações", "\n\n".join(msgs))

        def cancelled():
            self.log.add(f"Extração cancelada pelo usuário ({criterion}); nenhum quadro foi acrescentado.")

        self.run_task("Extraindo quadros", job, on_success=ok, on_cancel=cancelled)

    def _capture_job(self, t: float, criterion: str):
        info, out = self.info, self.session_dir

        def job(ctx):
            ctx.progress(0, 0, f"capturando {format_time(t, True)}")
            # pequena folga garante o quadro exibido mesmo com arredondamento de microssegundos
            res = extract_frames(info, [t + 0.0002], out, Mode.MANUAL, criterion)
            if not res.records:
                raise VideoError(res.errors[0] if res.errors else "Não foi possível capturar o quadro.")
            rec = res.records[0]
            rec.requested_time = t
            return rec

        return job

    @Slot(float)
    def _on_capture_requested(self, t: float):
        if not self.info:
            return

        def ok(rec):
            self.model.add([rec])
            self.log.add(f"Captura manual: solicitado {format_time(t, True)}, quadro em "
                         f"{format_time(rec.effective_time, True)}.")
            self.lbl_status.setText(f"Quadro capturado em {format_time(rec.effective_time, True)} "
                                    f"({len(self.model.records)} na lista).")

        self.run_task("Capturando quadro", self._capture_job(t, "Seleção manual (captura no reprodutor)"),
                      on_success=ok, cancellable=False)

    # ================================================================ lista de quadros
    def _active_view(self):
        return self.frames_view2 if self.tabs.currentIndex() == 1 else self.frames_view1

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self._active_view().selectionModel().selectedIndexes()})

    def _select_row(self, row: int):
        for v in (self.frames_view1, self.frames_view2):
            if 0 <= row < self.model.rowCount():
                idx = self.model.index(row)
                v.setCurrentIndex(idx)
                v.scrollTo(idx)

    @Slot()
    def remove_selected(self):
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "Remover", "Selecione um ou mais quadros na lista.")
            return
        removed = self.model.remove_rows(rows)
        for r in removed:
            self.log.add(f"Quadro em {format_time(r.effective_time, True)} removido da composição pelo usuário.")

    def move_selected(self, delta: int):
        rows = self._selected_rows()
        if len(rows) != 1:
            QMessageBox.information(self, "Mover", "Selecione um quadro para mover.")
            return
        new = self.model.move(rows[0], delta)
        self._select_row(new)

    @Slot()
    def sort_frames(self):
        self.model.sort_by_time()

    @Slot()
    def clear_frames(self):
        if not self.model.records:
            return
        r = QMessageBox.question(self, "Limpar lista", f"Remover todos os {len(self.model.records)} quadros da lista?")
        if r == QMessageBox.StandardButton.Yes:
            self.log.add(f"Lista de quadros esvaziada pelo usuário ({len(self.model.records)} quadros).")
            self.model.clear()

    @Slot(int)
    def edit_caption(self, row: int):
        if not (0 <= row < len(self.model.records)):
            QMessageBox.information(self, "Editar legenda", "Selecione um quadro.")
            return
        rec = self.model.records[row]
        cur = self.model.data(self.model.index(row))
        text, ok = QInputDialog.getMultiLineText(
            self, "Corrigir legenda",
            f"Legenda do quadro {row + 1} (tempo efetivo {format_time(rec.effective_time, True)}).\n"
            "Deixe em branco para restaurar a legenda automática.", cur)
        if ok:
            new = text.strip() or None
            self.model.set_caption(row, new)
            self.log.add(f"Legenda do quadro em {format_time(rec.effective_time, True)} "
                         f"{'alterada para: ' + new.replace(chr(10), ' / ') if new else 'restaurada para a automática'}.")

    @Slot()
    def replace_selected(self):
        rows = self._selected_rows()
        if len(rows) != 1 or not self.info:
            QMessageBox.information(self, "Substituir", "Selecione um quadro para substituir.")
            return
        row = rows[0]
        old = self.model.records[row]
        d = TimeDialog(self, "Substituir quadro",
                       f"Substituir o quadro {row + 1} ({format_time(old.effective_time, True)}) pelo quadro do "
                       "instante informado:", old.effective_time or 0, self.player.current_time() if self.player.info
                       else None, self.info.duration)
        if not d.exec() or d.value is None:
            return
        t = d.value

        def ok(rec):
            target = next((i for i, r in enumerate(self.model.records) if r.id == old.id), None)
            if target is None:
                return
            self.model.replace(target, rec)
            self.log.add(f"Quadro em {format_time(old.effective_time, True)} substituído pelo quadro em "
                         f"{format_time(rec.effective_time, True)}.")
            if old.caption_override:
                QMessageBox.information(self, "Substituir", "A legenda editada do quadro anterior foi descartada; "
                                                            "o novo quadro usa a legenda automática.")
            self._select_row(target)

        self.run_task("Substituindo quadro", self._capture_job(t, "Seleção manual (substituição)"), on_success=ok,
                      cancellable=False)

    @Slot()
    def add_at_time(self):
        if not self.info:
            return
        d = TimeDialog(self, "Acrescentar quadro", "Instante do vídeo a acrescentar à prancha:",
                       self.player.current_time() if self.player.info else 0,
                       self.player.current_time() if self.player.info else None, self.info.duration)
        if d.exec() and d.value is not None:
            self._on_capture_requested(d.value)

    @Slot()
    def show_in_player(self):
        rows = self._selected_rows()
        if len(rows) != 1 or not self.player.info:
            return
        rec = self.model.records[rows[0]]
        self.tabs.setCurrentIndex(0)
        self.player.player.pause()
        self.player.seek((rec.effective_time or 0) + 0.0005)

    @Slot()
    def _on_frames_changed(self):
        self._update_actions()
        recs = self.model.records
        if recs:
            times = [r.effective_time for r in recs if r.effective_time is not None]
            if times:
                lo, hi = min(times), max(times)
                if self._last_range and self._last_range[0] <= lo and hi <= self._last_range[1]:
                    lo, hi = self._last_range  # trecho configurado na extração
                self.plate_panel.update_auto_time_range(f"{format_time(lo)} a {format_time(hi)}")
        if self.rb_manual.isChecked():
            self._update_estimate()
        self._schedule_render()

    @Slot(int)
    def _on_preview_cell_clicked(self, idx):
        self._select_row(idx)
        self.preview.select_cell(idx)

    # ================================================================ prévia
    @Slot()
    def _on_plate_settings_changed(self):
        self.model.refresh_captions()
        self._schedule_render()

    def _schedule_render(self):
        self._render_timer.start()

    def _render_key(self, records, settings):
        return (tuple((r.id, r.caption_override) for r in records), json.dumps(settings.to_dict(), sort_keys=True,
                                                                               default=str))

    @Slot()
    def _do_render(self):
        recs = [copy.copy(r) for r in self.model.records]
        s = self.plate_panel.settings()
        if not recs:
            self._current_layout = None
            self.preview.show_message("Nenhum quadro selecionado.\n\nGere ou capture quadros na aba "
                                      "“1 · Vídeo e extração”.")
            self.lbl_dims.setText("")
            self.lbl_warn.setVisible(False)
            return
        try:
            layout = compute_layout(recs, s)
        except LayoutError as e:
            self._current_layout = None
            self.lbl_dims.setText("")
            self.lbl_warn.setText(f"⚠ {e}")
            self.lbl_warn.setVisible(True)
            self.preview.show_message("A prancha não pode ser montada com estas configurações.\n\n" + str(e))
            return
        self._current_layout = layout
        self.lbl_dims.setText(
            f"Imagem final: {layout.width} × {layout.height} px ({layout.megapixels:.1f} megapixels) · "
            f"{len(recs)} quadro(s) em {layout.columns} coluna(s) × {layout.rows} linha(s) · "
            f"cada quadro com {layout.frame_width} px de largura · impressão a {s.dpi} dpi: "
            f"{layout.width / s.dpi * 2.54:.1f} × {layout.height / s.dpi * 2.54:.1f} cm")
        if layout.warnings:
            self.lbl_warn.setText("⚠ " + "\n⚠ ".join(layout.warnings))
            self.lbl_warn.setVisible(True)
        else:
            self.lbl_warn.setVisible(False)
        self._render_gen += 1
        gen = self._render_gen
        self._render_worker.latest = gen
        self._pending_key = (gen, self._render_key(recs, s))
        self._renderRequest.emit(gen, recs, s)

    @Slot(int, object, object, object)
    def _on_rendered(self, gen, qimg, pil, layout):
        if gen != self._render_gen:
            return
        key = self._pending_key[1] if self._pending_key and self._pending_key[0] == gen else None
        self._last_render = (key, pil, layout)
        self.preview.set_image(qimg, layout)
        rows = self._selected_rows() if self.tabs.currentIndex() == 1 else []
        if rows:
            self.preview.select_cell(rows[0])

    @Slot(int, str)
    def _on_render_failed(self, gen, text):
        if gen == self._render_gen:
            self.preview.show_message(text)

    @Slot()
    def _reset_layout(self):
        self.plate_panel.set_settings(template_settings("Técnico simples", base=self.plate_panel.settings()))
        self._on_plate_settings_changed()

    @Slot(int)
    def _on_tab_changed(self, i):
        if i == 1:
            self.player.player.pause()
            self._schedule_render()

    # ================================================================ exportação
    @Slot()
    def export_plate(self):
        if not self.model.records or self.task is not None:
            return
        recs = [copy.copy(r) for r in self.model.records]
        s = self.plate_panel.settings()
        try:
            layout = compute_layout(recs, s)
        except LayoutError as e:
            QMessageBox.warning(self, "Prancha", str(e))
            return
        fmt = "PNG" if self.cmb_format.currentIndex() == 0 else "JPEG"
        if fmt == "JPEG" and max(layout.width, layout.height) > 65500:
            QMessageBox.warning(self, "JPEG", "A prancha excede 65.500 px, limite do formato JPEG. Use PNG ou "
                                              "reduza a prancha.")
            return
        if layout.megapixels * 1e6 > 80_000_000:
            r = QMessageBox.question(
                self, "Prancha muito grande",
                f"A prancha terá {layout.width} × {layout.height} px ({layout.megapixels:.0f} megapixels). "
                "O arquivo pode ficar pesado e lento para abrir em editores de texto.\n\n"
                "Para reduzir, diminua a largura dos quadros ou aumente o número de colunas. A resolução escolhida "
                "não será reduzida automaticamente.\n\nExportar mesmo assim?")
            if r != QMessageBox.StandardButton.Yes:
                return
        stem = os.path.splitext(self.info.file_name)[0] if self.info else "video"
        ext = ".png" if fmt == "PNG" else ".jpg"
        start_dir = self.qs.value("last_export_dir", os.path.dirname(self.info.path) if self.info else "")
        filt = "Imagem PNG (*.png)" if fmt == "PNG" else "Imagem JPEG (*.jpg *.jpeg)"
        path, _ = QFileDialog.getSaveFileName(self, "Salvar prancha", os.path.join(start_dir, f"{stem}_prancha{ext}"),
                                              filt)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ext
        self.qs.setValue("last_export_dir", os.path.dirname(path))
        base = os.path.splitext(path)[0]
        protected = [self.info.path] if self.info else []
        want_pdf, want_frames = self.chk_pdf.isChecked(), self.chk_frames.isChecked()
        want_txt, want_csv, want_hash = self.chk_txt.isChecked(), self.chk_csv.isChecked(), self.chk_hash.isChecked()
        quality = self.sp_quality.value()
        key = self._render_key(recs, s)
        cached = self._last_render[1] if self._last_render and self._last_render[0] == key else None
        log = self.log
        video_path = self.info.path if self.info else None

        def job(ctx):
            outputs = {}
            steps = 2 + want_pdf + want_frames + want_hash
            step = 0
            if cached is not None:
                img, lay = cached, layout
            else:
                ctx.progress(step, steps, "montando a prancha")
                img, lay = render_plate(recs, s, cache=ImageCache(), is_cancelled=ctx.is_cancelled)
            ctx.check()
            step += 1
            ctx.progress(step, steps, f"gravando {os.path.basename(path)}")
            outputs["plate"] = save_image(img, path, fmt, dpi=s.dpi, jpeg_quality=quality, protected=protected)
            outputs["layout"] = lay
            outputs["extra"] = []
            if want_pdf:
                ctx.check()
                step += 1
                ctx.progress(step, steps, "gravando PDF")
                outputs["extra"].append(save_image(img, base + ".pdf", "PDF", dpi=s.dpi, protected=protected))
            if want_frames:
                ctx.check()
                step += 1
                folder = base + "_quadros"
                ctx.progress(step, steps, "gravando quadros individuais")
                outputs["frames"] = export_frames(recs, folder, os.path.basename(base), apply_geometry=s.apply_geometry,
                                                  protected=protected, is_cancelled=ctx.is_cancelled,
                                                  number_width=number_width(len(recs)))
            if want_hash and video_path:
                ctx.check()
                step += 1
                ctx.progress(step, steps, "calculando SHA-256 do vídeo original")
                outputs["video_hash"] = sha256_file(video_path, is_cancelled=ctx.is_cancelled)
            return outputs

        def ok(out):
            plate: ExportedFile = out["plate"]
            files = [plate.path] + [e.path for e in out["extra"]]
            if "video_hash" in out:
                log.video_hashes.append(HashRecord(out["video_hash"], _dt.datetime.now(), "na exportação"))
                log.add(f"SHA-256 do vídeo calculado (na exportação): {out['video_hash']}")
                self.info_labels["sha"].setText(f"{out['video_hash'][:32]}\n{out['video_hash'][32:]}\n(calculado na exportação)")
            log.add(f"Prancha exportada: {plate.path} ({plate.width} × {plate.height} px, SHA-256 {plate.sha256})")
            for e in out["extra"]:
                log.add(f"Arquivo adicional exportado: {e.path} (SHA-256 {e.sha256})")
            frames = out.get("frames")
            if frames:
                log.add(f"{len(frames)} quadro(s) individual(is) exportado(s) em {os.path.dirname(frames[0][2].path)}")
                files.append(os.path.dirname(frames[0][2].path) + os.sep)
            self._last_exports = {"plate": plate, "layout": out["layout"], "frames": frames,
                                  "extra": out["extra"], "records": recs, "settings": s}
            errors = []
            try:
                if want_txt:
                    write_text(base + "_registro.txt",
                               build_txt(log, recs, s, out["layout"], plate, frames, out["extra"]), protected)
                    files.append(base + "_registro.txt")
                if want_csv:
                    write_text(base + "_registro.csv", build_csv(log, recs, s, out["layout"], plate, frames), protected)
                    files.append(base + "_registro.csv")
            except (VideoError, OSError) as e:
                errors.append(str(e))
            self._export_done_dialog(files, errors, plate)

        self.run_task("Exportando", job, on_success=ok)

    def _export_done_dialog(self, files, errors, plate):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information if not errors else QMessageBox.Icon.Warning)
        box.setWindowTitle("Exportação concluída")
        txt = f"Prancha gravada ({plate.width} × {plate.height} px).\n\nArquivos gerados:\n" + \
              "\n".join(f"• {f}" for f in files)
        if errors:
            txt += "\n\nProblemas:\n" + "\n".join(errors)
        box.setText(txt)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        open_btn = box.addButton("Abrir pasta", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(plate.path)))

    @Slot()
    def save_log_only(self):
        if not self.info:
            return
        stem = os.path.splitext(self.info.file_name)[0]
        start_dir = self.qs.value("last_export_dir", os.path.dirname(self.info.path))
        path, flt = QFileDialog.getSaveFileName(self, "Salvar registro técnico",
                                                os.path.join(start_dir, f"{stem}_registro.txt"),
                                                "Texto (*.txt);;Planilha CSV (*.csv)")
        if not path:
            return
        recs = list(self.model.records)
        s = self.plate_panel.settings()
        exp = self._last_exports if self._last_exports.get("records") is not None and \
            [r.id for r in self._last_exports["records"]] == [r.id for r in recs] else {}
        layout = exp.get("layout") or self._current_layout
        try:
            if path.lower().endswith(".csv") or "CSV" in flt:
                if not path.lower().endswith(".csv"):
                    path += ".csv"
                text = build_csv(self.log, recs, exp.get("settings", s), layout, exp.get("plate"), exp.get("frames"))
            else:
                if not path.lower().endswith(".txt"):
                    path += ".txt"
                text = build_txt(self.log, recs, exp.get("settings", s), layout, exp.get("plate"), exp.get("frames"),
                                 exp.get("extra"))
            write_text(path, text, [self.info.path])
            self.lbl_status.setText(f"Registro técnico salvo: {path}")
        except VideoError as e:
            error_box(self, "Registro técnico", str(e), e.technical)

    # ================================================================ atalhos, arrastar e soltar, encerramento
    def _shortcut_ok(self) -> bool:
        fw = QApplication.focusWidget()
        return self.tabs.currentIndex() == 0 and not isinstance(fw, (QLineEdit, QSpinBox, QDoubleSpinBox))

    @Slot()
    def _sc_play(self):
        if self._shortcut_ok():
            self.player.toggle_play()

    @Slot()
    def _sc_prev(self):
        if self._shortcut_ok():
            self.player.prev_frame()

    @Slot()
    def _sc_next(self):
        if self._shortcut_ok():
            self.player.next_frame()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Delete and isinstance(QApplication.focusWidget(), type(self.frames_view1)):
            self.remove_selected()
            return
        super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            e.acceptProposedAction()
            self.load_video(files[0])

    def closeEvent(self, e):
        if self.task is not None:
            r = QMessageBox.question(self, "Operação em andamento",
                                     "Há uma operação em andamento. Deseja cancelá-la e sair?")
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.task.cancel()
            self.task.thread.wait(10000)
        self.player.shutdown()
        self._render_worker.latest = -1
        self._render_thread.quit()
        self._render_thread.wait(5000)
        tempstore.cleanup_all()
        super().closeEvent(e)
