"""Execução de tarefas demoradas fora da thread da interface.

Atenção (PySide6): somente métodos definidos no corpo da classe e decorados com @Slot
são executados na thread do objeto receptor. Por isso os sinais destes workers são
sempre conectados a slots declarados nas classes da interface.
"""

from __future__ import annotations

import threading
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot


class TaskCancelled(Exception):
    pass


class TaskContext:
    """Passado à função da tarefa: progresso e verificação de cancelamento."""

    def __init__(self, worker: "TaskWorker"):
        self._worker = worker
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self):
        if self._cancel.is_set():
            raise TaskCancelled()

    def progress(self, done: int, total: int, text: str = ""):
        self._worker.progress.emit(int(done), int(total), text)

    def emit_item(self, obj):
        self._worker.item.emit(obj)


class TaskWorker(QObject):
    progress = Signal(int, int, str)
    item = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)  # exceção
    cancelled = Signal()
    done = Signal()

    def __init__(self, fn: Callable[[TaskContext], object]):
        super().__init__()
        self._fn = fn
        self.ctx = TaskContext(self)

    @Slot()
    def run(self):
        try:
            result = self._fn(self.ctx)
            if self.ctx.is_cancelled():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)
        except TaskCancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001 - toda falha vira mensagem ao usuário
            e.traceback_text = traceback.format_exc()
            self.failed.emit(e)
        finally:
            self.done.emit()


class TaskHandle:
    def __init__(self, thread: QThread, worker: TaskWorker, title: str):
        self.thread = thread
        self.worker = worker
        self.title = title

    def cancel(self):
        self.worker.ctx.cancel()


def start_task(fn: Callable[[TaskContext], object], title: str, parent: QObject) -> TaskHandle:
    """Cria a thread e o worker; o chamador conecta os sinais ANTES de chamar ``handle.thread.start()``."""
    thread = QThread(parent)
    worker = TaskWorker(fn)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return TaskHandle(thread, worker, title)


class RenderWorker(QObject):
    """Renderiza a prévia da prancha em thread própria; descarta pedidos superados."""

    rendered = Signal(int, object, object, object)  # geração, QImage, PIL.Image, layout
    failed = Signal(int, str)

    def __init__(self):
        super().__init__()
        from ..core.layout import ImageCache

        self.cache = ImageCache()
        self.latest = 0

    @Slot(int, object, object)
    def render(self, gen: int, records, settings):
        if gen != self.latest:
            return  # já existe pedido mais novo
        from ..core.layout import LayoutError, render_plate
        from .qtutil import pil_to_qimage

        try:
            img, layout = render_plate(records, settings, cache=self.cache,
                                       is_cancelled=lambda: gen != self.latest)
            if gen != self.latest:
                return
            self.rendered.emit(gen, pil_to_qimage(img), img, layout)
        except InterruptedError:
            return
        except LayoutError as e:
            self.failed.emit(gen, str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(gen, f"Erro ao montar a prancha: {e}")
