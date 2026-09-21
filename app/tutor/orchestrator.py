"""Ход урока.

Занятие ведёт этот код, а не языковая модель. Последовательность,
момент перехода к следующему заданию и уровень подсказки определяются
здесь — детерминированно. Модель (этап 3) будет отвечать на вопросы и
объяснять, но не решать, чему учить дальше.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app import config
from app.course import templates
from app.course.models import Lesson, Task
from app.db import database, repository
from app.runner import checker, error_db


class Stage(str, Enum):
    THEORY = "theory"  # читаем объяснение
    TASK = "task"  # решаем задание
    SUMMARY = "summary"  # урок закончен
    TOPIC_SUMMARY = "topic_summary"  # тема закончена, подводим итог
    FINISHED = "finished"  # курс пройден


@dataclass
class Verdict:
    """Что сказать ученику после нажатия «Проверить»."""

    passed: bool
    title: str
    body_md: str = ""
    error_line: int | None = None
    # Предложить помощь, не навязывая: ученик вправе отказаться.
    offer_help: bool = False
    advance: bool = False  # можно переходить дальше
    lesson_done: bool = False
    # Чего ждали и что вышло. Заполняется, только когда код отработал без
    # ошибки, но выдал не то: это случай для учителя, а не для правил.
    expected_got: tuple[str, str] | None = None


# Похвала по кругу: одна и та же фраза на десятом задании звучит фальшиво.
_PRAISE = [
    "Верно. Идём дальше.",
    "Правильно.",
    "Так и есть — задание сделано.",
    "Хорошо, работает как надо.",
    "Получилось.",
]


class LessonSession:
    """Текущее занятие: какой урок, какое задание, сколько было неудач."""

    def __init__(self) -> None:
        self.lesson: Lesson | None = None
        self.tasks: list[Task] = []
        self.task_index: int = 0
        self.stage: Stage = Stage.THEORY
        self.hint_level: int = 0
        self._fails_in_row: int = 0
        self._praise_index: int = 0
        # Готовые варианты параметризованных заданий: в пределах одного
        # захода числа меняться не должны, иначе ученик сойдёт с ума.
        self._variants: dict[str, Task] = {}

    # -- запуск и восстановление ------------------------------------------

    def start(self) -> None:
        """Продолжает с того места, где остановились в прошлый раз."""
        state = repository.load_state()
        lesson = None

        if state.get("lesson_id"):
            lesson = repository.lesson(state["lesson_id"])
            if lesson is not None and repository.lesson_status(lesson.id) == "done":
                lesson = None  # урок уже сдан, перескакиваем на следующий

        if lesson is None:
            lesson = repository.first_unfinished_lesson()

        if lesson is None:
            self.stage = Stage.FINISHED
            return

        self._open_lesson(lesson)

        # Восстанавливаем, на каком задании остановились. А вот уровень
        # подсказки намеренно НЕ восстанавливаем: человек, вернувшийся к
        # заданию на следующий день, должен снова получить наводящий
        # вопрос, а не готовое решение с первого нажатия.
        if state.get("stage") == Stage.TASK.value and state.get("task_id"):
            for index, task in enumerate(self.tasks):
                if task.id == state["task_id"]:
                    self.task_index = index
                    self.stage = Stage.TASK
                    self.hint_level = 0
                    break

        self._save()

    def _open_lesson(self, lesson: Lesson) -> None:
        self.lesson = lesson
        self.tasks = repository.tasks_of(lesson.id)
        self._variants = {}
        self.task_index = 0
        self.stage = Stage.THEORY
        self.hint_level = 0
        self._fails_in_row = 0
        repository.set_lesson_status(lesson.id, "in_progress")
        self._save()

    # -- навигация ---------------------------------------------------------

    @property
    def current_task(self) -> Task | None:
        if self.stage != Stage.TASK or not self.tasks:
            return None
        if self.task_index >= len(self.tasks):
            return None

        task = self.tasks[self.task_index]
        if task.kind != "template":
            return task

        # Вариант выбирается по числу прошлых заходов на это задание,
        # поэтому при возвращении к нему числа будут другими.
        if task.id not in self._variants:
            seen = repository.attempts_count(task.id)
            self._variants[task.id] = templates.render(task, seen)
        return self._variants[task.id]

    def begin_tasks(self) -> Task | None:
        """Переход от теории к заданиям."""
        if not self.tasks:
            self.stage = Stage.SUMMARY
            self._save()
            return None
        self.stage = Stage.TASK
        self.task_index = 0
        self.hint_level = 0
        self._fails_in_row = 0
        self._save()
        return self.current_task

    def finished_topic(self) -> object | None:
        """Тема, которую только что закрыли. ``None``, если тема ещё идёт.

        Проверяется после сдачи последнего задания урока: если все уроки
        темы отмечены пройденными, пора подводить итог.
        """
        if self.lesson is None:
            return None

        topic = repository.topic_of_lesson(self.lesson.id)
        if topic is None:
            return None

        lessons = repository.lessons_of(topic.id)
        if all(repository.lesson_status(item.id) == "done" for item in lessons):
            return topic
        return None

    def topic_stats(self, topic_id: str) -> tuple[str, list[str]]:
        """Сухие числа по теме и список того, что давалось тяжело."""
        conn = database.connect()
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN a.verdict = 'pass' THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN a.llm_used = 1 THEN 1 ELSE 0 END) AS helped "
            "FROM attempts a JOIN tasks t ON t.id = a.task_id "
            "JOIN lessons l ON l.id = t.lesson_id WHERE l.topic_id = ?",
            (topic_id,),
        ).fetchone()

        total = (row["total"] if row else 0) or 0
        passed = (row["passed"] if row else 0) or 0
        helped = (row["helped"] if row else 0) or 0

        # Отдельно — итоговые задания темы. Именно они показывают,
        # закрепилось ли пройденное, поэтому оценка смотрит на них.
        final = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN a.verdict = 'pass' THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN a.llm_used = 1 THEN 1 ELSE 0 END) AS helped "
            "FROM attempts a JOIN tasks t ON t.id = a.task_id "
            "JOIN lessons l ON l.id = t.lesson_id "
            "WHERE l.topic_id = ? AND t.is_final = 1",
            (topic_id,),
        ).fetchone()

        f_total = (final["total"] if final else 0) or 0
        f_passed = (final["passed"] if final else 0) or 0
        f_helped = (final["helped"] if final else 0) or 0

        lines = [
            f"По урокам темы: попыток {total}, удачных {passed}, "
            f"обращений за подсказкой {helped}.",
        ]

        if f_total:
            lines.append(
                f"На заданиях по всей теме: попыток {f_total}, "
                f"удачных {f_passed}, подсказок {f_helped}. "
                "Оценку ставь прежде всего по ним — именно они показывают, "
                "закрепилось ли пройденное."
            )

        return "\n".join(lines), repository.shaky_concepts()

    def next_lesson(self) -> bool:
        """Следующий урок. Возвращает False, если курс кончился."""
        lesson = repository.first_unfinished_lesson()
        if lesson is None:
            self.stage = Stage.FINISHED
            self._save()
            return False
        self._open_lesson(lesson)
        return True

    def position_text(self) -> str:
        if self.lesson is None:
            return "Курс пройден"
        t_ord, t_total, l_ord, l_total = repository.position_of(self.lesson.id)
        text = f"Тема {t_ord} из {t_total}  ·  Урок {l_ord} из {l_total}"
        if self.stage == Stage.TASK and self.tasks:
            text += f"  ·  Задание {self.task_index + 1} из {len(self.tasks)}"
        return text

    # -- проверка решения --------------------------------------------------

    def submit(self, code: str) -> Verdict:
        """Проверяет код ученика и решает, что делать дальше."""
        task = self.current_task
        if task is None:
            return Verdict(passed=False, title="Сейчас нет активного задания.")

        result = checker.check(code, task.tests)

        repository.record_attempt(
            task_id=task.id,
            code=code,
            verdict="pass" if result.passed else ("error" if result.crashed else "fail"),
            stdout=result.run.stdout if result.run else "",
            stderr=result.run.stderr if result.run else "",
            error_type=result.error_type,
            hint_level=self.hint_level,
        )

        if result.passed:
            return self._on_success(task)
        return self._on_failure(task, result)

    def _on_success(self, task: Task) -> Verdict:
        attempts = repository.attempts_count(task.id, only_failed=True)

        # Зачёт мягкий: решено — значит решено, сколько бы ни было попыток.
        # Но если далось тяжело, понятие остаётся на заметке как шаткое.
        repository.mark_concepts(task.concepts, mastered=attempts <= 2)

        praise = _PRAISE[self._praise_index % len(_PRAISE)]
        self._praise_index += 1
        self._fails_in_row = 0
        self.hint_level = 0

        body = ""
        if attempts >= 3:
            body = (
                "Далось не сразу — это нормально, так и запоминается. "
                "К этой теме мы ещё вернёмся в заданиях по всей теме."
            )

        self.task_index += 1
        last = self.task_index >= len(self.tasks)

        if last:
            self.stage = Stage.SUMMARY
            repository.set_lesson_status(self.lesson.id, "done")
            self._save()
            return Verdict(
                passed=True,
                title=praise,
                body_md=body,
                advance=True,
                lesson_done=True,
            )

        self._save()
        return Verdict(passed=True, title=praise, body_md=body, advance=True)

    def _on_failure(self, task: Task, result: checker.CheckResult) -> Verdict:
        self._fails_in_row += 1
        failure = result.failures[0] if result.failures else None

        # Однозначную ошибку объясняем сами и сразу — живой преподаватель
        # на незакрытую скобку тоже отвечает не задумываясь.
        explanation = None
        if result.crashed:
            # Синтаксическую ошибку ловит разбор кода — трассировки нет,
            # поэтому текст сообщения берётся из самого исключения.
            explanation = error_db.explain(result.error_type, result.error_message)
            if explanation is None and result.run and result.run.stderr:
                explanation = error_db.explain_stderr(result.run.stderr)

        parts: list[str] = []
        title = failure.message if failure else "Не сходится."

        if explanation is not None:
            title = explanation.title
            parts.append(explanation.body.strip())
            if explanation.fix:
                parts.append(f"*Что сделать:* {explanation.fix.strip()}")
        elif failure is not None:
            if failure.expected or failure.got:
                parts.append(
                    "```\n"
                    f"ожидалось: {failure.expected or '—'}\n"
                    f"получилось: {failure.got or '—'}\n"
                    "```"
                )
            if failure.hint:
                parts.append(failure.hint)

        # После двух неудач подряд предлагаем помощь — но именно предлагаем.
        offer = self._fails_in_row >= config.FAILS_BEFORE_NUDGE
        if offer:
            database.log_friction(
                "repeated_error",
                detail=f"{self._fails_in_row} неудач подряд",
                task_id=task.id,
            )

        expected_got = None
        if not result.crashed and failure is not None and failure.expected:
            expected_got = (failure.expected, failure.got)

        self._save()
        return Verdict(
            passed=False,
            title=title,
            body_md="\n\n".join(p for p in parts if p),
            error_line=result.error_line,
            offer_help=offer,
            expected_got=expected_got,
        )

    # -- подсказки ---------------------------------------------------------

    @property
    def hints_exhausted(self) -> bool:
        """Разбор уже показан — повторять его незачем."""
        return self.hint_level >= config.MAX_HINT_LEVEL

    def raise_hint_level(self) -> int:
        """Поднимает уровень подсказки на ступень. Дальше четвёртой не идём."""
        self.hint_level = min(self.hint_level + 1, config.MAX_HINT_LEVEL)
        task = self.current_task
        database.log_friction(
            "help_request",
            detail=f"уровень {self.hint_level}",
            task_id=task.id if task else None,
        )
        self._save()
        return self.hint_level

    def reset_hint_level(self) -> None:
        self.hint_level = 0
        self._save()

    # -- служебное ---------------------------------------------------------

    def _save(self) -> None:
        task = self.current_task
        repository.save_state(
            lesson_id=self.lesson.id if self.lesson else None,
            task_id=task.id if task else None,
            stage=self.stage.value,
            hint_level=self.hint_level,
        )
