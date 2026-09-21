"""Карточка ученика — то, что учитель о нём помнит.

Вместо того чтобы возить в каждом запросе всю переписку, мы держим
короткую выжимку: что уже освоено, что шатается, как человеку удобнее
объяснять. Получается около полутысячи токенов вместо десятков тысяч,
и модель при этом помнит больше существенного.

Почти всё здесь считается из таблицы попыток, без обращения к модели.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from app.db import database, repository


@dataclass
class Profile:
    """Всё, что стоит знать об ученике перед объяснением."""

    mastered: list[str] = field(default_factory=list)
    shaky: list[str] = field(default_factory=list)
    error_patterns: list[str] = field(default_factory=list)
    style_note: str = ""
    lessons_done: int = 0

    def to_prompt(self) -> str:
        """Компактный вид для промпта."""
        lines = []
        if self.lessons_done:
            lines.append(f"Уроков пройдено: {self.lessons_done}.")
        if self.mastered:
            lines.append("Уверенно владеет: " + ", ".join(self.mastered[:12]) + ".")
        if self.shaky:
            lines.append("Даётся тяжело: " + ", ".join(self.shaky[:8]) + ".")
        if self.error_patterns:
            lines.append("Частые промахи: " + "; ".join(self.error_patterns[:5]) + ".")
        if self.style_note:
            lines.append("Как ему объяснять: " + self.style_note)
        return "\n".join(lines) if lines else "Ученик только начал, данных о нём ещё нет."


# Человеческие названия для типов исключений: в промпт незачем тащить
# английские имена классов.
_ERROR_NAMES = {
    "SyntaxError": "опечатки в записи (скобки, кавычки, двоеточия)",
    "IndentationError": "отступы",
    "NameError": "опечатки в именах и необъявленные переменные",
    "TypeError": "смешивание текста и чисел",
    "ValueError": "преобразование текста в число",
    "IndexError": "выход за границы списка",
    "ZeroDivisionError": "деление на ноль",
    "AttributeError": "действия, неприменимые к значению",
}


def load() -> Profile:
    """Собирает карточку: часть из базы фактов, часть из сохранённой заметки."""
    stored = _stored()

    profile = Profile(style_note=stored.get("style_note", ""))

    conn = database.connect()

    rows = conn.execute("SELECT name, status FROM concepts").fetchall()
    profile.mastered = [r["name"] for r in rows if r["status"] == "mastered"]
    profile.shaky = [r["name"] for r in rows if r["status"] == "shaky"]

    # Повторяющиеся ошибки считаем прямо по попыткам — модель для этого
    # не нужна, факты и так есть в базе.
    errors = conn.execute(
        "SELECT error_type, COUNT(*) AS n FROM attempts "
        "WHERE error_type IS NOT NULL GROUP BY error_type "
        "HAVING n >= 2 ORDER BY n DESC LIMIT 5"
    ).fetchall()
    profile.error_patterns = [
        _ERROR_NAMES.get(r["error_type"], r["error_type"]) for r in errors
    ]

    profile.lessons_done = len(repository.completed_lessons())
    return profile


def save_style_note(note: str) -> None:
    """Единственное поле, которое пишет модель."""
    data = _stored()
    data["style_note"] = note.strip()[:400]
    conn = database.connect()
    conn.execute(
        "UPDATE profile SET json = ?, updated_at = datetime('now') WHERE id = 1",
        (json.dumps(data, ensure_ascii=False),),
    )
    conn.commit()


def known_terms() -> list[str]:
    """Понятия, которые ученик уже проходил.

    Нужны, чтобы учитель не объяснял непонятное через непонятное: в уроке
    про циклы нельзя ссылаться на словари, которых ещё не было.
    """
    conn = database.connect()
    rows = conn.execute(
        "SELECT DISTINCT t.params_json FROM tasks t "
        "JOIN lessons l ON l.id = t.lesson_id "
        "JOIN progress p ON p.lesson_id = l.id "
        "WHERE p.status IN ('done', 'in_progress')"
    ).fetchall()

    terms: list[str] = []
    for row in rows:
        try:
            for name in json.loads(row["params_json"] or "{}").get("concepts", []):
                if name not in terms:
                    terms.append(name)
        except (ValueError, TypeError):
            continue
    return terms


def attempts_summary(lesson_id: str) -> str:
    """Короткий отчёт о том, как прошёл урок, — для обновления заметки."""
    conn = database.connect()
    row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN a.verdict = 'pass' THEN 1 ELSE 0 END) AS passed, "
        "SUM(CASE WHEN a.verdict = 'error' THEN 1 ELSE 0 END) AS errors "
        "FROM attempts a JOIN tasks t ON t.id = a.task_id "
        "WHERE t.lesson_id = ?",
        (lesson_id,),
    ).fetchone()

    if not row or not row["total"]:
        return "Попыток не было."

    total = row["total"]
    passed = row["passed"] or 0
    errors = row["errors"] or 0
    return (
        f"Всего попыток: {total}, из них удачных: {passed}, "
        f"с ошибкой выполнения: {errors}."
    )


def _stored() -> dict:
    row = database.connect().execute("SELECT json FROM profile WHERE id = 1").fetchone()
    if not row:
        return {}
    try:
        return json.loads(row["json"] or "{}")
    except ValueError:
        return {}


def as_dict(profile: Profile) -> dict:
    return asdict(profile)
