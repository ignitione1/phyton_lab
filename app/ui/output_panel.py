"""Консоль: вывод программы и поле ответа на ``input()``.

Поле ввода нужно с самого начала: в курсе для новичка ``input()`` появляется
во второй же теме, а без интерактивного ввода такая программа просто
повисла бы, ожидая данных, которых никто не пришлёт.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui import theme

COLOR_ERROR = theme.ERROR
COLOR_INFO = theme.FG_DIM
COLOR_ECHO = theme.SYN_BUILTIN


class OutputPanel(QWidget):
    """Нижняя панель: что программа напечатала и что ученик ей отвечает."""

    input_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._view = QPlainTextEdit(self)
        self._view.setReadOnly(True)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(11)
        self._view.setFont(font)
        self._view.setObjectName("console")
        layout.addWidget(self._view, 1)

        # Строка ввода. Прячется, пока программа не попросит данных.
        self._input_row = QWidget(self)
        row = QHBoxLayout(self._input_row)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        prompt = QLabel("Ответ программе:", self._input_row)
        prompt.setObjectName("inputPrompt")
        row.addWidget(prompt)

        self._input = QLineEdit(self._input_row)
        self._input.setFont(font)
        self._input.returnPressed.connect(self._submit)
        self._input.setPlaceholderText("введи текст и нажми Enter")
        row.addWidget(self._input, 1)

        layout.addWidget(self._input_row)
        self._input_row.setVisible(False)

    # -- вывод -------------------------------------------------------------

    def clear(self) -> None:
        self._view.clear()

    def append(self, text: str) -> None:
        """Добавляет вывод программы как есть."""
        self._append_html(_escape(text))

    def append_error(self, text: str) -> None:
        self._append_html(f'<span style="color:{COLOR_ERROR}">{_escape(text)}</span>')

    def append_info(self, text: str) -> None:
        """Служебная строка от самого приложения, не от программы ученика."""
        self._append_html(
            f'<span style="color:{COLOR_INFO}; font-style:italic">{_escape(text)}</span>'
        )

    def append_echo(self, text: str) -> None:
        """Отражает то, что ученик ввёл, — иначе диалог в консоли не читается."""
        self._append_html(f'<span style="color:{COLOR_ECHO}">{_escape(text)}</span>')

    def text(self) -> str:
        """Весь накопленный вывод — нужен для поиска номера строки в ошибке."""
        return self._view.toPlainText()

    def _append_html(self, html: str) -> None:
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html.replace("\n", "<br>"))
        self._view.setTextCursor(cursor)
        self._view.ensureCursorVisible()

    # -- ввод --------------------------------------------------------------

    def set_input_enabled(self, enabled: bool) -> None:
        """Показывает строку ввода, пока программа работает."""
        self._input_row.setVisible(enabled)
        if enabled:
            self._input.clear()
            self._input.setFocus(Qt.OtherFocusReason)

    def _submit(self) -> None:
        text = self._input.text()
        self._input.clear()
        self.append_echo(text + "\n")
        self.input_submitted.emit(text)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace(" ", "&nbsp;")
    )
