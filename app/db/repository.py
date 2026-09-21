"""Запросы к базе: курс, прогресс, попытки, слабые места."""

from __future__ import annotations

import json

from app.course.models import Lesson, Task, Topic
from app.db import database


# --------------------------------------------------------------------------
# Курс
# --------------------------------------------------------------------------


def topics() -> list[Topic]:
    rows = database.connect().execute("SELECT * FROM topics ORDER BY ord").fetchall()
    return [Topic(id=r["id"], ord=r["ord"], title=r["title"]) for r in rows]


def lessons_of(topic_id: str) -> list[Lesson]:
    rows = (
        database.connect()
        .execute("SELECT * FROM lessons WHERE topic_id = ? ORDER BY ord", (topic_id,))
        .fetchall()
    )
    return [Lesson.from_row(r) for r in rows]


def all_lessons() -> list[Lesson]:
    """Все уроки курса в порядке прохождения."""
    rows = (
        database.connect()
        .execute(
            "SELECT l.* FROM lessons l JOIN topics t ON t.id = l.topic_id "
            "ORDER BY t.ord, l.ord"
        )
        .fetchall()
    )
    return [Lesson.from_row(r) for r in rows]


def lesson(lesson_id: str) -> Lesson | None:
    row = (
        database.connect()
        .execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,))
        .fetchone()
    )
    return Lesson.from_row(row) if row else None


def tasks_of(lesson_id: str) -> list[Task]:
    rows = (
        database.connect()
        .execute("SELECT * FROM tasks WHERE lesson_id = ? ORDER BY ord", (lesson_id,))
        .fetchall()
    )
    return [Task.from_row(r) for r in rows]


def task(task_id: str) -> Task | None:
    row = (
        database.connect().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    )
    return Task.from_row(row) if row else None


def topic_of_lesson(lesson_id: str) -> Topic | None:
    row = (
        database.connect()
        .execute(
            "SELECT t.* FROM topics t JOIN lessons l ON l.topic_id = t.id WHERE l.id = ?",
            (lesson_id,),
        )
        .fetchone()
    )
    return Topic(id=row["id"], ord=row["ord"], title=row["title"]) if row else None


def position_of(lesson_id: str) -> tuple[int, int, int, int]:
    """Где мы в курсе: (номер темы, всего тем, номер урока в теме, уроков в теме)."""
    conn = database.connect()
    row = conn.execute(
        "SELECT t.ord AS t_ord, l.ord AS l_ord, l.topic_id FROM lessons l "
        "JOIN topics t ON t.id = l.topic_id WHERE l.id = ?",
        (lesson_id,),
    ).fetchone()
    if not row:
        return (0, 0, 0, 0)

    total_topics = conn.execute("SELECT COUNT(*) AS n FROM topics").fetchone()["n"]
    in_topic = conn.execute(
        "SELECT COUNT(*) AS n FROM lessons WHERE topic_id = ?", (row["topic_id"],)
    ).fetchone()["n"]
    return (row["t_ord"], total_topics, row["l_ord"], in_topic)


# --------------------------------------------------------------------------
# Прогресс
# --------------------------------------------------------------------------


def lesson_status(lesson_id: str) -> str:
    row = (
        database.connect()
        .execute("SELECT status FROM progress WHERE lesson_id = ?", (lesson_id,))
        .fetchone()
    )
    return row["status"] if row else "not_started"


def set_lesson_status(lesson_id: str, status: str, score: int | None = None) -> None:
    conn = database.connect()
    conn.execute(
        "INSERT INTO progress (lesson_id, status, score, completed_at) "
        "VALUES (?, ?, ?, CASE WHEN ? = 'done' THEN datetime('now') ELSE NULL END) "
        "ON CONFLICT(lesson_id) DO UPDATE SET status = excluded.status, "
        "score = COALESCE(excluded.score, progress.score), "
        "completed_at = COALESCE(excluded.completed_at, progress.completed_at)",
        (lesson_id, status, score, status),
    )
    conn.commit()


def first_unfinished_lesson() -> Lesson | None:
    """Урок, с которого продолжать. Движение по курсу строго линейное."""
    for item in all_lessons():
        if lesson_status(item.id) != "done":
            return item
    return None


def completed_lessons() -> list[str]:
    rows = (
        database.connect()
        .execute("SELECT lesson_id FROM progress WHERE status = 'done'")
        .fetchall()
    )
    return [r["lesson_id"] for r in rows]


# --------------------------------------------------------------------------
# Попытки и слабые места
# --------------------------------------------------------------------------


