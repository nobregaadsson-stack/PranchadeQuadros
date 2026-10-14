"""Lista ordenada dos quadros que compõem a prancha (fonte única para prévia, exportação e registro)."""

from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QAbstractListModel, QMimeData, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView

from ..core.extraction import FrameRecord
from ..core.layout import PlateSettings, caption_for
from ..core.timefmt import format_seconds, format_time
from .qtutil import pil_to_qimage

MIME = "application/x-prancha-linhas"


class FramesModel(QAbstractListModel):
    framesChanged = Signal()

    def __init__(self, settings_getter: Callable[[], PlateSettings], parent=None):
        super().__init__(parent)
        self.records: list[FrameRecord] = []
        self._icons: dict[str, QIcon] = {}
        self._settings = settings_getter

    # ------------------------------------------------------------ leitura
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.records):
            return None
        r = self.records[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return caption_for(r, index.row(), len(self.records), self._settings())
        if role == Qt.ItemDataRole.DecorationRole:
            return self._icon(r)
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [
                f"Tempo solicitado: {format_time(r.requested_time, True)}",
                f"Tempo efetivo do quadro: {format_time(r.effective_time, True)} (fonte: {r.time_source})",
            ]
            if r.offset is not None and abs(r.offset) > 0.0005:
                lines.append(f"Diferença: {format_seconds(r.offset)} s")
            lines.append(f"Origem: {r.origin.value} — {r.criterion}")
            lines.append(f"Dimensões extraídas: {r.width} × {r.height} px")
            if r.caption_override:
                lines.append("Legenda editada manualmente")
            if r.note:
                lines.append(r.note)
            return "\n".join(lines)
        return None

    def _icon(self, r: FrameRecord) -> QIcon:
        ic = self._icons.get(r.id)
        if ic is None:
            if r.thumb is None:
                from ..core.extraction import make_thumb
                from PIL import Image

                with Image.open(r.image_path) as im:
                    r.thumb = make_thumb(im.convert("RGB"), r.rotation, r.sar)
            ic = QIcon(QPixmap.fromImage(pil_to_qimage(r.thumb)))
            self._icons[r.id] = ic
        return ic

    def flags(self, index):
        base = super().flags(index)
        if index.isValid():
            return base | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        return base | Qt.ItemFlag.ItemIsDropEnabled

    # ------------------------------------------------------------ arrastar e soltar (reordenar)
    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction  # evita que a view remova linhas após o drop

    def mimeTypes(self):
        return [MIME]

    def mimeData(self, indexes):
        md = QMimeData()
        rows = sorted({i.row() for i in indexes if i.isValid()})
        md.setData(MIME, json.dumps(rows).encode())
        return md

    def canDropMimeData(self, data, action, row, column, parent):
        return data.hasFormat(MIME)

    def dropMimeData(self, data, action, row, column, parent):
        if not data.hasFormat(MIME):
            return False
        rows = json.loads(bytes(data.data(MIME)).decode())
        if row < 0:
            row = parent.row() if parent.isValid() else len(self.records)
        self.move_rows(rows, row)
        return False  # movimentação já realizada aqui

    # ------------------------------------------------------------ alterações
    def is_time_sorted(self) -> bool:
        t = [r.effective_time if r.effective_time is not None else 0 for r in self.records]
        return all(a <= b for a, b in zip(t, t[1:]))

    def add(self, recs: list[FrameRecord], replace: bool = False):
        self.beginResetModel()
        if replace:
            self.records = []
            self._icons.clear()
        keep_sorted = self.is_time_sorted()
        self.records.extend(recs)
        if keep_sorted:
            self.records.sort(key=lambda r: r.effective_time if r.effective_time is not None else 0)
        self.endResetModel()
        self.framesChanged.emit()

    def clear(self):
        self.beginResetModel()
        self.records = []
        self._icons.clear()
        self.endResetModel()
        self.framesChanged.emit()

    def remove_rows(self, rows: list[int]) -> list[FrameRecord]:
        removed = []
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self.records):
                self.beginRemoveRows(QModelIndex(), row, row)
                removed.append(self.records.pop(row))
                self.endRemoveRows()
        if removed:
            self._refresh_all()
        return list(reversed(removed))

    def move_rows(self, rows: list[int], dest: int):
        rows = [r for r in sorted(set(rows)) if 0 <= r < len(self.records)]
        if not rows:
            return
        moving = [self.records[r] for r in rows]
        before = sum(1 for r in rows if r < dest)
        remaining = [rec for i, rec in enumerate(self.records) if i not in rows]
        dest = max(0, min(dest - before, len(remaining)))
        self.beginResetModel()
        self.records = remaining[:dest] + moving + remaining[dest:]
        self.endResetModel()
        self.framesChanged.emit()

    def move(self, row: int, delta: int) -> int:
        new = row + delta
        if not (0 <= row < len(self.records)) or not (0 <= new < len(self.records)):
            return row
        self.beginResetModel()
        self.records[row], self.records[new] = self.records[new], self.records[row]
        self.endResetModel()
        self.framesChanged.emit()
        return new

    def sort_by_time(self):
        self.beginResetModel()
        self.records.sort(key=lambda r: r.effective_time if r.effective_time is not None else 0)
        self.endResetModel()
        self.framesChanged.emit()

    def set_caption(self, row: int, text: str | None):
        if 0 <= row < len(self.records):
            self.records[row].caption_override = text
            self._refresh_all()

    def replace(self, row: int, rec: FrameRecord):
        if 0 <= row < len(self.records):
            self._icons.pop(self.records[row].id, None)
            self.records[row] = rec
            self._refresh_all()

    def refresh_captions(self):
        if self.records:
            self.dataChanged.emit(self.index(0), self.index(len(self.records) - 1))

    def _refresh_all(self):
        self.refresh_captions()
        self.framesChanged.emit()


def make_frames_view(model: FramesModel, horizontal: bool, parent=None) -> QListView:
    v = QListView(parent)
    v.setModel(model)
    v.setViewMode(QListView.ViewMode.IconMode)
    v.setFlow(QListView.Flow.LeftToRight)
    v.setWrapping(True)
    v.setResizeMode(QListView.ResizeMode.Adjust)
    v.setMovement(QListView.Movement.Static)  # reordenação feita pelo modelo (dropMimeData)
    v.setIconSize(QSize(170, 110) if horizontal else QSize(150, 100))
    v.setGridSize(QSize(196, 160) if horizontal else QSize(176, 150))
    v.setWordWrap(True)
    v.setUniformItemSizes(True)
    v.setSpacing(4)
    v.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    v.setDragEnabled(True)
    v.setAcceptDrops(True)
    v.setDropIndicatorShown(True)
    v.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
    v.setDefaultDropAction(Qt.DropAction.CopyAction)
    return v
