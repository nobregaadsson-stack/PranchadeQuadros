from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTextBrowser, QVBoxLayout)

from .. import APP_NAME, APP_VERSION
from ..core.timefmt import TimeParseError, format_time, parse_time


class TimeDialog(QDialog):
    """Pede um instante do vídeo (HH:MM:SS.mmm)."""

    def __init__(self, parent, title: str, text: str, initial: float, player_time: float | None,
                 duration: float | None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.duration = duration
        self.value: float | None = None
        v = QVBoxLayout(self)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        h = QHBoxLayout()
        self.ed = QLineEdit(format_time(initial, True))
        self.ed.setPlaceholderText("HH:MM:SS.mmm")
        h.addWidget(self.ed, 1)
        if player_time is not None:
            b = QPushButton(f"Posição do reprodutor ({format_time(player_time, True)})")
            b.clicked.connect(lambda: self.ed.setText(format_time(player_time, True)))
            h.addWidget(b)
        v.addLayout(h)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Confirmar")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(460, 120)

    def _accept(self):
        try:
            t = parse_time(self.ed.text())
        except TimeParseError as e:
            QMessageBox.warning(self, "Tempo inválido", str(e))
            return
        if self.duration is not None and t > self.duration:
            QMessageBox.warning(self, "Tempo inválido",
                                f"O tempo informado ultrapassa a duração do vídeo ({format_time(self.duration, True)}).")
            return
        self.value = t
        self.accept()


HELP_HTML = f"""
<h2>{APP_NAME} {APP_VERSION}</h2>
<p><b>Processamento 100% local.</b> Nenhum arquivo, metadado ou informação é enviado pela internet.
O aplicativo não exige conta nem cadastro e não envia telemetria.</p>
<h3>Fluxo de trabalho</h3>
<ol>
<li><b>Selecionar vídeo</b> (botão ou arrastar o arquivo para a janela). O arquivo original é aberto somente para leitura.</li>
<li><b>Trecho de análise</b>: informe o tempo inicial e final (ou use “Marcar início/fim” no reprodutor).</li>
<li><b>Critério</b>: A — intervalo de tempo; B — quantidade de quadros; C — seleção manual (botão
“Capturar quadro exibido” no reprodutor).</li>
<li><b>Gerar quadros</b>. Os quadros aparecem na lista, onde podem ser removidos, reordenados (arrastar ou setas)
e ter a legenda corrigida.</li>
<li>Na aba <b>Prancha e exportação</b>, escolha modelo, colunas, dimensões, legendas e cabeçalho. A prévia mostra
exatamente a imagem que será gravada.</li>
<li><b>Exportar</b> em PNG (recomendado) ou JPEG, opcionalmente com PDF, quadros individuais, registro técnico
(TXT/CSV) e SHA-256.</li>
</ol>
<h3>Tempos</h3>
<p>Para cada instante solicitado é usado o quadro em exibição naquele instante. O <i>tempo efetivo</i> (marca de
tempo do próprio quadro) é o que aparece na legenda; ele pode ser até uma fração de quadro anterior ao solicitado.
Ambos ficam no registro técnico. As legendas truncam o tempo (nunca arredondam para cima).</p>
<h3>Atalhos</h3>
<p>Espaço: reproduzir/pausar · ← →: quadro anterior/seguinte · Ctrl+O: abrir vídeo · Ctrl+E: exportar ·
Delete: remover quadros selecionados · Ctrl + roda do mouse: zoom na prévia.</p>
<h3>Importante</h3>
<p>A prancha é uma composição de quadros extraídos e não uma reprodução integral do vídeo. O registro técnico
documenta as operações realizadas e não constitui certificação de autenticidade.</p>
"""


def show_help(parent):
    d = QDialog(parent)
    d.setWindowTitle("Ajuda")
    v = QVBoxLayout(d)
    tb = QTextBrowser()
    tb.setOpenExternalLinks(False)
    tb.setHtml(HELP_HTML)
    v.addWidget(tb)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    bb.button(QDialogButtonBox.StandardButton.Close).setText("Fechar")
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    d.resize(680, 600)
    d.exec()


def error_box(parent, title: str, message: str, details: str = ""):
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if details:
        box.setDetailedText(details)
    box.exec()
