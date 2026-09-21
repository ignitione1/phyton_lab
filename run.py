"""Точка входа. Запуск: python run.py

У приложения два режима. Обычный открывает окно. Особый — с флагом
``--exec-user-code`` — исполняет указанный файл и выходит; так собранный
.exe работает интерпретатором для кода ученика, и отдельный Python
в поставку класть не нужно.
"""

from __future__ import annotations

import sys

from app.runner.child import is_child_invocation, run_user_script

# Проверка стоит до импорта Qt намеренно: дочерний процесс поднимается
# на каждый запуск кода, и тянуть в него весь интерфейс незачем.
if is_child_invocation(sys.argv):
    raise SystemExit(run_user_script(sys.argv[2]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.course import loader  # noqa: E402
from app.db import database  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    config.ensure_dirs()
    database.connect()
    # Курс живёт в YAML, база — лишь его копия для быстрого доступа.
    # Перенос идемпотентный, прогресс ученика не затрагивается.
    loader.load_into_db()

    app = QApplication(sys.argv)
    app.setApplicationName("Python Lab")
    # Палитра нужна помимо qss: контекстное меню редактора и всплывающие
    # подсказки рисуются системой и иначе остались бы светлыми.
    theme.apply_palette(app)

    # Ключа нет ни в хранилище, ни в .env — предложим ввести.
    # Отказ ничего не ломает: уроки и проверка работают без учителя.
    if not config.has_api_key():
        from app.ui.key_dialog import KeyDialog

        KeyDialog.ask()

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
