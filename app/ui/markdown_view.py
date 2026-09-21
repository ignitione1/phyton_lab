"""Показ текста урока.

Свой разбор markdown вместо ``QTextBrowser.setMarkdown``: встроенный
рендер не даёт управлять оформлением, а нам нужны читаемые в тёмной теме
блоки кода с подсветкой. Поддерживается ровно то подмножество разметки,
которым написан курс.
"""

from __future__ import annotations

import html
import re

from PySide6.QtWidgets import QTextBrowser, QWidget

from app.ui import theme

_KEYWORDS = {
    "if", "else", "elif", "for", "while", "def", "return", "import", "from",
    "in", "not", "and", "or", "True", "False", "None", "break", "continue",
    "class", "try", "except", "finally", "with", "as", "pass", "lambda",
}
_BUILTINS = {
    "print", "input", "len", "range", "int", "str", "float", "bool", "list",
    "dict", "set", "tuple", "sum", "min", "max", "abs", "round", "sorted",
    "type", "enumerate", "zip", "open",
}


def highlight_code(code: str) -> str:
    """Раскрашивает код внутри блока — тем же набором цветов, что в редакторе."""
    escaped = html.escape(code)

    def paint(match: re.Match[str]) -> str:
        token = match.group(0)

        if token.startswith("#"):
            return f'<span style="color:{theme.SYN_COMMENT}">{token}</span>'
        if token[0] in "\"'":
            return f'<span style="color:{theme.SYN_STRING}">{token}</span>'
        if token in _KEYWORDS:
            return f'<span style="color:{theme.SYN_KEYWORD}">{token}</span>'
        if token in _BUILTINS:
            return f'<span style="color:{theme.SYN_BUILTIN}">{token}</span>'
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            return f'<span style="color:{theme.SYN_NUMBER}">{token}</span>'
        return token

    pattern = re.compile(
        r"#[^\n]*"  # комментарий
        r"|&quot;[^&\n]*&quot;"  # строка в двойных кавычках (уже экранирована)
        r"|&#x27;[^&\n]*&#x27;"  # строка в одинарных
        r"|\b\w+\b"
    )
    return pattern.sub(paint, escaped)


def to_html(md: str) -> str:
    """Переводит markdown урока в HTML."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    in_code = False
    code_buffer: list[str] = []
    list_type: str | None = None

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                code = "\n".join(code_buffer)
                out.append(f"<pre class='code'>{highlight_code(code)}</pre>")
                code_buffer = []
                in_code = False
            else:
                close_list()
                in_code = True
            continue

        if in_code:
            code_buffer.append(line)
            continue

        stripped = line.strip()

        if not stripped:
            close_list()
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1)) + 1  # ## в уроке — это h3 на экране
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            if list_type != "ul":
                close_list()
                out.append("<ul>")
                list_type = "ul"
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
            continue

        numbered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if numbered:
            if list_type != "ol":
                close_list()
                out.append("<ol>")
                list_type = "ol"
            out.append(f"<li>{_inline(numbered.group(2))}</li>")
            continue

        quote = re.match(r"^>\s?(.*)$", stripped)
        if quote:
            close_list()
            out.append(f"<blockquote>{_inline(quote.group(1))}</blockquote>")
            continue

        out.append(f"<p>{_inline(stripped)}</p>")

    close_list()
    if in_code and code_buffer:
        out.append(f"<pre class='code'>{highlight_code(chr(10).join(code_buffer))}</pre>")

    return "\n".join(out)


def _inline(text: str) -> str:
    """Жирный, курсив, `код` и стрелки внутри строки."""
    parts = re.split(r"(`[^`]+`)", text)
    result: list[str] = []

    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            code = html.escape(part[1:-1])
            result.append(
                f'<code style="background:{theme.BG_PANEL};color:{theme.SYN_BUILTIN}">'
                f"&nbsp;{code}&nbsp;</code>"
            )
            continue

        chunk = html.escape(part)
        chunk = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", chunk)
        chunk = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", chunk)
        chunk = chunk.replace("←", "&nbsp;←").replace("→", "→")
        result.append(chunk)

    return "".join(result)


_DOC_CSS = f"""
body {{ color: {theme.FG}; }}
h2, h3, h4, h5 {{ color: {theme.FG}; }}
p {{ line-height: 148%; }}
li {{ line-height: 148%; margin-bottom: 3px; }}
blockquote {{ color: {theme.FG_DIM}; }}
pre.code {{
    background: {theme.BG_DEEP};
    color: {theme.FG};
    padding: 10px 12px;
    font-family: Consolas, "Courier New", monospace;
}}
code {{ font-family: Consolas, "Courier New", monospace; }}
a {{ color: {theme.ACCENT}; }}
"""


class MarkdownView(QTextBrowser):
    """Только для чтения: теория, условие задания, реплики учителя."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.document().setDefaultStyleSheet(_DOC_CSS)
        self.setFrameShape(QTextBrowser.NoFrame)
        self._source = ""
        self._stream_base = ""
        self._stream_text = ""
        self._streaming = False

    def set_markdown(self, md: str) -> None:
        self._source = md
        self.setHtml(to_html(md))

    def append_markdown(self, md: str) -> None:
        self._source = (self._source + "\n\n" + md) if self._source else md
        self.setHtml(to_html(self._source))
        self._scroll_to_end()

    # -- потоковый вывод ---------------------------------------------------

    def begin_stream(self, heading: str = "") -> None:
        """Открывает блок, который будет дописываться по мере ответа."""
        self._stream_base = self._source
        self._stream_text = ""
        self._streaming = True
        if heading:
            self._stream_base += f"\n\n---\n\n**{heading}**"
        self.setHtml(to_html(self._stream_base))
        self._scroll_to_end()

    def stream_text(self, text: str) -> None:
        """Перерисовывает блок целиком — вызывать не чаще пары раз в секунду."""
        if not self._streaming:
            return
        self._stream_text = text
        self.setHtml(to_html(self._stream_base + "\n\n" + text))
        self._scroll_to_end()

    def end_stream(self) -> None:
        if not self._streaming:
            return
        self._streaming = False
        self._source = self._stream_base + "\n\n" + self._stream_text
        self.setHtml(to_html(self._source))
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
