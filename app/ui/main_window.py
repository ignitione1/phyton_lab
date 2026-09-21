"""Главное окно: слева урок, справа редактор и консоль."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.db import database, repository
from app.runner.sandbox import CodeRunner
from app.tutor import profile, prompts
from app.tutor.orchestrator import LessonSession, Stage
from app.tutor.worker import TutorService
from app.ui import theme
from app.ui.code_editor import CodeEditor
from app.ui.lesson_panel import LessonPanel
from app.ui.output_panel import OutputPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Python Lab — учимся программировать")
        self.resize(1320, 860)

        self._runner = CodeRunner(self)
        self._runner.output.connect(self._on_output)
        self._runner.finished.connect(self._on_finished)

        self.session = LessonSession()

        # Учитель работает в стороне от интерфейса: ответ идёт секунду-другую,
        # и всё это время окно должно оставаться живым.
        self.tutor = TutorService(self)
        self.tutor.chunk.connect(self._on_tutor_chunk)
        self.tutor.finished.connect(self._on_tutor_finished)
        self.tutor.failed.connect(self._on_tutor_failed)
        self._tutor_buffer = ""
        self._last_failure = ""
        self._tutor_purpose = "hint"

        self._build_ui()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(2000)
        self._save_timer.timeout.connect(self._save_draft)

        # Текст ответа перерисовывается не на каждую букву, а несколько раз
        # в секунду: иначе панель мерцает и тормозит.
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(120)
        self._stream_timer.timeout.connect(self._flush_tutor_text)

        # Учитель замечает, что ученик завис, и сам предлагает помощь.
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(int(config.IDLE_NUDGE_SEC * 1000))
        self._idle_timer.timeout.connect(self._on_idle)

        # Занятие открывается только после того, как таймеры готовы:
        # отрисовка стадии сразу обращается к ним.
        self.session.start()
        self._render_stage()

        self.editor.textChanged.connect(self._on_code_changed)

        QShortcut(QKeySequence("Ctrl+Return"), self, self._run_code)
        QShortcut(QKeySequence("F5"), self, self._run_code)

    # -- сборка интерфейса -------------------------------------------------

    def _build_ui(self) -> None:
        self.setStyleSheet(theme.load_stylesheet())

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.progress_label = QLabel(central)
        self.progress_label.setObjectName("progressBar")
        outer.addWidget(self.progress_label)

        splitter = QSplitter(Qt.Horizontal, central)

        self.lesson_panel = LessonPanel(splitter)
        self.lesson_panel.example_requested.connect(self._load_example)
        self.lesson_panel.tasks_requested.connect(self._start_tasks)
        self.lesson_panel.next_lesson_requested.connect(self._next_lesson)
        self.lesson_panel.question_asked.connect(self._ask_question)
        splitter.addWidget(self.lesson_panel)

        splitter.addWidget(self._build_work_panel(splitter))
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([520, 800])
        outer.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Готово")
        self._token_label = QLabel("")
        self.statusBar().addPermanentWidget(self._token_label)
        self._update_tokens()

    def _build_work_panel(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Vertical, panel)

        self.editor = CodeEditor(splitter)
        splitter.addWidget(self.editor)

        self.output = OutputPanel(splitter)
        self.output.input_submitted.connect(self._runner.send_input)
        splitter.addWidget(self.output)

        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([500, 300])
        layout.addWidget(splitter, 1)

        layout.addWidget(self._build_buttons(panel))
        return panel

    def _build_buttons(self, parent: QWidget) -> QWidget:
        bar = QWidget(parent)
        bar.setObjectName("buttonBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)

        self.run_button = QPushButton("▶  Запустить", bar)
        self.run_button.setObjectName("runButton")
        self.run_button.setToolTip("Ctrl+Enter или F5")
        self.run_button.clicked.connect(self._run_code)
        row.addWidget(self.run_button)

        self.check_button = QPushButton("✓  Проверить", bar)
        self.check_button.setObjectName("checkButton")
        self.check_button.clicked.connect(self._check_task)
        row.addWidget(self.check_button)

        row.addStretch(1)

        self.help_button = QPushButton("Не понимаю", bar)
        self.help_button.setObjectName("helpButton")
        self.help_button.clicked.connect(self._ask_for_help)
        row.addWidget(self.help_button)

        return bar

    # -- ход урока ---------------------------------------------------------

    def _render_stage(self) -> None:
        session = self.session
        self.progress_label.setText(session.position_text())

        if session.stage == Stage.FINISHED or session.lesson is None:
            self.lesson_panel.show_course_done(self._course_stats())
            self._set_task_mode(False)
            return

        if session.stage == Stage.THEORY:
            self.lesson_panel.show_theory(session.lesson)
            self._set_task_mode(False)
            self.editor.setPlainText(database.load_draft())
            return

        if session.stage == Stage.TOPIC_SUMMARY:
            self._set_task_mode(False)
            return

        if session.stage == Stage.SUMMARY:
            self.lesson_panel.show_lesson_done(session.lesson.title)
            self._set_task_mode(False)
            return

        task = session.current_task
        if task is None:
            self.lesson_panel.show_lesson_done(session.lesson.title)
            self._set_task_mode(False)
            return

        # Ученик перешёл дальше — ответ на прошлое задание уже не нужен.
        self.tutor.cancel()
        self._stream_timer.stop()
        self._last_failure = ""

        self.lesson_panel.show_task(task, session.task_index + 1, len(session.tasks))
        self._set_task_mode(True)
        self.editor.setPlainText(task.starter_code or "")
        self.editor.clear_error()
        self.output.clear()
        self._restart_idle_timer()

    def _set_task_mode(self, active: bool) -> None:  # noqa: D401
        """Проверять и звать учителя можно, только когда решается задание."""
        self.check_button.setEnabled(active)
        self.help_button.setEnabled(active)
        self.help_button.setText("Не понимаю")
        if not active:
            self._idle_timer.stop()

    def _start_tasks(self) -> None:
        self.session.begin_tasks()
        self._render_stage()

    def _next_lesson(self) -> None:
        self.tutor.cancel()
        self._stream_timer.stop()
        if self.session.next_lesson():
            self._render_stage()
        else:
            self.lesson_panel.show_course_done(self._course_stats())
            self._set_task_mode(False)

    def _load_example(self, code: str) -> None:
        self.editor.setPlainText(code)
        self.editor.clear_error()
        self.output.clear()
        self.output.append_info("Пример загружен — нажми «Запустить».")

    # -- проверка задания --------------------------------------------------

    def _check_task(self) -> None:
        task = self.session.current_task
        if task is None:
            return

        self._idle_timer.stop()
        self.statusBar().showMessage("Проверяю…")
        self.check_button.setEnabled(False)

        verdict = self.session.submit(self.editor.toPlainText())

        self.check_button.setEnabled(True)
        self.statusBar().showMessage("Готово")
        self._update_tokens()

        self._last_failure = "" if verdict.passed else verdict.title
        self.editor.mark_error_line(verdict.error_line)
        self.lesson_panel.show_verdict(
            verdict.title, verdict.body_md, good=verdict.passed
        )

        if verdict.passed:
            self.help_button.setText("Не понимаю")

            # Закрыли последний урок темы — подводим итог с оценкой.
            if verdict.lesson_done:
                topic = self.session.finished_topic()
                if topic is not None:
                    QTimer.singleShot(1200, lambda t=topic: self._show_topic_summary(t))
                    return

            # Небольшая пауза, чтобы ученик успел прочитать похвалу.
            QTimer.singleShot(1200, self._render_stage)
            return

        # Код отработал, но решает не ту задачу — тут нужно понять замысел,
        # и это как раз случай для учителя, а не для правил.
        if (
            config.has_api_key()
            and verdict.offer_help
            and not verdict.error_line
            and verdict.expected_got
        ):
            expected, got = verdict.expected_got
            self._start_tutor(
                purpose="review",
                heading="Смотрим вместе",
                user=prompts.build_logic_review(
                    task_statement=task.statement_md,
                    student_code=self.editor.toPlainText(),
                    expected=expected,
                    got=got,
                    lesson_title=self.session.lesson.title if self.session.lesson else "",
                ),
            )
        elif verdict.offer_help:
            self.lesson_panel.show_verdict(
                "Давай посмотрим вместе?",
                "Нажми «Не понимаю» — разберём по шагам. Готовое решение сразу "
                "не покажу: сначала подскажу, куда смотреть.",
            )

        self._restart_idle_timer()

    def _ask_for_help(self) -> None:
        """Кнопка учителя: каждое нажатие поднимает подсказку на ступень."""
        task = self.session.current_task
        if task is None:
            return

        # Разбор уже давали — второй такой же ничего не добавит,
        # только потратит деньги и собьёт ученика с толку.
        if self.session.hints_exhausted:
            self.lesson_panel.show_verdict(
                "Разбор уже был выше",
                "Прокрути объяснение вверх — там полный разбор. Попробуй "
                "написать код сам, по памяти: так он и запомнится.",
            )
            self._restart_idle_timer()
            return

        level = self.session.raise_hint_level()
        self.help_button.setText("Всё равно не понимаю")
        self._restart_idle_timer()

        if not config.has_api_key():
            self.lesson_panel.show_verdict(
                f"Подсказка, ступень {level} из {config.MAX_HINT_LEVEL}",
                _offline_hint(task, level),
            )
            return

        heading = f"Подсказка, ступень {level} из {config.MAX_HINT_LEVEL}"
        self._start_tutor(
            heading=heading,
            user=prompts.build_hint(
                level=level,
                task_statement=task.statement_md,
                student_code=self.editor.toPlainText(),
                lesson_title=self.session.lesson.title if self.session.lesson else "",
                failure=self._last_failure,
                attempts=repository.attempts_count(task.id, only_failed=True),
            ),
            # Полный разбор поручаем модели посильнее: там важно не наврать
            # в коде, который ученик станет разбирать.
            model=config.MODEL_HEAVY if level >= 4 else config.MODEL_LIGHT,
            effort=config.EFFORT_AUTHOR if level >= 4 else config.EFFORT_EXPLAIN,
        )

    def _show_topic_summary(self, topic) -> None:
        """Итог темы: что освоено, оценка, что дальше."""
        self.session.stage = Stage.TOPIC_SUMMARY
        self.progress_label.setText(f"Тема пройдена: {topic.title}")
        self.lesson_panel.show_topic_done(topic.title)
        self._set_task_mode(False)

        stats, weak = self.session.topic_stats(topic.id)
        lessons = [item.title for item in repository.lessons_of(topic.id)]

        if not config.has_api_key():
            self.lesson_panel.show_verdict(
                "Тема закончена",
                f"{stats}\n\nРазбор с оценкой появится, когда будет ключ OpenAI.",
                good=True,
            )
            return

        # Итог — редкий вызов и важный: здесь уместна модель посильнее.
        self._start_tutor(
            heading="Итог темы",
            purpose="summary",
            model=config.MODEL_HEAVY,
            effort=config.EFFORT_AUTHOR,
            user=prompts.build_topic_summary(
                topic_title=topic.title,
                lessons=lessons,
                stats=stats,
                weak_spots=weak,
            ),
        )

    def _ask_question(self, question: str) -> None:
        """Свободный вопрос ученика своими словами."""
        if not config.has_api_key():
            self.lesson_panel.show_verdict(
                "Учителя сейчас нет",
                "Чтобы задавать вопросы, положи ключ OpenAI в файл .env "
                "рядом с run.py и перезапусти программу.",
            )
            return

        lesson = self.session.lesson
        task = self.session.current_task
        database.log_friction(
            "question", detail=question[:200], task_id=task.id if task else None
        )

        # Прямая просьба о решении — единственный способ перескочить сразу
        # на последнюю ступень. Всё остальное лестницу не обходит.
        if task is not None and prompts.asks_for_solution(question):
            self.session.hint_level = config.MAX_HINT_LEVEL
            self.session._save()
            self.help_button.setText("Всё равно не понимаю")
            self._start_tutor(
                heading=f"Разбор решения (ступень {config.MAX_HINT_LEVEL} из "
                f"{config.MAX_HINT_LEVEL})",
                user=prompts.build_hint(
                    level=config.MAX_HINT_LEVEL,
                    task_statement=task.statement_md,
                    student_code=self.editor.toPlainText(),
                    lesson_title=lesson.title if lesson else "",
                    failure=self._last_failure,
                    attempts=repository.attempts_count(task.id, only_failed=True),
                ),
                model=config.MODEL_HEAVY,
                effort=config.EFFORT_AUTHOR,
            )
            return

        self._start_tutor(
            heading="Учитель",
            purpose="question",
            user=prompts.build_question(
                question=question,
                lesson_title=lesson.title if lesson else "",
                theory_excerpt=lesson.theory_md if lesson else "",
                task_statement=task.statement_md if task else "",
                student_code=self.editor.toPlainText(),
                solving_task=task is not None,
            ),
        )

    # -- разговор с учителем ------------------------------------------------

    def _start_tutor(
        self,
        heading: str,
        user: str,
        model: str | None = None,
        effort: str = config.EFFORT_EXPLAIN,
        purpose: str = "hint",
    ) -> None:
        self._tutor_buffer = ""
        self._tutor_purpose = purpose
        self.lesson_panel.begin_tutor_reply(heading)
        self.statusBar().showMessage("Учитель отвечает…")
        self.help_button.setEnabled(False)
        self._stream_timer.start()

        self.tutor.ask(
            system=prompts.build_system(profile.known_terms())
            + "\n\nЧто известно об ученике:\n"
            + profile.load().to_prompt(),
            user=user,
            model=model,
            effort=effort,
        )

    def _on_tutor_chunk(self, text: str) -> None:
        self._tutor_buffer += text

    def _flush_tutor_text(self) -> None:
        if self._tutor_buffer:
            self.lesson_panel.stream_tutor_reply(self._tutor_buffer)

    def _on_tutor_finished(
        self,
        text: str,
        model: str,
        tokens_in: int,
        cached_in: int,
        tokens_out: int,
        cost: float,
    ) -> None:
        self._stream_timer.stop()
        self._tutor_buffer = text
        self.lesson_panel.stream_tutor_reply(text)
        self.lesson_panel.end_tutor_reply()
        self.statusBar().showMessage("Готово")
        self.help_button.setEnabled(self.session.current_task is not None)

        # Цена считается и сохраняется сразу: если тарифы изменятся,
        # прошлые траты останутся такими, какими были на самом деле.
        repository.record_spend(
            model=model,
            purpose=self._tutor_purpose,
            tokens_in=tokens_in,
            cached_in=cached_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )

        task = self.session.current_task
        if task is not None:
            repository.record_attempt(
                task_id=task.id,
                code=self.editor.toPlainText(),
                verdict="help",
                hint_level=self.session.hint_level,
                llm_used=True,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        self._update_tokens()

    def _on_tutor_failed(self, message: str) -> None:
        self._stream_timer.stop()
        self.lesson_panel.end_tutor_reply()
        self.statusBar().showMessage("Готово")
        self.help_button.setEnabled(self.session.current_task is not None)

        task = self.session.current_task
        fallback = _offline_hint(task, self.session.hint_level) if task else ""
        self.lesson_panel.show_verdict(
            "Учитель не ответил",
            message + (("\n\n" + fallback) if fallback else ""),
        )

    def _on_idle(self) -> None:
        """Ученик давно ничего не менял — предлагаем помощь, не навязывая."""
        if self.session.current_task is None:
            return
        database.log_friction(
            "idle",
            detail=f"{config.IDLE_NUDGE_SEC} с без изменений",
            task_id=self.session.current_task.id,
        )
        self.lesson_panel.show_verdict(
            "Застрял?",
            "Если не получается — нажми «Не понимаю», подскажу.",
        )

    def _restart_idle_timer(self) -> None:
        if self.session.current_task is not None:
            self._idle_timer.start()

    # -- запуск кода -------------------------------------------------------

    def _run_code(self) -> None:
        if self._runner.is_running:
            self._runner.stop()
            self.output.append_info("\n[остановлено]\n")
            self._reset_run_state()
            return

        code = self.editor.toPlainText()
        if not code.strip():
            self.output.clear()
            self.output.append_info("Пустой файл — писать нечего. Напиши хоть строчку.")
            return

        self.editor.clear_error()
        self.output.clear()
        self.output.set_input_enabled(True)

        self.run_button.setText("■  Остановить")
        self.statusBar().showMessage("Программа работает…")
        self._runner.start(code)

    def _on_output(self, chunk: str) -> None:
        self.output.append(chunk)

    def _on_finished(self, exit_code: int, timed_out: bool) -> None:
        if timed_out:
            self.output.append_error(
                f"\n\n⏱ Программа работала дольше {config.RUN_TIMEOUT_SEC:.0f} секунд "
                "и была остановлена.\nЧаще всего это значит, что цикл никогда "
                "не заканчивается."
            )
        elif exit_code != 0:
            self._mark_error_from_traceback()
            self.output.append_info("\n[программа завершилась с ошибкой]")
        else:
            self.output.append_info("\n[программа завершилась]")

        self._reset_run_state()

    def _reset_run_state(self) -> None:
        self.run_button.setText("▶  Запустить")
        self.output.set_input_enabled(False)
        self.statusBar().showMessage("Готово")

    def _mark_error_from_traceback(self) -> None:
        matches = re.findall(r'File "[^"]*solution\.py", line (\d+)', self.output.text())
        if matches:
            self.editor.mark_error_line(int(matches[-1]))

    # -- служебное ---------------------------------------------------------

    def _on_code_changed(self) -> None:
        self._save_timer.start()
        self._restart_idle_timer()

    def _save_draft(self) -> None:
        # Черновик бережём только вне заданий: у задания есть свой стартовый код.
        if self.session.stage != Stage.TASK:
            database.save_draft(self.editor.toPlainText())

    def _course_stats(self) -> dict:
        """Сухие числа пройденного пути — для финального экрана."""
        conn = database.connect()
        return {
            "topics": conn.execute("SELECT COUNT(*) AS n FROM topics").fetchone()["n"],
            "lessons": len(repository.completed_lessons()),
            "tasks": conn.execute(
                "SELECT COUNT(DISTINCT task_id) AS n FROM attempts WHERE verdict = 'pass'"
            ).fetchone()["n"],
            "attempts": conn.execute(
                "SELECT COUNT(*) AS n FROM attempts WHERE verdict != 'help'"
            ).fetchone()["n"],
        }

    def _update_tokens(self) -> None:
        """Показывает расход деньгами: токены ученику ни о чём не говорят."""
        total = repository.total_spend()
        today = repository.spend_today()

        self._token_label.setText(
            f"Потрачено: {_money(total)}" + (f"   ·   сегодня {_money(today)}" if today else "")
        )

        parts = ["Расходы на учителя за всё время:", ""]
        for purpose, count, amount in repository.spend_breakdown():
            parts.append(f"  {_PURPOSES.get(purpose, purpose)}: {count} — {_money(amount)}")
        tokens_in, tokens_out = repository.token_totals()
        parts += ["", f"Токенов: {tokens_in} входных, {tokens_out} выходных"]
        self._token_label.setToolTip("\n".join(parts))

    def closeEvent(self, event) -> None:
        self.tutor.cancel()
        self._runner.stop()
        self._save_draft()
        database.close()
        super().closeEvent(event)


_PURPOSES = {
    "hint": "подсказки",
    "question": "вопросы",
    "review": "разбор ошибок",
    "summary": "итоги тем",
    "profile": "заметки об ученике",
}


def _money(amount: float) -> str:
    """Суммы тут копеечные, поэтому меньше цента показываем честно."""
    if amount <= 0:
        return "$0"
    if amount < 0.01:
        return f"${amount:.4f}".rstrip("0")
    if amount < 1:
        return f"${amount:.3f}".rstrip("0")
    return f"${amount:.2f}"


def _offline_hint(task, level: int) -> str:
    """Запасные подсказки, когда учитель недоступен.

    Нет ключа или пропала сеть — ученик всё равно не должен остаться
    ни с чем. Лестница та же: решение только на четвёртой ступени.
    """
    hints = [t.hint for t in task.tests if t.hint]

    if level == 1:
        first = hints[0] if hints else "Перечитай условие: что именно должно получиться?"
        return f"{first}\n\nЕсли не помогло — нажми ещё раз."

    if level == 2:
        if len(hints) > 1:
            return hints[1] + "\n\nЕсли не помогло — нажми ещё раз."
        return (
            "Сравни свой код с примерами из теории, строка за строкой. "
            "Чаще всего расходится одна мелочь: скобка, кавычка или регистр.\n\n"
            "Если не помогло — нажми ещё раз."
        )

    if level == 3:
        return (
            "Разбор именно твоего кода появится на следующем этапе разработки — "
            "там учитель посмотрит, что ты написал, и объяснит.\n\n"
            "Пока могу показать готовое решение: нажми ещё раз."
        )

    return (
        "**Как можно было решить**\n\n"
        "```\n" + (task.solution or "").strip() + "\n```\n\n"
        "Разбери построчно и напиши сам, не копируя, — иначе не запомнится."
    )
