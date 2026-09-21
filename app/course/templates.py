"""Параметризованные задания.

Просьба была такая: запросов к модели поменьше, а разнообразия побольше.
Генерировать каждое задание моделью — дорого и непредсказуемо. Поэтому
одно написанное задание превращается в десяток разных на вид: числа,
имена и слова берутся из заготовленных наборов, а ожидаемый ответ
считается формулой. Обходится в ноль токенов.

Вариант выбирается по тому, сколько раз ученик уже видел это задание,
поэтому при возврате к заданию числа будут другими.
"""

from __future__ import annotations

import ast
import copy
import operator
from typing import Any

from app.course.models import Task, TestCase

# Что разрешено в формулах ожидаемого ответа. Набор намеренно узкий:
# формулы пишем мы сами, но лучше, чтобы опечатка падала сразу и громко,
# а не исполняла что попало.
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "len": len,
    "sum": sum,
    "int": int,
    "float": float,
    "str": str,
    "sorted": sorted,
}


def evaluate(expression: str, values: dict[str, Any]) -> Any:
    """Считает формулу вида ``a * b`` при заданных значениях."""
    tree = ast.parse(expression, mode="eval")
    return _eval_node(tree.body, values)


def _eval_node(node: ast.AST, values: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ValueError(f"в формуле упомянуто неизвестное имя: {node.id}")
        return values[node.id]

    if isinstance(node, ast.BinOp):
        handler = _BIN_OPS.get(type(node.op))
        if handler is None:
            raise ValueError("недопустимое действие в формуле")
        return handler(_eval_node(node.left, values), _eval_node(node.right, values))

    if isinstance(node, ast.UnaryOp):
        handler = _UNARY_OPS.get(type(node.op))
        if handler is None:
            raise ValueError("недопустимое действие в формуле")
        return handler(_eval_node(node.operand, values))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("в формуле разрешены только простые действия")
        args = [_eval_node(arg, values) for arg in node.args]
        return _FUNCS[node.func.id](*args)

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(item, values) for item in node.elts]

    raise ValueError(f"в формуле нельзя использовать {type(node).__name__}")


def pick_values(params: dict[str, list[Any]], variant: int) -> dict[str, Any]:
    """Выбирает набор значений по номеру варианта.

    Значения берутся по кругу, но с разным шагом для каждого имени —
    иначе при трёх наборах по три значения получилось бы всего три
    сочетания вместо двадцати семи.
    """
    values: dict[str, Any] = {}
    for index, (name, pool) in enumerate(sorted(params.items())):
        if not pool:
            continue
        step = index + 1
        values[name] = pool[(variant * step) % len(pool)]
    return values


def render(task: Task, variant: int) -> Task:
    """Возвращает задание с подставленными значениями.

    Обычные задания возвращаются как есть — проверять ничего не нужно.
    """
    if task.kind != "template" or not task.params:
        return task

    values = pick_values(task.params, variant)
    if not values:
        return task

    filled = copy.deepcopy(task)
    filled.statement_md = _substitute(task.statement_md, values)
    filled.starter_code = _substitute(task.starter_code, values)
    filled.solution = _substitute(task.solution, values)
    filled.tests = [_render_test(test, values) for test in task.tests]
    return filled


def _substitute(text: str, values: dict[str, Any]) -> str:
    """Подставляет значения вместо {имя}. Прочие скобки не трогает."""
    if not text:
        return text
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def _render_test(test: TestCase, values: dict[str, Any]) -> TestCase:
    filled = copy.deepcopy(test)

    # Ожидаемый вывод задаётся формулой: expect_expr: "a * b"
    if test.expect_expr:
        filled.expect = str(evaluate(test.expect_expr, values))
        filled.expect_expr = ""
    elif test.expect is not None:
        filled.expect = _substitute(test.expect, values)

    if test.value_expr:
        filled.expect_value = evaluate(test.value_expr, values)
        filled.value_expr = ""

    if test.args_expr:
        filled.args = [evaluate(item, values) for item in test.args_expr]
        filled.args_expr = []

    filled.stdin = _substitute(test.stdin, values)
    filled.expect_contains = [_substitute(item, values) for item in test.expect_contains]
    filled.hint = _substitute(test.hint, values)
    return filled


def variants_count(params: dict[str, list[Any]]) -> int:
    """Сколько всего разных сочетаний даёт набор."""
    total = 1
    for pool in params.values():
        if pool:
            total *= len(pool)
    return total