def record_attempt(
    task_id: str,
    code: str,
    verdict: str,
    stdout: str = "",
    stderr: str = "",
    error_type: str | None = None,
    hint_level: int = 0,
    llm_used: bool = False,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> None:
    conn = database.connect()
    conn.execute(
        "INSERT INTO attempts (task_id, code, verdict, stdout, stderr, error_type, "
        "hint_level, llm_used, tokens_in, tokens_out) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id,
            code,
            verdict,
            stdout[:4000],
            stderr[:4000],
            error_type,
            hint_level,
            int(llm_used),
            tokens_in,
            tokens_out,
        ),
    )
    conn.commit()


def attempts_count(task_id: str, only_failed: bool = False) -> int:
    query = "SELECT COUNT(*) AS n FROM attempts WHERE task_id = ?"
    if only_failed:
        query += " AND verdict != 'pass'"
    return database.connect().execute(query, (task_id,)).fetchone()["n"]


def recent_errors(task_id: str, limit: int = 5) -> list[str]:
    rows = (
        database.connect()
        .execute(
            "SELECT error_type FROM attempts WHERE task_id = ? AND error_type IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (task_id, limit),
        )
        .fetchall()
    )
    return [r["error_type"] for r in rows]


def mark_concepts(names: list[str], mastered: bool) -> None:
    """Отмечает понятия как освоенные или шаткие.

    Считается детерминированно, по фактам из попыток: обращаться за этим
    к модели незачем.
    """
    if not names:
        return
    conn = database.connect()
    status = "mastered" if mastered else "shaky"
    for name in names:
        conn.execute(
            "INSERT INTO concepts (name, status, evidence_count) VALUES (?, ?, 1) "
            "ON CONFLICT(name) DO UPDATE SET "
            "status = CASE WHEN concepts.status = 'shaky' AND ? = 'mastered' "
            "              THEN 'shaky' ELSE ? END, "
            "evidence_count = concepts.evidence_count + 1, "
            "updated_at = datetime('now')",
            (name, status, status, status),
        )
    conn.commit()


def shaky_concepts() -> list[str]:
    rows = (
        database.connect()
        .execute("SELECT name FROM concepts WHERE status = 'shaky' ORDER BY evidence_count DESC")
        .fetchall()
    )
    return [r["name"] for r in rows]


# --------------------------------------------------------------------------
# Состояние сессии
# --------------------------------------------------------------------------


def load_state() -> dict:
    row = database.connect().execute("SELECT * FROM session_state WHERE id = 1").fetchone()
    return dict(row) if row else {}


def save_state(
    lesson_id: str | None = None,
    task_id: str | None = None,
    stage: str | None = None,
    hint_level: int | None = None,
) -> None:
    conn = database.connect()
    current = load_state()
    conn.execute(
        "UPDATE session_state SET lesson_id = ?, task_id = ?, stage = ?, "
        "hint_level = ?, updated_at = datetime('now') WHERE id = 1",
        (
            lesson_id if lesson_id is not None else current.get("lesson_id"),
            task_id if task_id is not None else current.get("task_id"),
            stage if stage is not None else current.get("stage", "theory"),
            hint_level if hint_level is not None else current.get("hint_level", 0),
        ),
    )
    conn.commit()


# --------------------------------------------------------------------------
# Расходы
# --------------------------------------------------------------------------


def record_spend(
    model: str,
    purpose: str,
    tokens_in: int,
    cached_in: int,
    tokens_out: int,
    cost_usd: float,
) -> None:
    """Записывает одно обращение к модели вместе с его ценой."""
    conn = database.connect()
    conn.execute(
        "INSERT INTO spend (model, purpose, tokens_in, cached_in, tokens_out, cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (model, purpose, tokens_in, cached_in, tokens_out, cost_usd),
    )
    conn.commit()


def total_spend() -> float:
    """Всё потраченное за время существования базы."""
    row = database.connect().execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM spend"
    ).fetchone()
    return float(row["s"] or 0.0)


def spend_today() -> float:
    row = database.connect().execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM spend "
        "WHERE date(ts) = date('now')"
    ).fetchone()
    return float(row["s"] or 0.0)


def spend_breakdown() -> list[tuple[str, int, float]]:
    """По какому поводу сколько ушло — для подсказки над счётчиком."""
    rows = database.connect().execute(
        "SELECT purpose, COUNT(*) AS n, SUM(cost_usd) AS s FROM spend "
        "GROUP BY purpose ORDER BY s DESC"
    ).fetchall()
    return [(r["purpose"], r["n"], float(r["s"] or 0.0)) for r in rows]


def token_totals() -> tuple[int, int]:
    row = database.connect().execute(
        "SELECT COALESCE(SUM(tokens_in), 0) AS i, COALESCE(SUM(tokens_out), 0) AS o FROM attempts"
    ).fetchone()
    return (row["i"], row["o"])
