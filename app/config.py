"""Настройки приложения. Всё, что может понадобиться поменять, собрано здесь."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

import sys

# Собранное приложение распаковывает себя во временную папку, и хранить
# там прогресс нельзя — он исчезнет. Поэтому пути разведены:
#   APP_DIR   — где лежит программа (рядом с ней живут данные и .env);
#   BUNDLE_DIR — откуда читаются встроенные файлы курса.
# При обычном запуске это одно и то же место.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = APP_DIR

BASE_DIR = APP_DIR  # прежнее имя оставлено: им пользуется остальной код

load_dotenv(APP_DIR / ".env")

# --- Пути ---------------------------------------------------------------

DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "lab.db"
# Сюда складывается код ученика на время запуска. Отдельная папка, чтобы
# случайно созданные файлы не сорили в проекте.
WORKDIR = DATA_DIR / "workdir"
COURSE_DIR = BUNDLE_DIR / "app" / "course" / "content"

# --- Запуск кода --------------------------------------------------------

# Чем исполнять код ученика.
#
# В обычном запуске это тот же интерпретатор, на котором работает само
# приложение. В собранном .exe отдельного интерпретатора нет, поэтому
# приложение запускает само себя с особым флагом и работает в этот раз
# не окном, а интерпретатором (см. app/runner/child.py).

PYTHON_EXE = sys.executable

IS_FROZEN = bool(getattr(sys, "frozen", False))


def python_command() -> list[str]:
    """Команда, к которой останется дописать путь к файлу."""
    if IS_FROZEN:
        from app.runner.child import EXEC_FLAG

        return [sys.executable, EXEC_FLAG]
    return [sys.executable]


RUN_TIMEOUT_SEC = 5.0  # ручной запуск по кнопке
CHECK_TIMEOUT_SEC = 3.0  # прогон одного теста при проверке задания
MAX_OUTPUT_CHARS = 20_000  # защита от print в бесконечном цикле

# --- Модели -------------------------------------------------------------

# Ключ ищется по порядку: хранилище паролей Windows, затем .env.
# Подробности — в app/secrets_store.py.
def api_key() -> str:
    from app import secrets_store

    return secrets_store.load()


# Прежнее имя оставлено ради совместимости, но пользоваться лучше api_key().
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Цены на 21.09.2026, за 1M токенов (input / cached / output):
#   gpt-5.6-luna   $0.20 / $0.02 / $1.20  — дешевле gpt-5-mini по всем колонкам
#   gpt-5.6-terra  $2.00 / $0.20 / $12.00
MODEL_LIGHT = "gpt-5.6-luna"  # подсказки, вопросы, разбор ошибок
MODEL_HEAVY = "gpt-5.6-terra"  # генерация заданий, итоги тем, полный разбор

# Reasoning-токены тарифицируются как output, поэтому усилие задаём явно.
EFFORT_MECHANICAL = "none"  # обновление карточки ученика
EFFORT_EXPLAIN = "low"  # объяснения и подсказки
EFFORT_AUTHOR = "medium"  # генерация заданий с тестами

DAILY_TOKEN_LIMIT = 500_000  # мягкий предел: предупреждаем, но не блокируем

# --- Педагогика ---------------------------------------------------------

MAX_HINT_LEVEL = 4  # 4 — полный разбор, только по просьбе ученика
IDLE_NUDGE_SEC = 180  # через сколько молчания учитель предложит помощь
FAILS_BEFORE_NUDGE = 2  # сколько неудачных проверок подряд до предложения


def ensure_dirs() -> None:
    """Создаёт рабочие каталоги. Вызывается один раз при старте."""
    DATA_DIR.mkdir(exist_ok=True)
    WORKDIR.mkdir(exist_ok=True)


def has_api_key() -> bool:
    """Есть ли ключ. Без него живут локальные слои, но учителя нет."""
    key = api_key()
    return bool(key and key.startswith("sk-"))
