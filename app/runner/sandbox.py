"""Запуск кода ученика.

Два режима, намеренно разные:

* :class:`CodeRunner` — интерактивный, для кнопки «Запустить». Работает на
  ``QProcess``: не морозит интерфейс, отдаёт вывод по мере появления и
  позволяет отвечать на ``input()`` прямо в консоли.
* :func:`run_batch` — пакетный, для проверки задания тестами. Синхронный,
  stdin подаётся целиком заранее.

Изоляция здесь бытовая, а не защитная: код пишет сам ученик и атаковать ему
некого. Мы страхуемся от зависания и от заваленного выводом интерфейса.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from app import config
from app.runner import child

SCRIPT_NAME = "solution.py"
# Отдельное имя для кода ученика, когда запускается не он сам, а обёртка
# вокруг него: иначе обёртка перезаписала бы файл, который собирается читать.
USER_CODE_NAME = "user_code.py"


def _prepare_script(code: str, name: str = SCRIPT_NAME) -> Path:
    """Кладёт код в рабочий каталог и возвращает путь к файлу."""
    config.ensure_dirs()
    path = config.WORKDIR / name
    path.write_text(code, encoding="utf-8")
    return path


def _env_vars() -> dict[str, str]:
    """Окружение дочернего процесса.

    ``PYTHONIOENCODING`` обязателен: без него на Windows консоль дочернего
    процесса берёт cp1251 и любой ``print("привет")`` превращается в мусор.
    ``PYTHONUNBUFFERED`` нужен, чтобы вывод появлялся сразу, а не в конце.
    """
    return {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


# --------------------------------------------------------------------------
# Пакетный запуск — для проверки задания тестами
# --------------------------------------------------------------------------


@dataclass
class RunResult:
    """Итог одного запуска."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_batch(
    code: str,
    stdin_data: str = "",
    timeout: float | None = None,
) -> RunResult:
    """Запускает код и дожидается конца. Блокирующий — не звать из UI-потока."""
    script = _prepare_script(code)
    timeout = timeout if timeout is not None else config.CHECK_TIMEOUT_SEC

    import os

    env = os.environ.copy()
    env.update(_env_vars())

    try:
        proc = subprocess.run(
            [*config.python_command(), str(script)],
            input=stdin_data,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(config.WORKDIR),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return RunResult(
            stdout=_clip(exc.stdout or ""),
            stderr="",
            exit_code=-1,
            timed_out=True,
        )

    return RunResult(
        stdout=_clip(proc.stdout),
        stderr=_clip(proc.stderr),
        exit_code=proc.returncode,
        timed_out=False,
    )


def _clip(text: str) -> str:
    """Обрезает вывод, чтобы `print` в вечном цикле не подвесил интерфейс."""
    if text is None:
        return ""
    if len(text) <= config.MAX_OUTPUT_CHARS:
        return text
    return text[: config.MAX_OUTPUT_CHARS] + "\n\n[...вывод обрезан...]"


# --------------------------------------------------------------------------
# Интерактивный запуск — для кнопки «Запустить»
# --------------------------------------------------------------------------


class CodeRunner(QObject):
    """Асинхронный запуск с поддержкой ``input()``.

    Срок жизни программы здесь не отмеряется: его держит сам дочерний
    процесс (см. :func:`app.runner.child._install_watchdog`). Отсюда не
    видно, работает программа или ждёт ответа человека, а разница
    решающая: ученик, набирающий ответ на вопрос, не должен получить
    «программа зациклилась». Если сторож всё же сработал, дочерний
    процесс выходит с кодом ``child.TIMEOUT_EXIT_CODE``.

    Сигналы:
        output: очередной кусок вывода (stdout и stderr вперемешку, как в консоли)
        finished: (код возврата, был ли таймаут)
    """

    output = Signal(str)
    finished = Signal(int, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._chars_sent = 0

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start(self, code: str) -> None:
        """Запускает код. Предыдущий запуск, если он висел, снимается."""
        self.stop()
        script = _prepare_script(code)

        self._chars_sent = 0

        proc = QProcess(self)
        # stderr сливаем в общий поток: ученик видит вывод и ошибку в том же
        # порядке, в каком они произошли, — как в настоящем терминале.
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setWorkingDirectory(str(config.WORKDIR))

        env = QProcessEnvironment.systemEnvironment()
        for key, value in _env_vars().items():
            env.insert(key, value)
        # Сколько программе разрешено работать, решает она сама — отсюда
        # уходит только само число.
        env.insert(child.TIMEOUT_ENV, str(config.RUN_TIMEOUT_SEC))
        proc.setProcessEnvironment(env)

        proc.readyReadStandardOutput.connect(self._on_output)
        proc.finished.connect(self._on_finished)

        self._proc = proc
        command = config.python_command()
        proc.start(command[0], [*command[1:], str(script)])

    def send_input(self, text: str) -> None:
        """Отправляет строку в ``stdin`` — ответ ученика на ``input()``."""
        if not self.is_running or self._proc is None:
            return
        self._proc.write((text + "\n").encode("utf-8"))

    def stop(self) -> None:
        """Снимает процесс, если он ещё жив.

        Сигналы отвязываются до того, как процесс будет убит: иначе
        ``kill`` порождает ещё одно «программа завершилась» — от этого
        сообщение об остановке печаталось дважды.
        """
        proc, self._proc = self._proc, None
        if proc is None:
            return

        proc.readyReadStandardOutput.disconnect()
        proc.finished.disconnect()
        if proc.state() != QProcess.NotRunning:
            proc.kill()
            proc.waitForFinished(1000)
        proc.deleteLater()

    # -- внутреннее --------------------------------------------------------

    def _on_output(self) -> None:
        if self._proc is None:
            return
        chunk = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not chunk:
            return
        if self._chars_sent >= config.MAX_OUTPUT_CHARS:
            return
        self._chars_sent += len(chunk)
        if self._chars_sent >= config.MAX_OUTPUT_CHARS:
            chunk += "\n\n[...вывод обрезан, программа остановлена...]"
            self.output.emit(chunk)
            self.stop()
            self.finished.emit(-1, False)
            return
        self.output.emit(chunk)

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self._proc = None
        self.finished.emit(exit_code, exit_code == child.TIMEOUT_EXIT_CODE)
