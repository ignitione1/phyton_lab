"""Структуры данных курса.

Курс живёт в YAML-файлах, а в приложении — в этих объектах. Ничего
«умного» здесь нет намеренно: содержание урока — это данные, а не код.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestCase:
    """Одна проверка задания.

    Виды:
        stdout — запустить код и сравнить напечатанное;
        call   — вызвать функцию ученика с аргументами и сверить результат;
        ast    — посмотреть, из чего состоит код (есть ли цикл, нет ли
                 запрещённой конструкции). Без этой проверки на задании
                 «посчитай сумму циклом» проходит ``print(15)``.
    """

    kind: str
    # stdout
    stdin: str = ""
    expect: str | None = None
    expect_contains: list[str] = field(default_factory=list)
    nonempty: bool = False  # достаточно, чтобы программа хоть что-то напечатала
    # call
    func: str = ""
    args: list[Any] = field(default_factory=list)
    expect_value: Any = None
    # ast
    require: list[str] = field(default_factory=list)
    forbid: list[str] = field(default_factory=list)
    # Формулы для параметризованных заданий: ответ не пишут руками,
    # а считают из подставленных значений.
    expect_expr: str = ""
    value_expr: str = ""
    args_expr: list[str] = field(default_factory=list)
    # человеческое пояснение, если проверка не прошла
    hint: str = ""

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TestCase":
        return TestCase(
            kind=data["kind"],
            stdin=data.get("stdin", ""),
            expect=data.get("expect"),
            expect_contains=list(data.get("expect_contains", [])),
            nonempty=bool(data.get("nonempty", False)),
            func=data.get("func", ""),
            args=list(data.get("args", [])),
            expect_value=data.get("expect_value"),
            require=list(data.get("require", [])),
            forbid=list(data.get("forbid", [])),
            expect_expr=data.get("expect_expr", ""),
            value_expr=data.get("value_expr", ""),
            args_expr=list(data.get("args_expr", [])),
            hint=data.get("hint", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "stdin": self.stdin,
            "expect": self.expect,
            "expect_contains": self.expect_contains,
            "nonempty": self.nonempty,
            "func": self.func,
            "args": self.args,
            "expect_value": self.expect_value,
            "require": self.require,
            "forbid": self.forbid,
            "expect_expr": self.expect_expr,
            "value_expr": self.value_expr,
            "args_expr": self.args_expr,
            "hint": self.hint,
        }


@dataclass
class Task:
    id: str
    lesson_id: str
    ord: int
    statement_md: str
    starter_code: str = ""
    solution: str = ""
    tests: list[TestCase] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    # Наборы значений для подстановки: {"a": [12, 15], "b": [3, 4]}
    params: dict = field(default_factory=dict)
    kind: str = "static"
    difficulty: int = 1
    is_final: bool = False

    @staticmethod
    def from_row(row) -> "Task":
        tests = [TestCase.from_dict(t) for t in json.loads(row["tests_json"])]
        params = json.loads(row["params_json"] or "{}")
        return Task(
            id=row["id"],
            lesson_id=row["lesson_id"],
            ord=row["ord"],
            statement_md=row["statement_md"],
            starter_code=row["starter_code"],
            solution=row["solution"],
            tests=tests,
            concepts=list(params.get("concepts", [])),
            params=dict(params.get("values", {})),
            kind=row["kind"],
            difficulty=row["difficulty"],
            is_final=bool(row["is_final"]),
        )


@dataclass
class Example:
    """Показательный кусок кода в теории — его можно отправить в редактор."""

    caption: str
    code: str
    # Что «напечатать» при проверке, если пример спрашивает input().
    # На самом уроке ученик вводит своё; это нужно только валидатору.
    stdin: str = ""

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Example":
        return Example(
            caption=data.get("caption", ""),
            code=data["code"],
            stdin=data.get("stdin", ""),
        )

    def to_dict(self) -> dict[str, str]:
        return {"caption": self.caption, "code": self.code, "stdin": self.stdin}


@dataclass
class Lesson:
    id: str
    topic_id: str
    ord: int
    title: str
    theory_md: str
    examples: list[Example] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)

    @staticmethod
    def from_row(row) -> "Lesson":
        return Lesson(
            id=row["id"],
            topic_id=row["topic_id"],
            ord=row["ord"],
            title=row["title"],
            theory_md=row["theory_md"],
            examples=[Example.from_dict(e) for e in json.loads(row["examples_json"])],
        )


@dataclass
class Topic:
    id: str
    ord: int
    title: str
    lessons: list[Lesson] = field(default_factory=list)
