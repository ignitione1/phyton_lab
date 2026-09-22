"""Загрузка курса из YAML в базу и его проверка.

Вычитывать уроки на глаз некому: ученик по определению не может судить о
материале, которого ещё не знает. Поэтому качество контента держится на
:func:`validate`, а не на внимательности человека.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app import config
from app.course.models import Example, Task, TestCase
from app.db import database

# Заведомо негодные решения. Если тесты задания пропускают хоть одно,
# значит они дырявые и зачтут ерунду.
_BAD_SOLUTIONS = {
    "пустой файл": "",
    "только комментарий": "# ничего не делаю\n",
    "печать без аргументов": "print()\n",
}


# --------------------------------------------------------------------------
# Чтение файлов
# --------------------------------------------------------------------------


def read_files() -> list[dict[str, Any]]:
    """Читает все YAML-файлы курса в порядке имён."""
    files = sorted(config.COURSE_DIR.glob("*.yaml"))
    return [yaml.safe_load(path.read_text(encoding="utf-8")) for path in files]


def load_into_db() -> int:
    """Переносит курс в базу. Идемпотентно: повторный вызов просто обновит.

    Прогресс ученика не трогается — он живёт в отдельных таблицах и
    привязан к идентификаторам, а не к порядковым номерам.
    """
    conn = database.connect()
    count = 0

    for data in read_files():
        topic = data["topic"]
        conn.execute(
            "INSERT INTO topics (id, ord, title) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET ord = excluded.ord, title = excluded.title",
            (topic["id"], topic["ord"], topic["title"]),
        )

        for lesson in data.get("lessons", []):
            examples = [Example.from_dict(e).to_dict() for e in lesson.get("examples", [])]
            conn.execute(
                "INSERT INTO lessons (id, topic_id, ord, title, theory_md, examples_json) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET ord = excluded.ord, title = excluded.title, "
                "theory_md = excluded.theory_md, examples_json = excluded.examples_json",
                (
                    lesson["id"],
                    topic["id"],
                    lesson["ord"],
                    lesson["title"],
                    lesson["theory_md"],
                    json.dumps(examples, ensure_ascii=False),
                ),
            )

            for task in lesson.get("tasks", []):
                tests = [TestCase.from_dict(t).to_dict() for t in task.get("tests", [])]
                params = {
                    "concepts": task.get("concepts", []),
                    "values": task.get("params", {}),
                }
                conn.execute(
                    "INSERT INTO tasks (id, lesson_id, ord, kind, statement_md, "
                    "starter_code, solution, tests_json, params_json, difficulty, is_final) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET ord = excluded.ord, "
                    "statement_md = excluded.statement_md, "
                    "starter_code = excluded.starter_code, solution = excluded.solution, "
                    "tests_json = excluded.tests_json, params_json = excluded.params_json, "
                    "difficulty = excluded.difficulty, is_final = excluded.is_final",
                    (
                        task["id"],
                        lesson["id"],
                        task["ord"],
                        task.get("kind", "static"),
                        task["statement_md"],
                        task.get("starter_code") or "",
                        task.get("solution") or "",
                        json.dumps(tests, ensure_ascii=False),
                        json.dumps(params, ensure_ascii=False),
                        task.get("difficulty", 1),
                        int(bool(task.get("is_final", False))),
                    ),
                )
                count += 1

        conn.execute(
            "INSERT OR IGNORE INTO progress (lesson_id, status) "
            "SELECT id, 'not_started' FROM lessons WHERE topic_id = ?",
            (topic["id"],),
        )

    conn.commit()
    return count


# --------------------------------------------------------------------------
# Проверка курса
# --------------------------------------------------------------------------


@dataclass
class Problem:
    where: str
    what: str


@dataclass
class ValidationReport:
    problems: list[Problem] = field(default_factory=list)
    tasks_checked: int = 0
    examples_checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    def add(self, where: str, what: str) -> None:
        self.problems.append(Problem(where, what))


def validate(run_code: bool = True) -> ValidationReport:
    """Проверяет курс целиком.

    Что именно проверяется:

    1. идентификаторы уникальны, порядковые номера не повторяются;
    2. эталонное решение задания проходит собственные тесты — иначе
       проверка завернёт ученика на верном ответе;
    3. тесты не пропускают заведомо негодное решение (пустой файл и т.п.);
    4. каждый пример из теории запускается без ошибок;
    5. задание не требует приёма, которого в курсе ещё не показывали.

    Последний пункт стоит особняком: остальные смотрят на задание изнутри
    и признают верным то, что сходится само с собой. Пятый смотрит назад —
    была ли у ученика возможность это узнать.

    ``run_code=False`` пропускает пункты 2-4: полезно, когда нужна быстрая
    проверка структуры без запуска доброй сотни процессов. Пятый пункт
    код не запускает и выполняется всегда.
    """
    from app.course import prerequisites
    from app.runner import checker, sandbox

    report = ValidationReport()
    seen_ids: dict[str, str] = {}
    course = read_files()

    for where, what in prerequisites.find_gaps(course):
        report.add(where, what)

    for data in course:
        topic = data["topic"]
        topic_where = f"тема {topic['id']}"

        if topic["id"] in seen_ids:
            report.add(topic_where, "повторяющийся идентификатор темы")
        seen_ids[topic["id"]] = topic_where

        lesson_ords: set[int] = set()

        for lesson in data.get("lessons", []):
            where = f"{topic['id']} / урок {lesson['id']}"

            if lesson["id"] in seen_ids:
                report.add(where, "повторяющийся идентификатор урока")
            seen_ids[lesson["id"]] = where

            if lesson["ord"] in lesson_ords:
                report.add(where, f"номер урока {lesson['ord']} уже занят")
            lesson_ords.add(lesson["ord"])

            if not lesson.get("theory_md", "").strip():
                report.add(where, "пустая теория")

            # Примеры в теории должны работать: неработающий пример
            # подрывает доверие к курсу сильнее, чем отсутствие примера.
            if run_code:
                for index, example in enumerate(lesson.get("examples", []), start=1):
                    code = example["code"]
                    # Часть примеров ломается намеренно — они показывают
                    # ошибку. Такие помечены в подписи.
                    if _is_deliberately_broken(example.get("caption", "")):
                        continue
                    stdin = example.get("stdin", "")
                    if "input(" in code and not stdin:
                        report.add(
                            f"{where}, пример {index}",
                            "спрашивает input(), но не задан stdin для проверки",
                        )
                        continue
                    result = sandbox.run_batch(
                        code, stdin_data=stdin, timeout=config.CHECK_TIMEOUT_SEC
                    )
                    report.examples_checked += 1
                    if not result.ok:
                        last = (result.stderr or "").strip().splitlines()
                        report.add(
                            f"{where}, пример {index}",
                            "не запускается: " + (last[-1] if last else "таймаут"),
                        )

            task_ords: set[int] = set()

            for task in lesson.get("tasks", []):
                task_where = f"{where} / задание {task['id']}"

                if task["id"] in seen_ids:
                    report.add(task_where, "повторяющийся идентификатор задания")
                seen_ids[task["id"]] = task_where

                if task["ord"] in task_ords:
                    report.add(task_where, f"номер задания {task['ord']} уже занят")
                task_ords.add(task["ord"])

                tests = [TestCase.from_dict(t) for t in task.get("tests", [])]
                if not tests:
                    report.add(task_where, "нет ни одной проверки")
                    continue

                solution = task.get("solution") or ""
                if not solution.strip():
                    report.add(task_where, "нет эталонного решения")
                    continue

                try:
                    ast.parse(solution)
                except SyntaxError as exc:
                    report.add(task_where, f"эталонное решение не разбирается: {exc}")
                    continue

                if not run_code:
                    continue

                report.tasks_checked += 1

                # У параметризованного задания проверяем несколько вариантов:
                # ошибка в формуле вылезет не на первом же наборе значений.
                variants = _variants_to_check(task, tests)

                for label, variant_solution, variant_tests in variants:
                    outcome = checker.check(variant_solution, variant_tests)
                    if not outcome.passed:
                        first = outcome.failures[0] if outcome.failures else None
                        report.add(
                            task_where + label,
                            "эталонное решение НЕ проходит собственные тесты: "
                            + (first.message if first else "неизвестно"),
                        )
                        break

                # Обратная проверка: тесты не должны пропускать ерунду.
                for name, bad_code in _BAD_SOLUTIONS.items():
                    if checker.check(bad_code, tests).passed:
                        report.add(
                            task_where,
                            f"тесты пропускают негодное решение ({name}) — "
                            "проверка слишком слабая",
                        )
                        break

    return report


def _variants_to_check(task: dict, tests: list[TestCase]) -> list[tuple]:
    """Наборы «решение + тесты», которые надо прогнать для одного задания."""
    from app.course import templates
    from app.course.models import Task as TaskModel

    solution = task.get("solution") or ""

    if task.get("kind") != "template" or not task.get("params"):
        return [("", solution, tests)]

    model = TaskModel(
        id=task["id"],
        lesson_id="",
        ord=task.get("ord", 1),
        statement_md=task.get("statement_md", ""),
        starter_code=task.get("starter_code") or "",
        solution=solution,
        tests=tests,
        params=task["params"],
        kind="template",
    )

    total = templates.variants_count(task["params"])
    result = []
    for variant in range(min(total, 6)):
        filled = templates.render(model, variant)
        result.append((f" (вариант {variant + 1})", filled.solution, filled.tests))
    return result


def _is_deliberately_broken(caption: str) -> bool:
    """Примеры, которые показывают ошибку, ломаются по замыслу."""
    lowered = caption.lower()
    return any(
        word in lowered
        for word in ("сломан", "ошибк", "опечат", "не работает", "неправильн")
    )


# --------------------------------------------------------------------------
# Запуск из командной строки
# --------------------------------------------------------------------------


def _main() -> int:
    report = validate(run_code=True)
    print(f"Проверено заданий: {report.tasks_checked}")
    print(f"Проверено примеров: {report.examples_checked}")
    if report.ok:
        print("\nПроблем не найдено.")
    else:
        print(f"\nНайдено проблем: {len(report.problems)}\n")
        for problem in report.problems:
            print(f"  [{problem.where}]\n      {problem.what}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    raise SystemExit(_main())
