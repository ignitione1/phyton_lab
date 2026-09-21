"""Поиск объяснения для типовой ошибки.

Отвечает мгновенно и без сети, но только на однозначное: незакрытая
скобка, опечатка в имени, склейка текста с числом. Всё, что требует
понять замысел ученика, сюда не попадает и уходит к учителю.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app import config

_PATTERNS_PATH = config.BUNDLE_DIR / "app" / "runner" / "error_patterns.yaml"


@dataclass
class Explanation:
    title: str
    body: str
    fix: str

    def to_markdown(self) -> str:
        parts = [f"**{self.title}**", "", self.body.strip()]
        if self.fix:
            parts += ["", f"*Что сделать:* {self.fix.strip()}"]
        return "\n".join(parts)


@dataclass
class _Rule:
    type: str
    pattern: re.Pattern[str] | None
    title: str
    body: str
    fix: str


@lru_cache(maxsize=1)
def _rules() -> list[_Rule]:
    raw = yaml.safe_load(_PATTERNS_PATH.read_text(encoding="utf-8"))
    rules: list[_Rule] = []
    for item in raw.get("rules", []):
        rules.append(
            _Rule(
                type=item["type"],
                pattern=re.compile(item["match"]) if item.get("match") else None,
                title=item["title"],
                body=item.get("body", ""),
                fix=item.get("fix", ""),
            )
        )
    return rules


def explain(error_type: str | None, message: str) -> Explanation | None:
    """Ищет объяснение по типу исключения и тексту сообщения.

    Правила просматриваются по порядку, поэтому в YAML частные случаи
    стоят выше общих: «не закрыта скобка» должно сработать раньше, чем
    «Python не понял эту строку».
    """
    if not error_type:
        return None

    for rule in _rules():
        if rule.type != error_type:
            continue
        if rule.pattern is None:
            return _build(rule, None)
        match = rule.pattern.search(message or "")
        if match:
            return _build(rule, match)

    return None


def explain_stderr(stderr: str) -> Explanation | None:
    """То же самое, но разбирает трассировку целиком."""
    if not stderr:
        return None
    last = stderr.strip().splitlines()[-1] if stderr.strip() else ""
    match = re.match(r"^(\w+(?:Error|Exception))\b:?\s*(.*)$", last.strip())
    if not match:
        return None
    return explain(match.group(1), match.group(2))


def _build(rule: _Rule, match: re.Match[str] | None) -> Explanation:
    """Подставляет в текст куски из сообщения об ошибке: {1}, {2}, ..."""

    def fill(text: str) -> str:
        if match is None:
            return text
        for index, group in enumerate(match.groups(), start=1):
            text = text.replace("{%d}" % index, f"`{group}`" if group else "")
        return text

    return Explanation(
        title=fill(rule.title),
        body=fill(rule.body),
        fix=fill(rule.fix),
    )
