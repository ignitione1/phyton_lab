"""Режим интерпретатора для самого себя.

В собранном приложении нет отдельного `python.exe`, а код ученика
запускать надо. Решение: приложение умеет работать интерпретатором.
Запущенное с особым флагом, оно не открывает окно, а исполняет
указанный файл и завершается.

Отдельный модуль, потому что он должен подниматься быстро и без Qt:
это дочерний процесс, который стартует на каждый запуск кода.
"""

from __future__ import annotations

import sys

EXEC_FLAG = "--exec-user-code"

# Сколько секунд программе разрешено работать. Передаётся из родителя
# через окружение; если переменной нет, сторож не заводится вовсе —
# так запускаются проверки задания, где время меряет сам родитель.
TIMEOUT_ENV = "PYTHONLAB_RUN_TIMEOUT"

# Код возврата, которым дочерний процесс сообщает: меня остановил сторож.
# 124 — то же число, которым отвечает системная утилита `timeout`.
TIMEOUT_EXIT_CODE = 124


def _force_utf8() -> None:
    """Переводит все три потока на UTF-8.

    Собранное приложение не подхватывает ``PYTHONIOENCODING`` так, как
    обычный Python: кодировку потоков фиксирует загрузчик. Без этого
    любой ``print("привет")`` в дочернем процессе превращается в мусор,
    а на Windows ещё и падает при выводе кириллицы.

    Ввод переключаем наравне с выводом: ученик вводит русские имена
    через ``input()``, и они должны доходить целыми.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def is_child_invocation(argv: list[str]) -> bool:
    """Нас запустили, чтобы исполнить файл ученика, а не показать окно."""
    return len(argv) >= 3 and argv[1] == EXEC_FLAG


def _install_watchdog() -> None:
    """Заводит сторож времени, который не считает ожидание человека.

    Ограничение по времени нужно против вечного цикла. Беда в том, что
    программа, честно ждущая ответа в ``input()``, со стороны выглядит
    точно так же: она ничего не печатает и не заканчивается. Пока сторож
    сидел в родителе и просто смотрел на часы, ученик, который набирал
    ответ на второй вопрос дольше пяти секунд, получал посреди своего
    ответа «программа зациклилась».

    Поэтому сторож живёт здесь, рядом с программой, где видно, чем она
    занята: на время ``input()`` часы останавливаются, а после ответа
    отсчёт начинается заново. Лимит, таким образом, ограничивает работу
    между двумя вопросами, а не терпение человека.
    """
    import builtins
    import os
    import threading
    import time

    try:
        limit = float(os.environ.get(TIMEOUT_ENV, ""))
    except ValueError:
        return
    if limit <= 0:
        return

    # Общее с потоком-сторожем: до каких пор можно работать и не ждём ли
    # мы сейчас человека. Словарь, а не переменные, — чтобы не городить
    # `nonlocal` в двух функциях сразу.
    state = {"deadline": time.monotonic() + limit, "waiting": False}
    real_input = builtins.input

    def input_with_clock_paused(*args, **kwargs):
        state["waiting"] = True
        try:
            return real_input(*args, **kwargs)
        finally:
            state["waiting"] = False
            state["deadline"] = time.monotonic() + limit

    builtins.input = input_with_clock_paused

    def watch() -> None:
        while state["waiting"] or time.monotonic() < state["deadline"]:
            time.sleep(0.05)
        # Выходим жёстко: программа в этот момент занята своим циклом и
        # на вежливую просьбу завершиться не откликнется. Но напечатанное
        # ею сначала выпускаем наружу — иначе ученик не увидит, докуда
        # программа дошла.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        os._exit(TIMEOUT_EXIT_CODE)

    threading.Thread(target=watch, daemon=True).start()


def run_user_script(path: str) -> int:
    """Исполняет файл ученика так, как это сделал бы обычный Python.

    Трассировка при ошибке чистится от наших собственных кадров: ученик
    должен видеть только свои строки, а не внутренности запускающего
    механизма.
    """
    import runpy

    _force_utf8()
    _install_watchdog()

    # Программа ученика должна видеть себя обычным запущенным скриптом.
    sys.argv = [path]

    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    except BaseException:
        _print_clean_traceback(path)
        return 1

    return 0


def _print_clean_traceback(script_path: str) -> None:
    """Печатает ошибку так же, как это сделал бы обычный python."""
    import os
    import traceback

    exc_type, exc_value, exc_tb = sys.exc_info()
    if exc_type is None:
        return

    # Сначала выпускаем всё, что программа успела напечатать: иначе
    # ошибка окажется выше собственного вывода и собьёт с толку.
    try:
        sys.stdout.flush()
    except Exception:
        pass

    script_name = os.path.basename(script_path)

    # Выбрасываем кадры, которые относятся к runpy и к нашему запуску:
    # для ученика они бессмысленны и только пугают.
    frames = [
        frame
        for frame in traceback.extract_tb(exc_tb)
        if os.path.basename(frame.filename) == script_name
        or not _is_internal(frame.filename)
    ]

    sys.stderr.write("Traceback (most recent call last):\n")
    if frames:
        sys.stderr.write("".join(traceback.format_list(frames)))
    sys.stderr.write("".join(traceback.format_exception_only(exc_type, exc_value)))
    sys.stderr.flush()


def _is_internal(filename: str) -> bool:
    """Относится ли кадр к запускающему механизму, а не к коду ученика."""
    marks = ("runpy.py", "child.py", "<frozen ", "importlib")
    return any(mark in filename for mark in marks)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    return run_user_script(argv[2])


# Обычный (не собранный) запуск приходит сюда: там нет .exe, который умеет
# притворяться интерпретатором, и модуль запускают файлом.
if __name__ == "__main__":
    raise SystemExit(main())
