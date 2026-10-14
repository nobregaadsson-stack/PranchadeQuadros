"""Painel de configuração da prancha e visualizador da prévia."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFormLayout, QFrame,
                               QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..core.layout import (ASPECTS, DEFAULT_CAPTION, DEFAULT_FOOTER, PAGE_PRESETS, TEMPLATES, HeaderField,
                           PlateSettings, template_settings)


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedWidth(90)
        self.clicked.connect(self._pick)
        self._paint()

    def color(self) -> str:
        return self._color

    def set_color(self, c: str):
        self._color = c
        self._paint()

    def _paint(self):
        q = QColor(self._color)
        fg = "#000" if q.lightness() > 128 else "#fff"
        self.setText(self._color.upper())
        self.setStyleSheet(f"QPushButton {{ background:{self._color}; color:{fg}; border:1px solid #888; "
                           "border-radius:4px; padding:3px; }}")

    @Slot()
    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color), self, "Escolher cor")
        if c.isValid():
            self._color = c.name()
            self._paint()
            self.colorChanged.emit(self._color)


def _spin(lo, hi, val, suffix=" px", step=1):
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


RESOLUTIONS = [("Padrão — quadros com 640 px de largura", 640), ("Alta — quadros com 1280 px de largura", 1280),
               ("Original do vídeo (largura nativa)", -1), ("Personalizada", 0)]


class PlateSettingsPanel(QScrollArea):
    changed = Signal()
    resetRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._loading = False
        self._native_width = 1280
        self._time_range_auto = ""
        body = QWidget()
        self.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(4, 4, 8, 4)

        # ---- modelo
        g = QGroupBox("Modelo de composição")
        f = QFormLayout(g)
        self.cmb_template = QComboBox()
        self.cmb_template.addItems(TEMPLATES)
        self.cmb_template.setToolTip("Técnico simples: fundo branco, grade, bordas discretas.\n"
                                     "Relatório investigativo: cabeçalho de identificação e margens amplas.\n"
                                     "Alta densidade: mais quadros por imagem.\n"
                                     "Personalizado: todas as propriedades editáveis.")
        f.addRow("Modelo:", self.cmb_template)
        self.btn_reset = QPushButton("Restaurar layout padrão")
        self.btn_reset.setToolTip("Volta às configurações do modelo “Técnico simples”, mantendo os textos do cabeçalho.")
        self.btn_reset.clicked.connect(self.resetRequested.emit)
        f.addRow(self.btn_reset)
        v.addWidget(g)

        # ---- grade
        g = QGroupBox("Grade")
        f = QFormLayout(g)
        presets = QGridLayout()
        self.preset_buttons = []
        for n in (2, 3, 4, 5):
            b = QPushButton(f"{n} col.")
            b.setToolTip(f"Layout predefinido de {n} colunas")
            b.setProperty("cols", n)
            b.clicked.connect(self._on_preset_cols)
            presets.addWidget(b, 0, len(self.preset_buttons))
            self.preset_buttons.append(b)
        f.addRow(presets)
        self.rb_by_cols = QRadioButton("Definir colunas (linhas automáticas)")
        self.rb_by_rows = QRadioButton("Definir linhas (colunas automáticas)")
        self.rb_by_cols.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_by_cols)
        grp.addButton(self.rb_by_rows)
        f.addRow(self.rb_by_cols)
        f.addRow(self.rb_by_rows)
        self.sp_cols = _spin(1, 20, 3, suffix="")
        self.sp_rows = _spin(1, 200, 2, suffix="")
        f.addRow("Colunas (quadros/linha):", self.sp_cols)
        f.addRow("Linhas:", self.sp_rows)
        self.lbl_grid = QLabel("")
        self.lbl_grid.setObjectName("hint")
        f.addRow(self.lbl_grid)
        v.addWidget(g)

        # ---- tamanho
        g = QGroupBox("Dimensões da imagem final")
        f = QFormLayout(g)
        self.rb_auto = QRadioButton("Pela largura de cada quadro")
        self.rb_fixed = QRadioButton("Dimensões fixas da imagem (px)")
        self.rb_auto.setChecked(True)
        grp2 = QButtonGroup(self)
        grp2.addButton(self.rb_auto)
        grp2.addButton(self.rb_fixed)
        f.addRow(self.rb_auto)
        self.cmb_resolution = QComboBox()
        for label, _ in RESOLUTIONS:
            self.cmb_resolution.addItem(label)
        f.addRow("Resolução:", self.cmb_resolution)
        self.sp_frame_w = _spin(40, 8000, 640, step=20)
        f.addRow("Largura de cada quadro:", self.sp_frame_w)
        f.addRow(self.rb_fixed)
        self.cmb_page = QComboBox()
        self.cmb_page.addItems(list(PAGE_PRESETS.keys()) + ["Personalizada"])
        f.addRow("Tamanho:", self.cmb_page)
        wh = QHBoxLayout()
        self.sp_cw = _spin(200, 60000, 2480)
        self.sp_ch = _spin(200, 60000, 3508)
        wh.addWidget(self.sp_cw)
        wh.addWidget(QLabel("×"))
        wh.addWidget(self.sp_ch)
        f.addRow("Largura × altura:", wh)
        orient = QHBoxLayout()
        self.rb_portrait = QRadioButton("Retrato")
        self.rb_landscape = QRadioButton("Paisagem")
        self.rb_portrait.setChecked(True)
        grp3 = QButtonGroup(self)
        grp3.addButton(self.rb_portrait)
        grp3.addButton(self.rb_landscape)
        orient.addWidget(self.rb_portrait)
        orient.addWidget(self.rb_landscape)
        orient.addStretch(1)
        f.addRow("Orientação:", orient)
        self.sp_dpi = _spin(72, 1200, 300, suffix=" dpi")
        self.sp_dpi.setToolTip("Resolução de impressão gravada no arquivo (não altera os pixels).")
        f.addRow("DPI (impressão):", self.sp_dpi)
        v.addWidget(g)

        # ---- quadros
        g = QGroupBox("Quadros")
        f = QFormLayout(g)
        self.cmb_fit = QComboBox()
        self.cmb_fit.addItems(["Manter proporções originais", "Área padronizada com margens"])
        f.addRow("Ajuste:", self.cmb_fit)
        self.cmb_aspect = QComboBox()
        self.cmb_aspect.addItems(list(ASPECTS.keys()))
        f.addRow("Proporção da área:", self.cmb_aspect)
        self.btn_box_color = ColorButton("#E6E6E6")
        f.addRow("Cor das margens da área:", self.btn_box_color)
        self.cmb_halign = QComboBox()
        self.cmb_halign.addItems(["Esquerda", "Centro", "Direita"])
        f.addRow("Alinhamento horizontal:", self.cmb_halign)
        self.cmb_valign = QComboBox()
        self.cmb_valign.addItems(["Topo", "Centro", "Base"])
        f.addRow("Alinhamento vertical:", self.cmb_valign)
        self.cmb_lastrow = QComboBox()
        self.cmb_lastrow.addItems(["Última linha à esquerda", "Última linha centralizada"])
        f.addRow("Linha incompleta:", self.cmb_lastrow)
        self.chk_geometry = QCheckBox("Aplicar rotação e proporção de exibição")
        self.chk_geometry.setChecked(True)
        self.chk_geometry.setToolTip("Aplica a rotação gravada pelo celular/câmera e a proporção de pixel, como um "
                                     "reprodutor de vídeo. A correção é registrada no registro técnico.")
        f.addRow(self.chk_geometry)
        v.addWidget(g)

        # ---- espaçamento e bordas
        g = QGroupBox("Espaçamento, bordas e cores")
        f = QFormLayout(g)
        self.sp_spacing = _spin(0, 500, 24)
        self.sp_rowspacing = _spin(0, 500, 28)
        self.sp_margin = _spin(0, 1000, 48)
        f.addRow("Espaço entre colunas:", self.sp_spacing)
        f.addRow("Espaço entre linhas:", self.sp_rowspacing)
        f.addRow("Margens externas:", self.sp_margin)
        self.sp_border = _spin(0, 40, 1)
        f.addRow("Espessura da borda:", self.sp_border)
        self.btn_border_color = ColorButton("#7F7F7F")
        f.addRow("Cor da borda:", self.btn_border_color)
        self.btn_bg = ColorButton("#FFFFFF")
        f.addRow("Cor de fundo:", self.btn_bg)
        self.btn_text_color = ColorButton("#111111")
        f.addRow("Cor do texto:", self.btn_text_color)
        v.addWidget(g)

        # ---- legendas
        g = QGroupBox("Legendas")
        f = QFormLayout(g)
        self.cmb_cap_pos = QComboBox()
        self.cmb_cap_pos.addItems(["Abaixo do quadro", "Acima do quadro", "Sobreposta à imagem (canto inferior)",
                                   "Sem legenda"])
        self.cmb_cap_pos.setToolTip("Por padrão a legenda fica FORA da imagem extraída. A opção sobreposta cobre "
                                    "parte do conteúdo original e só deve ser usada quando desejado.")
        f.addRow("Posição:", self.cmb_cap_pos)
        self.ed_caption = QLineEdit(DEFAULT_CAPTION)
        self.ed_caption.setToolTip("Use {n} para o número do quadro e {tempo} para o tempo no vídeo.")
        f.addRow("Formato:", self.ed_caption)
        self.chk_ms = QCheckBox("Exibir milissegundos (HH:MM:SS.mmm)")
        f.addRow(self.chk_ms)
        self.chk_cap_bold = QCheckBox("Negrito")
        self.chk_cap_bold.setChecked(True)
        f.addRow(self.chk_cap_bold)
        self.sp_cap_size = _spin(6, 200, 20, suffix=" pt")
        f.addRow("Tamanho da legenda:", self.sp_cap_size)
        self.sp_gap = _spin(0, 100, 8)
        f.addRow("Distância legenda–quadro:", self.sp_gap)
        v.addWidget(g)

        # ---- cabeçalho
        g = QGroupBox("Cabeçalho")
        g.setCheckable(True)
        g.setChecked(False)
        self.grp_header = g
        gl = QGridLayout(g)
        self.chk_title = QCheckBox("Título")
        self.chk_title.setChecked(True)
        self.ed_title = QLineEdit("PRANCHA DE QUADROS DE VÍDEO")
        gl.addWidget(self.chk_title, 0, 0)
        gl.addWidget(self.ed_title, 0, 1)
        self.header_widgets: dict[str, tuple[QCheckBox, QWidget]] = {}
        row = 1
        for hf in PlateSettings().header_fields:
            chk = QCheckBox(hf.label)
            chk.setChecked(True)
            if hf.key == "notes":
                ed = QPlainTextEdit()
                ed.setFixedHeight(56)
            else:
                ed = QLineEdit()
            if hf.key == "analysis_dt":
                ed.setToolTip("Preenchido com a data e hora do sistema. Confirme ou corrija antes de exportar.")
            if hf.key == "time_range":
                ed.setToolTip("Preenchido automaticamente com o intervalo coberto pelos quadros. Pode ser editado.")
            gl.addWidget(chk, row, 0)
            gl.addWidget(ed, row, 1)
            self.header_widgets[hf.key] = (chk, ed)
            row += 1
        self.sp_title_size = _spin(6, 300, 32, suffix=" pt")
        self.sp_header_size = _spin(6, 200, 18, suffix=" pt")
        gl.addWidget(QLabel("Tamanho do título:"), row, 0)
        gl.addWidget(self.sp_title_size, row, 1)
        gl.addWidget(QLabel("Tamanho dos campos:"), row + 1, 0)
        gl.addWidget(self.sp_header_size, row + 1, 1)
        hint = QLabel("Todos os campos são opcionais. Nada é inserido automaticamente além do que você confirmar "
                      "(sem brasões, logotipos ou selos).")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        gl.addWidget(hint, row + 2, 0, 1, 2)
        v.addWidget(g)

        # ---- rodapé
        g = QGroupBox("Nota de identificação (rodapé)")
        g.setCheckable(True)
        g.setChecked(True)
        self.grp_footer = g
        fl = QVBoxLayout(g)
        self.ed_footer = QPlainTextEdit(DEFAULT_FOOTER)
        self.ed_footer.setFixedHeight(70)
        fl.addWidget(self.ed_footer)
        h = QHBoxLayout()
        h.addWidget(QLabel("Tamanho:"))
        self.sp_footer_size = _spin(6, 100, 14, suffix=" pt")
        h.addWidget(self.sp_footer_size)
        h.addStretch(1)
        fl.addLayout(h)
        v.addWidget(g)
        v.addStretch(1)

        for w in self.findChildren(QComboBox):
            w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(8)
        self._connect_all()
        self.set_settings(PlateSettings())

    # ------------------------------------------------------------------ ligação
    def _connect_all(self):
        for w in self.findChildren(QSpinBox):
            w.valueChanged.connect(self._on_any_change)
        for w in self.findChildren(QComboBox):
            if w is self.cmb_template:
                w.currentIndexChanged.connect(self._on_template)
            elif w is self.cmb_resolution:
                w.currentIndexChanged.connect(self._on_resolution)
            elif w is self.cmb_page:
                w.currentIndexChanged.connect(self._on_page)
            else:
                w.currentIndexChanged.connect(self._on_any_change)
        for w in self.findChildren(QCheckBox):
            w.toggled.connect(self._on_any_change)
        for w in self.findChildren(QRadioButton):
            w.toggled.connect(self._on_any_change)
        for w in self.findChildren(QLineEdit):
            w.editingFinished.connect(self._on_any_change)
        for w in self.findChildren(QPlainTextEdit):
            w.textChanged.connect(self._on_any_change)
        for w in self.findChildren(ColorButton):
            w.colorChanged.connect(self._on_any_change)
        self.grp_header.toggled.connect(self._on_any_change)
        self.grp_footer.toggled.connect(self._on_any_change)
        self.sp_frame_w.valueChanged.connect(self._sync_resolution_combo)
        self.sp_cw.valueChanged.connect(self._sync_page_combo)
        self.sp_ch.valueChanged.connect(self._sync_page_combo)

    @Slot()
    def _on_any_change(self, *_):
        if self._loading:
            return
        if self.cmb_template.currentText() != "Personalizado":
            self.cmb_template.blockSignals(True)
            self.cmb_template.setCurrentText("Personalizado")
            self.cmb_template.blockSignals(False)
        self._update_enabled()
        self.changed.emit()

    @Slot(int)
    def _on_template(self, _i):
        if self._loading:
            return
        name = self.cmb_template.currentText()
        if name == "Personalizado":
            self.changed.emit()
            return
        s = template_settings(name, base=self.settings())
        self.set_settings(s)
        self.changed.emit()

    @Slot()
    def _on_preset_cols(self):
        n = self.sender().property("cols")
        self._loading = True
        self.rb_by_cols.setChecked(True)
        self.sp_cols.setValue(int(n))
        self._loading = False
        self._on_any_change()

    @Slot(int)
    def _on_resolution(self, idx):
        if self._loading:
            return
        val = RESOLUTIONS[idx][1]
        self._loading = True
        self.rb_auto.setChecked(True)
        if val == -1:
            self.sp_frame_w.setValue(self._native_width)
        elif val > 0:
            self.sp_frame_w.setValue(val)
        self._loading = False
        self._on_any_change()

    @Slot(int)
    def _on_page(self, idx):
        if self._loading:
            return
        name = self.cmb_page.currentText()
        self._loading = True
        self.rb_fixed.setChecked(True)
        if name in PAGE_PRESETS:
            w, h = PAGE_PRESETS[name]
            self.sp_cw.setValue(w)
            self.sp_ch.setValue(h)
        self._loading = False
        self._on_any_change()

    @Slot()
    def _sync_resolution_combo(self, *_):
        val = self.sp_frame_w.value()
        idx = 3
        for i, (_, w) in enumerate(RESOLUTIONS):
            if (w == -1 and val == self._native_width) or w == val:
                idx = i
                break
        self.cmb_resolution.blockSignals(True)
        self.cmb_resolution.setCurrentIndex(idx)
        self.cmb_resolution.blockSignals(False)

    @Slot()
    def _sync_page_combo(self, *_):
        cur = tuple(sorted((self.sp_cw.value(), self.sp_ch.value())))
        name = "Personalizada"
        for k, wh in PAGE_PRESETS.items():
            if tuple(sorted(wh)) == cur:
                name = k
                break
        self.cmb_page.blockSignals(True)
        self.cmb_page.setCurrentText(name)
        self.cmb_page.blockSignals(False)

    def _update_enabled(self):
        by_cols = self.rb_by_cols.isChecked()
        self.sp_cols.setEnabled(by_cols)
        self.sp_rows.setEnabled(not by_cols)
        auto = self.rb_auto.isChecked()
        self.sp_frame_w.setEnabled(auto)
        self.cmb_resolution.setEnabled(auto)
        for w in (self.cmb_page, self.sp_cw, self.sp_ch, self.rb_portrait, self.rb_landscape):
            w.setEnabled(not auto)
        box = self.cmb_fit.currentIndex() == 1
        self.cmb_aspect.setEnabled(box)
        self.btn_box_color.setEnabled(box)

    # ------------------------------------------------------------------ leitura/escrita
    def set_native_width(self, w: int | None):
        if w:
            self._native_width = int(w)
            self._sync_resolution_combo()

    def set_header_value(self, key: str, value: str, only_if_empty: bool = False):
        chk, ed = self.header_widgets[key]
        cur = ed.toPlainText() if isinstance(ed, QPlainTextEdit) else ed.text()
        if only_if_empty and cur.strip():
            return
        self._loading = True
        if isinstance(ed, QPlainTextEdit):
            ed.setPlainText(value)
        else:
            ed.setText(value)
        self._loading = False

    def update_auto_time_range(self, text: str):
        """Atualiza o intervalo analisado, salvo se o usuário tiver digitado outro valor."""
        chk, ed = self.header_widgets["time_range"]
        if ed.text().strip() in ("", self._time_range_auto):
            self._loading = True
            ed.setText(text)
            self._loading = False
        self._time_range_auto = text

    def settings(self) -> PlateSettings:
        s = PlateSettings()
        s.template = self.cmb_template.currentText()
        s.grid_by = "columns" if self.rb_by_cols.isChecked() else "rows"
        s.columns = self.sp_cols.value()
        s.rows = self.sp_rows.value()
        s.size_mode = "auto" if self.rb_auto.isChecked() else "fixed"
        s.frame_width = self.sp_frame_w.value()
        s.canvas_width = self.sp_cw.value()
        s.canvas_height = self.sp_ch.value()
        s.orientation = "portrait" if self.rb_portrait.isChecked() else "landscape"
        s.dpi = self.sp_dpi.value()
        s.fit_mode = "original" if self.cmb_fit.currentIndex() == 0 else "box"
        s.box_aspect = ASPECTS[self.cmb_aspect.currentText()]
        s.box_color = self.btn_box_color.color()
        s.h_align = ["left", "center", "right"][self.cmb_halign.currentIndex()]
        s.v_align = ["top", "center", "bottom"][self.cmb_valign.currentIndex()]
        s.last_row_align = ["left", "center"][self.cmb_lastrow.currentIndex()]
        s.apply_geometry = self.chk_geometry.isChecked()
        s.spacing = self.sp_spacing.value()
        s.row_spacing = self.sp_rowspacing.value()
        s.margin = self.sp_margin.value()
        s.border_width = self.sp_border.value()
        s.border_color = self.btn_border_color.color()
        s.background = self.btn_bg.color()
        s.text_color = self.btn_text_color.color()
        s.caption_position = ["below", "above", "overlay", "none"][self.cmb_cap_pos.currentIndex()]
        s.caption_template = self.ed_caption.text() or DEFAULT_CAPTION
        s.show_ms = self.chk_ms.isChecked()
        s.caption_bold = self.chk_cap_bold.isChecked()
        s.caption_font_size = self.sp_cap_size.value()
        s.caption_gap = self.sp_gap.value()
        s.header_enabled = self.grp_header.isChecked()
        s.show_title = self.chk_title.isChecked()
        s.title = self.ed_title.text()
        s.title_font_size = self.sp_title_size.value()
        s.header_font_size = self.sp_header_size.value()
        fields = []
        for hf in s.header_fields:
            chk, ed = self.header_widgets[hf.key]
            val = ed.toPlainText() if isinstance(ed, QPlainTextEdit) else ed.text()
            fields.append(HeaderField(hf.key, hf.label, val, chk.isChecked()))
        s.header_fields = fields
        s.footer_enabled = self.grp_footer.isChecked()
        s.footer_text = self.ed_footer.toPlainText()
        s.footer_font_size = self.sp_footer_size.value()
        return s

    def set_settings(self, s: PlateSettings):
        self._loading = True
        try:
            self.cmb_template.setCurrentText(s.template)
            self.rb_by_cols.setChecked(s.grid_by == "columns")
            self.rb_by_rows.setChecked(s.grid_by != "columns")
            self.sp_cols.setValue(s.columns)
            self.sp_rows.setValue(s.rows)
            self.rb_auto.setChecked(s.size_mode == "auto")
            self.rb_fixed.setChecked(s.size_mode != "auto")
            self.sp_frame_w.setValue(s.frame_width)
            self.sp_cw.setValue(s.canvas_width)
            self.sp_ch.setValue(s.canvas_height)
            self.rb_portrait.setChecked(s.orientation == "portrait")
            self.rb_landscape.setChecked(s.orientation != "portrait")
            self.sp_dpi.setValue(s.dpi)
            self.cmb_fit.setCurrentIndex(0 if s.fit_mode == "original" else 1)
            for k, a in ASPECTS.items():
                if abs(a - s.box_aspect) < 1e-6:
                    self.cmb_aspect.setCurrentText(k)
            self.btn_box_color.set_color(s.box_color)
            self.cmb_halign.setCurrentIndex(["left", "center", "right"].index(s.h_align))
            self.cmb_valign.setCurrentIndex(["top", "center", "bottom"].index(s.v_align))
            self.cmb_lastrow.setCurrentIndex(["left", "center"].index(s.last_row_align))
            self.chk_geometry.setChecked(s.apply_geometry)
            self.sp_spacing.setValue(s.spacing)
            self.sp_rowspacing.setValue(s.row_spacing)
            self.sp_margin.setValue(s.margin)
            self.sp_border.setValue(s.border_width)
            self.btn_border_color.set_color(s.border_color)
            self.btn_bg.set_color(s.background)
            self.btn_text_color.set_color(s.text_color)
            self.cmb_cap_pos.setCurrentIndex(["below", "above", "overlay", "none"].index(s.caption_position))
            self.ed_caption.setText(s.caption_template)
            self.chk_ms.setChecked(s.show_ms)
            self.chk_cap_bold.setChecked(s.caption_bold)
            self.sp_cap_size.setValue(s.caption_font_size)
            self.sp_gap.setValue(s.caption_gap)
            self.grp_header.setChecked(s.header_enabled)
            self.chk_title.setChecked(s.show_title)
            self.ed_title.setText(s.title)
            self.sp_title_size.setValue(s.title_font_size)
            self.sp_header_size.setValue(s.header_font_size)
            for hf in s.header_fields:
                if hf.key in self.header_widgets:
                    chk, ed = self.header_widgets[hf.key]
                    chk.setChecked(hf.show)
                    if isinstance(ed, QPlainTextEdit):
                        if ed.toPlainText() != hf.value:
                            ed.setPlainText(hf.value)
                    else:
                        ed.setText(hf.value)
            self.grp_footer.setChecked(s.footer_enabled)
            if self.ed_footer.toPlainText() != s.footer_text:
                self.ed_footer.setPlainText(s.footer_text)
            self.sp_footer_size.setValue(s.footer_font_size)
        finally:
            self._loading = False
        self._sync_resolution_combo()
        self._sync_page_combo()
        self._update_enabled()

    def adjust(self, columns_delta: int = 0, width_factor: float = 1.0, spacing_delta: int = 0):
        """Ajustes rápidos usados pela barra da prévia."""
        self._loading = True
        if columns_delta:
            if self.rb_by_cols.isChecked():
                self.sp_cols.setValue(max(1, self.sp_cols.value() + columns_delta))
            else:
                self.sp_rows.setValue(max(1, self.sp_rows.value() - columns_delta))
        if width_factor != 1.0:
            if self.rb_auto.isChecked():
                self.sp_frame_w.setValue(int(round(self.sp_frame_w.value() * width_factor / 10)) * 10)
            else:
                self.sp_cw.setValue(int(round(self.sp_cw.value() * width_factor)))
                self.sp_ch.setValue(int(round(self.sp_ch.value() * width_factor)))
        if spacing_delta:
            self.sp_spacing.setValue(max(0, self.sp_spacing.value() + spacing_delta))
            self.sp_rowspacing.setValue(max(0, self.sp_rowspacing.value() + spacing_delta))
        self._loading = False
        self._on_any_change()


class PlatePreview(QGraphicsView):
    cellClicked = Signal(int)
    cellDoubleClicked = Signal(int)
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QBrush(QColor("#5b6168")))
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._pix_item: QGraphicsPixmapItem | None = None
        self._sel_item: QGraphicsRectItem | None = None
        self._layout = None
        self._fit = True
        self._message_item = None

    def show_message(self, text: str):
        self.scene().clear()
        self._pix_item = None
        self._sel_item = None
        self._layout = None
        self._message_item = self.scene().addText(text)
        self._message_item.setDefaultTextColor(QColor("#f0f0f0"))
        self.resetTransform()

    def set_image(self, qimg: QImage, layout):
        first = self._pix_item is None
        self.scene().clear()
        self._sel_item = None
        self._pix_item = self.scene().addPixmap(QPixmap.fromImage(qimg))
        self._pix_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().setSceneRect(QRectF(0, 0, qimg.width(), qimg.height()))
        self._layout = layout
        if first or self._fit:
            self.fit()

    def select_cell(self, index: int):
        if self._sel_item is not None:
            self.scene().removeItem(self._sel_item)
            self._sel_item = None
        if not self._layout or index < 0:
            return
        for c in self._layout.cells:
            if c.index == index:
                x0, y0, x1, y1 = c.cell_rect
                pen = QPen(QColor("#1f8fff"))
                pen.setWidthF(max(3.0, 3.0 / max(self.transform().m11(), 0.01)))
                pen.setStyle(Qt.PenStyle.DashLine)
                self._sel_item = self.scene().addRect(QRectF(x0 - 4, y0 - 4, x1 - x0 + 8, y1 - y0 + 8), pen)
                self.ensureVisible(self._sel_item, 20, 20)
                break

    def _cell_at(self, pos) -> int:
        if not self._layout:
            return -1
        p = self.mapToScene(pos)
        for c in self._layout.cells:
            x0, y0, x1, y1 = c.cell_rect
            if x0 <= p.x() <= x1 and y0 <= p.y() <= y1:
                return c.index
        return -1

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            idx = self._cell_at(e.position().toPoint())
            if idx >= 0:
                self.cellClicked.emit(idx)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        idx = self._cell_at(e.position().toPoint())
        if idx >= 0:
            self.cellDoubleClicked.emit(idx)
        super().mouseDoubleClickEvent(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)
        else:
            super().wheelEvent(e)

    def zoom(self, factor: float):
        self._fit = False
        cur = self.transform().m11()
        new = max(0.02, min(8.0, cur * factor))
        self.setTransform(self.transform().fromScale(new, new))
        self.zoomChanged.emit(new)

    def actual_size(self):
        self._fit = False
        self.resetTransform()
        self.zoomChanged.emit(1.0)

    def fit(self):
        self._fit = True
        if self._pix_item is not None:
            self.fitInView(self._pix_item, Qt.AspectRatioMode.KeepAspectRatio)
            self.zoomChanged.emit(self.transform().m11())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self.fit()
