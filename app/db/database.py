"""Подключение к SQLite и применение схемы."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app import config

_SCHEMA_PATH = config.BUNDLE_DIR / "app" / "db" / "schema.sql"

_connection: sqlite3.Connection | None = None


def connect() -> sqlite3.Connection:
    """Возвращает общее соединение, создавая базу при первом обращении.

    Соединение одно на приложение: писать в базу мы будем только из
    UI-потока, а фоновые задачи обращаются к нему через сигналы Qt.
    """
    global _connection
    if _connection is not None:
        return _connection

    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    _connection = conn
    return conn


def close() -> None:
    """Закрывает соединение. Вызывается при выходе из приложения."""
    global _connection
    if _connection is not None:
        _connection.commit()
        _connection.close()
        _connection = None


# --- Состояние сессии ----------------------------------------------------
# На этапе 1 из всей базы нужно только это: запомнить черновик кода,
# чтобы после перезапуска ученик не начинал с пустого экрана.


def load_draft() -> str:
    row = connect().execute("SELECT draft_code FROM session_state WHERE id = 1").fetchone()
    return row["draft_code"] if row else ""


def save_draft(code: str) -> None:
    conn = connect()
    conn.execute(
        "UPDATE session_state SET draft_code = ?, updated_at = datetime('now') WHERE id = 1",
        (code,),
    )
    conn.commit()


def log_friction(kind: str, detail: str = "", task_id: str | None = None) -> None:
    """Отмечает место, где ученику было трудно.

    Эти записи потом показывают, какие уроки написаны плохо, — ученику
    ничего сообщать специально не нужно.
    """
    conn = connect()
    conn.execute(
        "INSERT INTO friction (task_id, kind, detail) VALUES (?, ?, ?)",
        (task_id, kind, detail),
    )
    conn.commit()
