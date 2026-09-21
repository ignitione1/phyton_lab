"""Редактор кода: подсветка, номера строк, маркер ошибки, автоотступ.

Написан на ``QPlainTextEdit`` вместо готового компонента сознательно.
QScintilla под PySide6 не существует (биндинги есть только для PyQt), а
для ученика, который печатает первую строку кода, богатство настоящей IDE
скорее мешает: автодополнение не даёт запомнить, как пишется ``print``.
"""

from __future__ import annotations

import keyword
import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from app.ui import theme

INDENT = "    "  # четыре пробела, как велит PEP 8

COLOR_KEYWORD = theme.SYN_KEYWORD
COLOR_BUILTIN = theme.SYN_BUILTIN
COLOR_STRING = theme.SYN_STRING
COLOR_NUMBER = theme.SYN_NUMBER
COLOR_COMMENT = theme.SYN_COMMENT
COLOR_DEFNAME = theme.SYN_DEFNAME
COLOR_LINENO = theme.FG_FAINT
COLOR_LINENO_CUR = theme.FG
COLOR_CURLINE = theme.BG_CURLINE
COLOR_ERRLINE = theme.BG_ERRLINE
COLOR_ERRMARK = theme.ERROR
COLOR_GUTTER = theme.BG_PANEL

_BUILTINS = (
    "print input len range int str float bool list dict set tuple "
    "sum min max abs round sorted reversed enumerate zip type isinstance "
    "open format append"
).split()


class PythonHighlighter(QSyntaxHighlighter):
    """Подсветка Python. Намеренно простая — ровно то, что видит новичок."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self._rules: list[tuple[re.Pattern[str], QTextCharFormat]] = []

        def fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        kw_format = fmt(COLOR_KEYWORD, bold=True)
        for word in keyword.kwlist:
            self._rules.append((re.compile(rf"\b{word}\b"), kw_format))

        builtin_format = fmt(COLOR_BUILTIN)
        for word in _BUILTINS:
            self._rules.append((re.compile(rf"\b{word}\b(?=\s*\()"), builtin_format))

        # Имя после def/class — чтобы было видно, что именно объявляется.
        self._rules.append(
            (re.compile(r"\b(?:def|class)\s+(\w+)"), fmt(COLOR_DEFNAME, bold=True))
        )
        self._rules.append((re.compile(r"\b\d+\.?\d*\b"), fmt(COLOR_NUMBER)))

        str_format = fmt(COLOR_STRING)
        self._rules.append((re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"'), str_format))
        self._rules.append((re.compile(r"'[^'\\]*(?:\\.[^'\\]*)*'"), str_format))

        self._comment_format = fmt(COLOR_COMMENT, italic=True)
        self._string_format = str_format

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt_ in self._rules:
            for match in pattern.finditer(text):
                # Для def/class красим только имя, для остального — всё совпадение.
                start, end = (match.span(1) if match.lastindex else match.span())
                self.setFormat(start, end - start, fmt_)

        # Комментарий забивает всё до конца строки, но решётка внутри
        # строкового литерала комментарием не является.
        for match in re.finditer(r"#", text):
            pos = match.start()
            if self.format(pos).foreground().color() != QColor(COLOR_STRING):
                self.setFormat(pos, len(text) - pos, self._comment_format)
                break


class _LineNumberArea(QWidget):
    """Полоса слева: номера строк и маркер ошибки."""

    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    """Редактор кода ученика."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(12)
        self.setFont(font)
        self.setTabStopDistance(
            self.fontMetrics().horizontalAdvance(" ") * len(INDENT)
        )
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

        self._highlighter = PythonHighlighter(self.document())
        self._error_line: int | None = None

        self._line_numbers = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_width)
        self.updateRequest.connect(self._update_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)

        self._update_width()
        self._highlight_current_line()

    # -- строка с ошибкой --------------------------------------------------

    def mark_error_line(self, line: int | None) -> None:
        """Подсвечивает строку с ошибкой (нумерация с единицы)."""
        self._error_line = line
        self._highlight_current_line()
        self._line_numbers.update()

    def clear_error(self) -> None:
        self.mark_error_line(None)

    # -- номера строк ------------------------------------------------------

    def line_number_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_width(self) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_numbers.scroll(0, dy)
        else:
            self._line_numbers.update(
                0, rect.y(), self._line_numbers.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self._update_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_numbers.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_width(), cr.height())
        )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_numbers)
        painter.fillRect(event.rect(), QColor(COLOR_GUTTER))

        block = self.firstVisibleBlock()
        number = block.blockNumber() + 1
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        current = self.textCursor().blockNumber() + 1
        width = self._line_numbers.width()
        height = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if number == self._error_line:
                    painter.setPen(QColor(COLOR_ERRMARK))
                    painter.drawText(
                        0, int(top), width - 6, height, Qt.AlignRight, f"● {number}"
                    )
                else:
                    painter.setPen(
                        QColor(COLOR_LINENO_CUR if number == current else COLOR_LINENO)
                    )
                    painter.drawText(
                        0, int(top), width - 6, height, Qt.AlignRight, str(number)
                    )

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1

    def _highlight_current_line(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []

        if self._error_line is not None:
            block = self.document().findBlockByNumber(self._error_line - 1)
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                sel.format.setBackground(QColor(COLOR_ERRLINE))
                sel.format.setProperty(QTextFormat.FullWidthSelection, True)
                cursor = QTextCursor(block)
                cursor.clearSelection()
                sel.cursor = cursor
                selections.append(sel)

        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor(COLOR_CURLINE))
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            selections.append(sel)

        self.setExtraSelections(selections)

    # -- ввод --------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        """Tab даёт пробелы, Enter сохраняет отступ и добавляет его после ':'."""
        key = event.key()

        if key == Qt.Key_Tab and not self.textCursor().hasSelection():
            self.insertPlainText(INDENT)
            return

        if key == Qt.Key_Backtab or (
            key == Qt.Key_Tab and self.textCursor().hasSelection()
        ):
            self._shift_indent(remove=key == Qt.Key_Backtab)
            return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            cursor = self.textCursor()
            line = cursor.block().text()
            indent = re.match(r"[ \t]*", line).group()
            if line.rstrip().endswith(":"):
                indent += INDENT
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return

        super().keyPressEvent(event)

    def _shift_indent(self, remove: bool) -> None:
        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        cursor.beginEditBlock()
        cursor.setPosition(start)
        first = cursor.blockNumber()
        cursor.setPosition(end)
        last = cursor.blockNumber()

        for number in range(first, last + 1):
            block = self.document().findBlockByNumber(number)
            edit = QTextCursor(block)
            if remove:
                text = block.text()
                strip = len(text) - len(text.lstrip(" "))
                strip = min(strip, len(INDENT))
                if strip:
                    edit.movePosition(
                        QTextCursor.Right, QTextCursor.KeepAnchor, strip
                    )
                    edit.removeSelectedText()
            else:
                edit.insertText(INDENT)
        cursor.endEditBlock()
