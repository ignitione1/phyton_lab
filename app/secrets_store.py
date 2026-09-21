"""Хранение ключа OpenAI.

Ключ не должен попадать в сборку: распаковать её и достать строки — дело
нескольких минут, а обфускация не помогает, потому что в момент запроса
ключ всё равно существует в открытом виде.

Поэтому источники ищутся по порядку:

1. **Хранилище паролей Windows** — основное место. Рядом с программой
   ключа нет вовсе.
2. **Файл .env** рядом с программой — удобно при разработке.
3. Если нигде нет — приложение попросит ввести ключ и положит его
   в хранилище.
"""

from __future__ import annotations

import os

SERVICE_NAME = "PythonLab"
ACCOUNT_NAME = "openai-api-key"


def _keyring():
    """Библиотека может отсутствовать — это не повод падать."""
    try:
        import keyring

        return keyring
    except Exception:
        return None


def _env_key() -> str:
    """Ключ из .env рядом с программой.

    Файл читается здесь же, а не только при старте приложения: модуль
    должен одинаково работать и из окна, и из отдельного скрипта.
    """
    from_env = os.getenv("OPENAI_API_KEY", "").strip()
    if from_env:
        return from_env

    try:
        from dotenv import dotenv_values

        from app import config

        values = dotenv_values(config.APP_DIR / ".env")
        return (values.get("OPENAI_API_KEY") or "").strip()
    except Exception:
        return ""


def load() -> str:
    """Достаёт ключ из первого источника, где он есть."""
    ring = _keyring()
    if ring is not None:
        try:
            stored = ring.get_password(SERVICE_NAME, ACCOUNT_NAME)
            if stored:
                return stored.strip()
        except Exception:
            # Хранилище может быть недоступно (политики, другая система).
            pass

    return _env_key()


def save(key: str) -> tuple[bool, str]:
    """Кладёт ключ в хранилище Windows.

    Возвращает (получилось ли, что сказать человеку).
    """
    key = (key or "").strip()
    if not looks_like_key(key):
        return False, "Ключ должен начинаться с «sk-» и быть длиннее."

    ring = _keyring()
    if ring is None:
        return False, (
            "Хранилище паролей недоступно: не установлена библиотека keyring. "
            "Положи ключ в файл .env рядом с программой."
        )

    try:
        ring.set_password(SERVICE_NAME, ACCOUNT_NAME, key)
    except Exception as exc:
        return False, f"Не удалось сохранить ключ: {type(exc).__name__}"

    return True, "Ключ сохранён в хранилище паролей Windows."


def forget() -> bool:
    """Убирает ключ из хранилища."""
    ring = _keyring()
    if ring is None:
        return False
    try:
        ring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        return True
    except Exception:
        return False


def looks_like_key(key: str) -> bool:
    """Беглая проверка — чтобы не сохранять явную опечатку."""
    key = (key or "").strip()
    return key.startswith("sk-") and len(key) > 20


def where_from() -> str:
    """Откуда взят действующий ключ — для окна настроек."""
    ring = _keyring()
    if ring is not None:
        try:
            if ring.get_password(SERVICE_NAME, ACCOUNT_NAME):
                return "хранилище паролей Windows"
        except Exception:
            pass
    if _env_key():
        return "файл .env"
    return "не найден"
