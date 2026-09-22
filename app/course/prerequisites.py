"""Проверка: не требует ли задание того, чего ещё не показывали.

Самая обидная поломка курса для новичка выглядит так: задание составлено
верно, эталонное решение проходит собственные тесты, всё формально в
порядке — а решить его нельзя, потому что нужного приёма в предыдущих
уроках не было. Ученик при этом винит себя: он не может знать, что
пробел не в его голове, а в курсе.

Остальные проверки такое не ловят по своей природе: они смотрят на
задание изнутри, а здесь важно, что было **до** него.

Устроено так: идём по курсу в том же порядке, в каком его видит ученик.
Код из теории и примеров пополняет список показанного. Код из эталонного
решения сверяется с этим списком — и всё, чему взяться неоткуда,
становится проблемой.

Засчитывается показанным также то, что названо в самой формулировке
задания или лежит в заготовке кода: «воспользуйся `readlines()`» —
законный способ ввести приём прямо в задании.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Iterator

# Стрелка в примерах теории: `print(sum(оценки))  → 17`. Пояснение после
# неё кодом не является и разбору мешает.
ARROW = "→"

_OPS = {
    ast.FloorDiv: "деление нацело //",
    ast.Mod: "остаток %",
    ast.Pow: "степень **",
    ast.Div: "деление /",
    ast.Mult: "умножение *",
}

_NODES = {
    "For": "цикл for",
    "While": "цикл while",
    "If": "условие if",
    "FunctionDef": "своя функция (def)",
    "Return": "return",
    "JoinedStr": "f-строка",
    "ListComp": "списочная сборка",
    "Dict": "словарь",
    "Set": "множество",
    "Tuple": "кортеж",
    "Subscript": "обращение по индексу",
    "Slice": "срез",
    "Try": "try/except",
    "With": "with",
    "Import": "import",
    "Break": "break",
    "Continue": "continue",
    "BoolOp": "and / or",
    "AugAssign": "сокращённая запись (+= и подобные)",
}


def _walk(code: str) -> Iterator[ast.AST]:
    """Разбирает код, не сдаваясь на пояснениях со стрелкой.

    Блок теории целиком часто не разбирается — зато разбирается построчно,
    и этого достаточно: нас интересуют отдельные приёмы, а не структура.
    """
    code = "\n".join(line.split(ARROW)[0].rstrip() for line in (code or "").splitlines())
    if not code.strip():
        return
    try:
        yield from ast.walk(ast.parse(code))
        return
    except SyntaxError:
        pass
    for line in code.splitlines():
        try:
            yield from ast.walk(ast.parse(line.strip()))
        except SyntaxError:
            continue


def features(code: str) -> set[str]:
    """Приёмы, которые использует этот код."""
    found: set[str] = set()

    for node in _walk(code):
        name = type(node).__name__
        if name in _NODES:
            found.add(_NODES[name])

        if isinstance(node, ast.BinOp):
            op = _OPS.get(type(node.op))
            if op:
                found.add(op)

        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                found.add(f"{func.id}()")
                if func.id == "print":
                    if len(node.args) > 1:
                        found.add("print с несколькими кусками через запятую")
                    for keyword in node.keywords:
                        found.add(f"print(..., {keyword.arg}=)")

        elif isinstance(node, ast.Attribute):
            # Действие берётся и без вызова: в формулировке задания могут
            # написать просто `строка.upper` — намерение то же.
            found.add(f".{node.attr}()")

    return found


def _code_in_markdown(text: str) -> Iterator[str]:
    """Куски кода из разметки: блоки в тройных кавычках и вставки в одинарных."""
    if not text:
        return
    for match in re.finditer(r"```(?:python)?\n(.*?)```", text, re.S):
        yield match.group(1)
    for match in re.finditer(r"`([^`\n]+)`", text):
        yield match.group(1)


def _without_placeholders(code: str) -> str:
    """Подстановки шаблонного задания заменяет числом, иначе код не разберётся."""
    return re.sub(r"\{([^}\s]+)\}", "1", code or "")


def find_gaps(course: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Ищет задания, требующие непоказанного.

    Принимает курс в том виде, в каком его читает загрузчик. Возвращает
    пары «где» и «что», готовые лечь в отчёт валидации.
    """
    shown: set[str] = set()
    gaps: list[tuple[str, str]] = []

    for data in course:
        topic = data["topic"]

        for lesson in data.get("lessons", []):
            where = f"{topic['id']} / урок {lesson['id']}"

            # Сначала урок показывает новое.
            for chunk in _code_in_markdown(lesson.get("theory_md", "")):
                shown |= features(chunk)
            for example in lesson.get("examples", []):
                shown |= features(example.get("code", ""))

            # Затем задания опираются на показанное.
            for task in lesson.get("tasks", []):
                solution = _without_placeholders(task.get("solution", ""))

                # Названное в самом задании тоже считается показанным.
                named = features(task.get("starter_code") or "")
                for chunk in _code_in_markdown(task.get("statement_md", "")):
                    named |= features(chunk)

                # Функции, которые ученик определяет сам в этом же решении,
                # знать заранее не требуется.
                own = {
                    f"{node.name}()"
                    for node in _walk(solution)
                    if isinstance(node, ast.FunctionDef)
                }

                missing = features(solution) - shown - named - own
                if missing:
                    gaps.append(
                        (
                            f"{where} / задание {task['id']}",
                            "решение требует того, чего в курсе ещё не было: "
                            + ", ".join(sorted(missing)),
                        )
                    )

                shown |= named

    return gaps
