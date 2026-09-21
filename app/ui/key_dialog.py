"""Окно ввода ключа OpenAI.

Появляется при первом запуске, если ключ ещё нигде не найден. Отказаться
можно: без ключа приложение работает, только учителя не будет — уроки
и проверка заданий никуда не денутся.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import secrets_store
from app.ui import theme

EXPLANATION = """\
Чтобы учитель отвечал на вопросы и разбирал ошибки, нужен ключ OpenAI.

Ключ сохранится в хранилище паролей Windows — рядом с программой \
его не будет, и в саму программу он не попадёт.

Без ключа уроки, задания и проверка решений работают как обычно, \
но подсказки будут только заготовленные.
"""


class KeyDialog(QDialog):
    """Спрашивает ключ и кладёт его в хранилище."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ключ OpenAI")
        self.setMinimumWidth(520)
        self.setStyleSheet(theme.load_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel("Подключить учителя", self)
        title.setStyleSheet(
            f"color: {theme.FG}; font-size: 17px; font-weight: 600;"
        )
        layout.addWidget(title)

        explanation = QLabel(EXPLANATION, self)
        explanation.setWordWrap(True)
        explanation.setStyleSheet(f"color: {theme.FG_DIM}; font-size: 13px;")
        layout.addWidget(explanation)

        self._field = QLineEdit(self)
        self._field.setPlaceholderText("sk-...")
        self._field.setEchoMode(QLineEdit.Password)
        self._field.textChanged.connect(self._on_changed)
        layout.addWidget(self._field)

        self._hint = QLabel("", self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color: {theme.WARN}; font-size: 12px;")
        layout.addWidget(self._hint)

        row = QHBoxLayout()
        row.setSpacing(8)

        skip = QPushButton("Пока без учителя", self)
        skip.clicked.connect(self.reject)
        row.addWidget(skip)

        row.addStretch(1)

        self._save = QPushButton("Сохранить", self)
        self._save.setObjectName("runButton")
        self._save.setDefault(True)
        self._save.setEnabled(False)
        self._save.clicked.connect(self._on_save)
        row.addWidget(self._save)

        layout.addLayout(row)

    # -- поведение ---------------------------------------------------------

    def _on_changed(self, text: str) -> None:
        self._save.setEnabled(bool(text.strip()))
        self._hint.setText("")

    def _on_save(self) -> None:
        ok, message = secrets_store.save(self._field.text())
        if ok:
            self.accept()
            return
        self._hint.setText(message)

    @staticmethod
    def ask(parent: QWidget | None = None) -> bool:
        """Показывает окно. Возвращает True, если ключ сохранён."""
        dialog = KeyDialog(parent)
        return dialog.exec() == QDialog.Accepted
