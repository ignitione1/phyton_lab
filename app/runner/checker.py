"""Проверка решения ученика.

Задача этого модуля — не только вынести вердикт, но и объяснить его
по-человечески. Сообщение «ожидалось X, получено Y» новичку мало что даёт,
поэтому отдельно разбираются частые случаи: сошлось всё, кроме регистра;
отличаются только пробелы; вывода нет вовсе.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field

from app import config
from app.course.models import TestCase
from app.runner.sandbox import RunResult, run_batch

RESULT_MARKER = "@@RESULT@@"


@dataclass
class Failure:
    """Провалившаяся проверка — уже в человеческих словах."""

    message: str
    expected: str = ""
    got: str = ""
    hint: str = ""


@dataclass
class CheckResult:
    passed: bool
    failures: list[Failure] = field(default_factory=list)
    run: RunResult | None = None  # последний запуск: нужен для разбора ошибки
    error_type: str | None = None  # SyntaxError, NameError, ...
    error_line: int | None = None
    error_message: str = ""  # текст исключения — по нему ищется объяснение

    @property
    def crashed(self) -> bool:
        """Код не просто неверен, а вовсе не отработал."""
        return self.error_type is not None


def check(code: str, tests: list[TestCase]) -> CheckResult:
    """Прогоняет все проверки задания по порядку.

    Останавливается на первой упавшей: вываливать новичку пять ошибок сразу
    бессмысленно, он всё равно чинит их по одной.
    """
    # Синтаксис смотрим до запуска: так мы получаем точный номер строки,
    # а ученик — понятный ответ вместо трассировки.
    syntax_problem = _check_syntax(code)
    if syntax_problem is not None:
        return syntax_problem

    result = CheckResult(passed=True)

    for test in tests:
        if test.kind == "ast":
            failure = _check_ast(code, test)
        elif test.kind == "stdout":
            failure, run = _check_stdout(code, test)
            result.run = run
            if run is not None and run.stderr and not run.ok:
                result.error_type, result.error_line = _parse_error(run.stderr)
                result.error_message = _last_line(run.stderr)
        elif test.kind == "call":
            failure, run = _check_call(code, test)
            result.run = run
            if run is not None and run.stderr and not run.ok:
                result.error_type, result.error_line = _parse_error(run.stderr)
                result.error_message = _last_line(run.stderr)
        else:
            failure = Failure(message=f"Неизвестный вид проверки: {test.kind}")

        if failure is not None:
            if test.hint and not failure.hint:
                failure.hint = test.hint
            result.passed = False
            result.failures.append(failure)
            break

    return result


# --------------------------------------------------------------------------
# Синтаксис
# --------------------------------------------------------------------------


def _check_syntax(code: str) -> CheckResult | None:
    try:
        ast.parse(code)
        return None
    except SyntaxError as exc:
        return CheckResult(
            passed=False,
            failures=[
                Failure(
                    message="Python не смог прочитать твой код — в нём опечатка.",
                    got=(exc.text or "").strip(),
                )
            ],
            error_type=type(exc).__name__,
            error_line=exc.lineno,
            error_message=str(exc.msg),
        )


# --------------------------------------------------------------------------
# Проверка вывода
# --------------------------------------------------------------------------


def _check_stdout(code: str, test: TestCase) -> tuple[Failure | None, RunResult]:
    run = run_batch(code, stdin_data=test.stdin, timeout=config.CHECK_TIMEOUT_SEC)

    if run.timed_out:
        return (
            Failure(
                message=(
                    "Программа не завершилась за отведённое время. "
                    "Скорее всего, цикл никогда не заканчивается."
                )
            ),
            run,
        )

    if not run.ok and run.stderr:
        return (
            Failure(
                message="Программа остановилась с ошибкой.",
                got=run.stderr.strip().splitlines()[-1] if run.stderr.strip() else "",
            ),
            run,
        )

    got = run.stdout

    if test.nonempty and not _normalize(got):
        return (
            Failure(
                message="Программа ничего не напечатала.",
                hint="Воспользуйся командой print(), чтобы показать текст.",
            ),
            run,
        )

    if test.expect is not None:
        if _same_text(got, test.expect):
            return None, run
        return _describe_text_mismatch(got, test.expect), run

    for needle in test.expect_contains:
        if _normalize(needle) not in _normalize(got):
            return (
                Failure(
                    message="В выводе не хватает нужного текста.",
                    expected=needle,
                    got=got.strip() or "(ничего не напечатано)",
                ),
                run,
            )

    return None, run


def _normalize(text: str) -> str:
    """Схлопывает незначащие пробелы: они не должны решать судьбу решения."""
    lines = [" ".join(line.split()) for line in (text or "").strip().splitlines()]
    return "\n".join(line for line in lines).strip()


def _same_text(got: str, expected: str) -> bool:
    return _normalize(got) == _normalize(expected)


def _describe_text_mismatch(got: str, expected: str) -> Failure:
    """Разбирает частые причины расхождения и называет их прямо."""
    got_norm, exp_norm = _normalize(got), _normalize(expected)

    if not got_norm:
        return Failure(
            message="Программа ничего не напечатала.",
            expected=expected.strip(),
            got="(пусто)",
            hint="Проверь, что ты используешь print(), а не просто пишешь значение.",
        )

    if got_norm.lower() == exp_norm.lower():
        return Failure(
            message="Всё верно, кроме больших и маленьких букв.",
            expected=expected.strip(),
            got=got.strip(),
            hint="Python различает «Привет» и «привет» — это разный текст.",
        )

    if got_norm.replace(" ", "") == exp_norm.replace(" ", ""):
        return Failure(
            message="Текст правильный, но пробелы стоят не так.",
            expected=expected.strip(),
            got=got.strip(),
        )

    if exp_norm in got_norm:
        return Failure(
            message="Нужный текст есть, но напечатано что-то ещё сверх него.",
            expected=expected.strip(),
            got=got.strip(),
        )

    return Failure(
        message="Программа напечатала не то, что ожидалось.",
        expected=expected.strip(),
        got=got.strip(),
    )


# --------------------------------------------------------------------------
# Проверка вызовом функции
# --------------------------------------------------------------------------

# Запускается вместо кода ученика: подгружает его отдельным файлом,
# вызывает нужную функцию и печатает результат после метки.
_CALL_WRAPPER = '''
import json, sys
_ns = {{}}
with open({script!r}, encoding="utf-8") as _f:
    _src = _f.read()
exec(compile(_src, {script!r}, "exec"), _ns)
_fn = _ns.get({func!r})
if _fn is None:
    sys.stdout.write("\\n{marker}" + json.dumps({{"missing": True}}))
else:
    _value = _fn(*json.loads({args!r}))
    sys.stdout.write("\\n{marker}" + json.dumps({{"value": _value}}, ensure_ascii=False))
'''


def _check_call(code: str, test: TestCase) -> tuple[Failure | None, RunResult]:
    from app.runner.sandbox import USER_CODE_NAME, _prepare_script

    # Код ученика кладём в отдельный файл: обёртка поедет в solution.py
    # и затёрла бы его, если бы имена совпали.
    _prepare_script(code, USER_CODE_NAME)
    wrapper = _CALL_WRAPPER.format(
        script=USER_CODE_NAME,
        func=test.func,
        args=json.dumps(test.args),
        marker=RESULT_MARKER,
    )
    run = run_batch(wrapper, stdin_data=test.stdin, timeout=config.CHECK_TIMEOUT_SEC)

    if run.timed_out:
        return Failure(message="Функция работала слишком долго и была остановлена."), run

    if not run.ok:
        return (
            Failure(
                message="При вызове функции произошла ошибка.",
                got=run.stderr.strip().splitlines()[-1] if run.stderr.strip() else "",
            ),
            run,
        )

    marker_pos = run.stdout.rfind(RESULT_MARKER)
    if marker_pos == -1:
        return Failure(message="Не удалось получить результат функции."), run

    payload = json.loads(run.stdout[marker_pos + len(RESULT_MARKER):])

    if payload.get("missing"):
        return (
            Failure(
                message=f"В коде нет функции с именем «{test.func}».",
                hint="Проверь, что имя написано точно так, как просили в задании.",
            ),
            run,
        )

    value = payload.get("value")
    if value != test.expect_value:
        args_text = ", ".join(repr(a) for a in test.args)
        return (
            Failure(
                message=f"Функция {test.func}({args_text}) вернула не то значение.",
                expected=repr(test.expect_value),
                got=repr(value),
            ),
            run,
        )

    return None, run


# --------------------------------------------------------------------------
# Проверка устройства кода
# --------------------------------------------------------------------------

_NODE_NAMES = {
    "For": "цикл for",
    "While": "цикл while",
    "If": "условие if",
    "FunctionDef": "функция (def)",
    "Return": "return",
    "Call": "вызов функции",
    "List": "список",
    "Dict": "словарь",
    "Assign": "присваивание переменной",
    "BinOp": "вычисление (+, -, *, /)",
    "JoinedStr": "f-строка",
    "Compare": "сравнение",
}


def _check_ast(code: str, test: TestCase) -> Failure | None:
    tree = ast.parse(code)
    present = {type(node).__name__ for node in ast.walk(tree)}

    for name in test.require:
        if name not in present:
            human = _NODE_NAMES.get(name, name)
            return Failure(
                message=f"В решении нужно использовать {human}, а его нет.",
                hint="Задание проверяет не только ответ, но и способ его получить.",
            )

    for name in test.forbid:
        if name in present:
            human = _NODE_NAMES.get(name, name)
            return Failure(
                message=f"В этом задании нельзя использовать {human}.",
            )

    return None


# --------------------------------------------------------------------------
# Разбор трассировки
# --------------------------------------------------------------------------


def _last_line(stderr: str) -> str:
    """Последняя строка трассировки — в ней и написана суть ошибки."""
    lines = (stderr or "").strip().splitlines()
    if not lines:
        return ""
    # Отрезаем «NameError: » — в базе правил ищется только текст сообщения.
    import re as _re

    return _re.sub(r"^\w+(?:Error|Exception):\s*", "", lines[-1].strip())


def _parse_error(stderr: str) -> tuple[str | None, int | None]:
    """Достаёт из трассировки тип ошибки и номер строки в коде ученика."""
    import re

    error_type = None
    for line in reversed(stderr.strip().splitlines()):
        match = re.match(r"^(\w+Error|\w+Exception)\b", line.strip())
        if match:
            error_type = match.group(1)
            break

    line_no = None
    matches = re.findall(
        r'File "[^"]*(?:solution|user_code)\.py", line (\d+)', stderr
    )
    if matches:
        line_no = int(matches[-1])

    return error_type, line_no
