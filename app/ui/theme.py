"""Единственное место, где заданы цвета.

Тёмная тема сделана щадящей намеренно:

* фон не чёрный (#000), а тёмно-серый — на чистом чёрном светлый текст даёт
  ореол и глаза устают быстрее всего;
* текст не белый (#fff), а приглушённый — контраст около 10:1 вместо 21:1,
  этого с запасом хватает для WCAG AAA и читается заметно мягче;
* цвета подсветки приглушены по насыщенности: неон на тёмном режет глаза.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

# --- Поверхности ---------------------------------------------------------

BG = "#1f2228"  # основной фон
BG_PANEL = "#23262d"  # панели, полоса кнопок, статусбар
BG_DEEP = "#1a1d22"  # консоль — чуть глубже основного
BG_HOVER = "#2b2f37"
BG_CURLINE = "#272b33"  # строка под курсором
BORDER = "#31353f"

# --- Текст ---------------------------------------------------------------

FG = "#c7ccd6"  # основной текст
FG_DIM = "#8b93a1"  # подписи, служебные строки
FG_FAINT = "#677080"  # выключенные элементы, номера строк

# --- Акценты -------------------------------------------------------------

ACCENT = "#4b83d4"  # кнопка запуска
ACCENT_HOVER = "#5a90dd"
SUCCESS = "#7fb069"  # проверка пройдена
WARN = "#d9a55b"  # кнопка учителя
ERROR = "#e0707a"  # ошибки

BG_ERRLINE = "#3a2a2e"  # подложка строки с ошибкой
BG_WARN_SOFT = "#2f2a22"

# --- Подсветка синтаксиса ------------------------------------------------

SYN_KEYWORD = "#c678dd"  # фиолетовый: if, for, def
SYN_BUILTIN = "#61afef"  # голубой: print, input, len
SYN_STRING = "#98c379"  # зелёный: "текст"
SYN_NUMBER = "#d19a66"  # оранжевый: числа
SYN_COMMENT = "#808999"  # серый курсив; намеренно светлее обычного
SYN_DEFNAME = "#61afef"

# --- Подстановка в таблицу стилей ----------------------------------------

from app import config

_QSS_PATH = config.BUNDLE_DIR / "app" / "ui" / "styles.qss"


def _palette() -> dict[str, str]:
    """Все константы модуля, записанные ЗАГЛАВНЫМИ, — для подстановки в qss."""
    return {
        name: value
        for name, value in globals().items()
        if name.isupper() and isinstance(value, str) and value.startswith("#")
    }


def load_stylesheet() -> str:
    """Читает styles.qss и подставляет цвета вместо $ПЕРЕМЕННЫХ.

    Используется ``string.Template``, а не ``str.format``: в qss полно
    фигурных скобок, и format на них спотыкается.
    """
    if not _QSS_PATH.exists():
        return ""
    return Template(_QSS_PATH.read_text(encoding="utf-8")).safe_substitute(_palette())


def apply_palette(app) -> None:
    """Тёмная палитра для того, что не покрывается таблицей стилей.

    Без этого контекстное меню редактора, всплывающие подсказки и рамки
    остались бы светлыми — на тёмном окне это бьёт по глазам сильнее всего.
    """
    from PySide6.QtGui import QColor, QPalette

    app.setStyle("Fusion")
    p = QPalette()

    p.setColor(QPalette.Window, QColor(BG))
    p.setColor(QPalette.WindowText, QColor(FG))
    p.setColor(QPalette.Base, QColor(BG))
    p.setColor(QPalette.AlternateBase, QColor(BG_PANEL))
    p.setColor(QPalette.Text, QColor(FG))
    p.setColor(QPalette.Button, QColor(BG_PANEL))
    p.setColor(QPalette.ButtonText, QColor(FG))
    p.setColor(QPalette.BrightText, QColor(ERROR))
    p.setColor(QPalette.Highlight, QColor(ACCENT))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ToolTipBase, QColor(BG_PANEL))
    p.setColor(QPalette.ToolTipText, QColor(FG))
    p.setColor(QPalette.PlaceholderText, QColor(FG_FAINT))
    p.setColor(QPalette.Link, QColor(ACCENT))

    p.setColor(QPalette.Disabled, QPalette.Text, QColor(FG_FAINT))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(FG_FAINT))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(FG_FAINT))

    app.setPalette(p)
