"""Рисует иконку приложения.

Иконка генерируется кодом, а не лежит картинкой: так её легко поправить
и не нужно хранить двоичный файл. Рисунок простой — приглашение командной
строки на тёмном фоне: узнаваемо для «здесь пишут код».

Запуск:  python tools/make_icon.py
Результат: app/ui/icon.ico

Рисуем на QImage, а не на QPixmap: QImage не требует ни графической
подсистемы, ни запущенного QApplication.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from app.ui import theme

SIZES = [16, 24, 32, 48, 64, 128, 256]
OUTPUT = Path(__file__).resolve().parent.parent / "app" / "ui" / "icon.ico"


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    # Скруглённая подложка цвета панели.
    radius = size * 0.22
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(theme.BG_PANEL))
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    # Тонкая рамка, чтобы значок не сливался с тёмной панелью задач.
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(theme.BORDER), max(1.0, size * 0.02)))
    inset = size * 0.03
    painter.drawRoundedRect(
        QRectF(inset, inset, size - inset * 2, size - inset * 2), radius, radius
    )

    # Уголок «больше» — знак приглашения командной строки.
    pen = QPen(QColor(theme.ACCENT))
    pen.setWidthF(max(1.5, size * 0.085))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)

    left = size * 0.26
    middle = size * 0.46
    painter.drawLine(int(left), int(size * 0.33), int(middle), int(size * 0.5))
    painter.drawLine(int(middle), int(size * 0.5), int(left), int(size * 0.67))

    # Подчёркивание — курсор ввода.
    pen.setColor(QColor(theme.SYN_STRING))
    painter.setPen(pen)
    painter.drawLine(
        int(size * 0.55), int(size * 0.67), int(size * 0.76), int(size * 0.67)
    )

    painter.end()
    return image


def to_png(image: QImage) -> bytes:
    """Кодирует картинку в PNG.

    ``QByteArray`` держим в переменной: если передать временный объект
    прямо в ``QBuffer``, он умрёт раньше буфера.
    """
    storage = QByteArray()
    buffer = QBuffer(storage)
    buffer.open(QBuffer.WriteOnly)
    ok = image.save(buffer, "PNG")
    buffer.close()
    if not ok:
        raise RuntimeError("не удалось закодировать PNG")
    return bytes(storage)


def write_ico(path: Path, images: list[QImage]) -> None:
    """Собирает .ico вручную: формат простой, зависимостей не добавляет."""
    payloads = [to_png(image) for image in images]

    header = struct.pack("<HHH", 0, 1, len(payloads))
    offset = len(header) + 16 * len(payloads)

    directory = b""
    for image, data in zip(images, payloads):
        # В заголовке .ico размер 256 записывается нулём.
        width = image.width() if image.width() < 256 else 0
        height = image.height() if image.height() < 256 else 0
        directory += struct.pack(
            "<BBBBHHII", width, height, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + directory + b"".join(payloads))


def main() -> int:
    images = [draw(size) for size in SIZES]
    write_ico(OUTPUT, images)
    print(f"иконка записана: {OUTPUT}")
    print(f"размеры: {', '.join(str(s) for s in SIZES)}")
    print(f"объём: {OUTPUT.stat().st_size / 1024:.1f} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
