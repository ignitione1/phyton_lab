"""Запуск обращений к учителю в стороне от интерфейса.

Ответ идёт секунду-другую, а иногда и дольше. Если ждать его в потоке
окна, приложение замрёт — ни набрать код, ни нажать кнопку. Поэтому
каждый запрос уходит в пул потоков, а текст возвращается сигналами.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from app import config
from app.tutor import llm


class _Signals(QObject):
    chunk = Signal(str)  # очередной кусок текста
    # полный текст, модель, входные, из них кэшированных, выходные, цена в $
    finished = Signal(str, str, int, int, int, float)
    failed = Signal(str)  # человеческое сообщение об ошибке


class TutorTask(QRunnable):
    """Один вопрос учителю."""

    def __init__(
        self,
        system: str,
        user: str,
        model: str | None = None,
        effort: str = config.EFFORT_EXPLAIN,
        max_output_tokens: int = 900,
    ) -> None:
        super().__init__()
        self.signals = _Signals()
        self._system = system
        self._user = user
        self._model = model
        self._effort = effort
        self._max_tokens = max_output_tokens
        self._cancelled = False

    def cancel(self) -> None:
        """Отменяет запрос: ученик ушёл с задания, ответ больше не нужен."""
        self._cancelled = True

    def run(self) -> None:
        try:
            reply = llm.shared().stream(
                system=self._system,
                user=self._user,
                model=self._model,
                effort=self._effort,
                max_output_tokens=self._max_tokens,
                on_chunk=self._emit_chunk,
                should_stop=lambda: self._cancelled,
            )
        except llm.TutorUnavailable as exc:
            self.signals.failed.emit(str(exc))
            return
        except Exception as exc:  # на всякий случай: поток не должен падать молча
            self.signals.failed.emit(f"Неожиданная ошибка: {type(exc).__name__}")
            return

        if self._cancelled:
            return

        if not reply.ok:
            self.signals.failed.emit(reply.error)
            return

        if not reply.text:
            self.signals.failed.emit("Учитель ответил пустотой. Попробуй ещё раз.")
            return

        model = self._model or config.MODEL_LIGHT
        self.signals.finished.emit(
            reply.text,
            model,
            reply.usage.input_tokens,
            reply.usage.cached_tokens,
            reply.usage.output_tokens,
            reply.usage.cost_usd(model),
        )

    def _emit_chunk(self, text: str) -> None:
        if not self._cancelled:
            self.signals.chunk.emit(text)


class TutorService(QObject):
    """Следит, чтобы одновременно шёл только один разговор с учителем."""

    chunk = Signal(str)
    finished = Signal(str, str, int, int, int, float)
    failed = Signal(str)
    started = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._current: TutorTask | None = None

    @property
    def busy(self) -> bool:
        return self._current is not None

    def ask(
        self,
        system: str,
        user: str,
        model: str | None = None,
        effort: str = config.EFFORT_EXPLAIN,
        max_output_tokens: int = 900,
    ) -> None:
        # Новый вопрос отменяет предыдущий: ученику нужен ответ на то,
        # что он спросил сейчас, а не на позапрошлое.
        self.cancel()

        task = TutorTask(system, user, model, effort, max_output_tokens)
        task.signals.chunk.connect(self.chunk)
        task.signals.finished.connect(self._on_finished)
        task.signals.failed.connect(self._on_failed)

        self._current = task
        self.started.emit()
        self._pool.start(task)

    def cancel(self) -> None:
        if self._current is not None:
            self._current.cancel()
            self._current = None

    def _on_finished(
        self,
        text: str,
        model: str,
        tokens_in: int,
        cached_in: int,
        tokens_out: int,
        cost: float,
    ) -> None:
        self._current = None
        self.finished.emit(text, model, tokens_in, cached_in, tokens_out, cost)

    def _on_failed(self, message: str) -> None:
        self._current = None
        self.failed.emit(message)
