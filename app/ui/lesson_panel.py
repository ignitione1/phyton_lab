"""Левая панель: объяснение, задание и реплики учителя."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.course.models import Lesson, Task
from app.ui import theme
from app.ui.markdown_view import MarkdownView


class LessonPanel(QWidget):
    """Показывает то, что сейчас важно: теорию, условие или разбор."""

    example_requested = Signal(str)  # код примера → в редактор
    tasks_requested = Signal()  # «перейти к заданиям»
    next_lesson_requested = Signal()  # «следующий урок»
    question_asked = Signal(str)  # вопрос учителю своими словами

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._title = QLabel(self)
        self._title.setObjectName("lessonTitle")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._view = MarkdownView(self)
        self._view.setObjectName("lessonView")
        layout.addWidget(self._view, 1)

        # Ряд кнопок с примерами из теории: пример должно быть легко
        # запустить, а не перепечатывать руками.
        self._examples_bar = QWidget(self)
        self._examples_bar.setObjectName("examplesBar")
        self._examples_layout = QVBoxLayout(self._examples_bar)
        self._examples_layout.setContentsMargins(14, 8, 14, 8)
        self._examples_layout.setSpacing(6)
        layout.addWidget(self._examples_bar)
        self._examples_bar.setVisible(False)

        # Спросить можно всегда, а не только после неудачной проверки:
        # живого преподавателя тоже окликают в любой момент.
        self._ask_bar = QWidget(self)
        self._ask_bar.setObjectName("askBar")
        ask_row = QHBoxLayout(self._ask_bar)
        ask_row.setContentsMargins(14, 8, 14, 10)
        ask_row.setSpacing(8)

        self._ask_field = QLineEdit(self._ask_bar)
        self._ask_field.setObjectName("askField")
        self._ask_field.setPlaceholderText("Спросить учителя своими словами…")
        self._ask_field.returnPressed.connect(self._on_ask)
        ask_row.addWidget(self._ask_field, 1)

        self._ask_button = QPushButton("Спросить", self._ask_bar)
        self._ask_button.setObjectName("askButton")
        self._ask_button.clicked.connect(self._on_ask)
        ask_row.addWidget(self._ask_button)

        layout.addWidget(self._ask_bar)
        self._ask_bar.setVisible(False)

        self._action_bar = QWidget(self)
        self._action_bar.setObjectName("actionBar")
        action_row = QHBoxLayout(self._action_bar)
        action_row.setContentsMargins(14, 10, 14, 12)
        action_row.addStretch(1)

        self._action = QPushButton(self._action_bar)
        self._action.setObjectName("primaryAction")
        self._action.clicked.connect(self._on_action)
        action_row.addWidget(self._action)

        layout.addWidget(self._action_bar)
        self._action_bar.setVisible(False)

        self._action_kind = ""

    # -- содержимое --------------------------------------------------------

    def show_theory(self, lesson: Lesson) -> None:
        self._title.setText(lesson.title)
        self._title.setStyleSheet("")
        self._view.set_markdown(lesson.theory_md)
        self._fill_examples(lesson)
        self._ask_bar.setVisible(True)
        self._set_action("tasks", "Перейти к заданиям  →")

    def show_task(self, task: Task, number: int, total: int) -> None:
        # Итоговые задания темы отмечаем: ученик должен понимать,
        # что это проверка всего пройденного, а не очередной урок.
        prefix = "Задание по всей теме" if task.is_final else "Задание"
        self._title.setText(f"{prefix} {number} из {total}")
        self._title.setStyleSheet("")
        self._view.set_markdown(task.statement_md)
        self._examples_bar.setVisible(False)
        self._action_bar.setVisible(False)
        self._ask_bar.setVisible(True)

    def show_verdict(self, title: str, body_md: str = "", good: bool = False) -> None:
        """Дописывает ответ на проверку под условием задания."""
        color = theme.SUCCESS if good else theme.WARN
        block = f"\n\n---\n\n**{title}**\n\n"
        if body_md:
            block += body_md
        self._view.append_markdown(block)
        self._title.setStyleSheet(f"color: {color};")

    def show_lesson_done(self, lesson_title: str) -> None:
        self._title.setText("Урок пройден")
        self._view.set_markdown(
            f"### {lesson_title}\n\nВсе задания этого урока сделаны.\n\n"
            "Можно двигаться дальше."
        )
        self._examples_bar.setVisible(False)
        self._ask_bar.setVisible(False)
        self._title.setStyleSheet(f"color: {theme.SUCCESS};")
        self._set_action("next", "Следующий урок  →")

    def show_topic_done(self, topic_title: str) -> None:
        """Экран итога темы. Текст допишет учитель потоком."""
        self._title.setText(f"Тема пройдена: {topic_title}")
        self._title.setStyleSheet(f"color: {theme.SUCCESS};")
        self._view.set_markdown("")
        self._examples_bar.setVisible(False)
        self._ask_bar.setVisible(False)
        self._set_action("next", "Следующая тема  →")

    def show_course_done(self, stats: dict | None = None) -> None:
        """Финальный экран. Показывает пройденный путь, а не сухую строку."""
        self._title.setText("Курс пройден")
        self._title.setStyleSheet(f"color: {theme.SUCCESS};")

        stats = stats or {}
        parts = [
            "## Это конец курса",
            "",
            "Ты начал с того, что не видел кода вообще. Теперь позади:",
            "",
        ]

        if stats:
            parts += [
                f"- тем пройдено: **{stats.get('topics', 0)}**",
                f"- уроков: **{stats.get('lessons', 0)}**",
                f"- заданий решено: **{stats.get('tasks', 0)}**",
                f"- попыток сделано: **{stats.get('attempts', 0)}**",
                "",
            ]

        parts += [
            "Ты умеешь печатать и спрашивать, хранить данные в переменных, "
            "списках и словарях, принимать решения условиями, повторять "
            "циклами, выделять смысл в функции, не падать от ошибок "
            "и сохранять результат в файл.",
            "",
            "Этого достаточно, чтобы писать настоящие полезные программы.",
            "",
            "## Что делать дальше",
            "",
            "Возьми свою задачу — любую, лишь бы она была нужна лично тебе, — "
            "и напиши её. Своя задача учит быстрее любого курса, потому что "
            "её не бросишь на середине.",
            "",
            "Когда упрёшься в потолок, дальше идут модули и чужие библиотеки "
            "(`pip install`), классы и объекты. Но это уже другой разговор — "
            "и к нему стоит подходить с парой написанных программ за плечами.",
        ]

        self._view.set_markdown("\n".join(parts))
        self._examples_bar.setVisible(False)
        self._ask_bar.setVisible(False)
        self._action_bar.setVisible(False)

    def show_message(self, title: str, md: str) -> None:
        self._title.setText(title)
        self._view.set_markdown(md)
        self._examples_bar.setVisible(False)
        self._action_bar.setVisible(False)

    # -- разговор с учителем ----------------------------------------------

    def begin_tutor_reply(self, heading: str) -> None:
        """Открывает блок ответа и запрещает спрашивать дальше."""
        self._view.begin_stream(heading)
        self._ask_field.setEnabled(False)
        self._ask_button.setEnabled(False)
        self._ask_field.setPlaceholderText("Учитель отвечает…")

    def stream_tutor_reply(self, text: str) -> None:
        self._view.stream_text(text)

    def end_tutor_reply(self) -> None:
        self._view.end_stream()
        self._ask_field.setEnabled(True)
        self._ask_button.setEnabled(True)
        self._ask_field.setPlaceholderText("Спросить учителя своими словами…")

    def _on_ask(self) -> None:
        text = self._ask_field.text().strip()
        if not text:
            return
        self._ask_field.clear()
        self._view.append_markdown(f"\n\n---\n\n*Ты спросил:* {text}")
        self.question_asked.emit(text)

    # -- внутреннее --------------------------------------------------------

    def _fill_examples(self, lesson: Lesson) -> None:
        while self._examples_layout.count():
            item = self._examples_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not lesson.examples:
            self._examples_bar.setVisible(False)
            return

        caption = QLabel("Примеры — можно открыть в редакторе и запустить:", self._examples_bar)
        caption.setObjectName("examplesCaption")
        self._examples_layout.addWidget(caption)

        for example in lesson.examples:
            button = QPushButton("▸  " + (example.caption or "Пример"), self._examples_bar)
            button.setObjectName("exampleButton")
            button.setCursor(Qt.PointingHandCursor)
            code = example.code
            button.clicked.connect(lambda _=False, c=code: self.example_requested.emit(c))
            self._examples_layout.addWidget(button)

        self._examples_bar.setVisible(True)

    def _set_action(self, kind: str, text: str) -> None:
        self._action_kind = kind
        self._action.setText(text)
        self._action_bar.setVisible(True)

    def _on_action(self) -> None:
        if self._action_kind == "tasks":
            self.tasks_requested.emit()
        elif self._action_kind == "next":
            self.next_lesson_requested.emit()


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setStyleSheet(f"color: {theme.BORDER};")
