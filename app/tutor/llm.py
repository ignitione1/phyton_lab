"""Обращение к модели.

Узкий слой поверх Responses API: стриминг текста, учёт токенов, повтор
при сетевых сбоях. Всё, что знает об OpenAI, собрано здесь — сменить
модель или провайдера можно, не трогая остальной код.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from app import config


@dataclass
class Usage:
    """Сколько стоил вызов."""

    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost_usd(self, model: str) -> float:
        """Примерная стоимость. Цены — на 21.09.2026, за 1M токенов."""
        prices = {
            "gpt-5.6-luna": (0.20, 0.02, 1.20),
            "gpt-5.6-terra": (2.00, 0.20, 12.00),
            "gpt-5.6-sol": (4.00, 0.40, 20.00),
            "gpt-5": (1.25, 0.125, 10.00),
            "gpt-5-mini": (0.25, 0.025, 2.00),
        }
        rate_in, rate_cached, rate_out = prices.get(model, (0.0, 0.0, 0.0))
        fresh = max(0, self.input_tokens - self.cached_tokens)
        return (
            fresh * rate_in
            + self.cached_tokens * rate_cached
            + self.output_tokens * rate_out
        ) / 1_000_000


@dataclass
class Reply:
    text: str = ""
    usage: Usage = field(default_factory=Usage)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class TutorUnavailable(Exception):
    """Учителя сейчас нет: нет ключа либо не достучались до сервиса."""


class LLMClient:
    """Единственная точка обращения к модели."""

    def __init__(self) -> None:
        self._client: Any = None

    def _ensure(self) -> Any:
        if self._client is not None:
            return self._client
        if not config.has_api_key():
            raise TutorUnavailable(
                "Не найден ключ OpenAI. Положи его в файл .env рядом с run.py."
            )
        from openai import OpenAI

        self._client = OpenAI(api_key=config.api_key(), timeout=60.0)
        return self._client

    # -- стриминг ----------------------------------------------------------

    def stream(
        self,
        system: str,
        user: str,
        model: str | None = None,
        effort: str = config.EFFORT_EXPLAIN,
        max_output_tokens: int = 900,
        on_chunk: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> Reply:
        """Спрашивает модель, отдавая текст по мере появления.

        Стриминг здесь не украшательство: пауза в четыре секунды читается
        как зависшая программа, а текст, который печатается, — как живой
        собеседник, который думает.
        """
        client = self._ensure()
        model = model or config.MODEL_LIGHT
        reply = Reply()

        try:
            stream = self._with_retry(
                lambda: client.responses.create(
                    model=model,
                    instructions=system,
                    input=[{"role": "user", "content": user}],
                    reasoning={"effort": effort},
                    max_output_tokens=max_output_tokens,
                    stream=True,
                )
            )

            pieces: list[str] = []
            for event in stream:
                if should_stop is not None and should_stop():
                    break

                kind = getattr(event, "type", "")

                if kind == "response.output_text.delta":
                    delta = getattr(event, "delta", "") or ""
                    if delta:
                        pieces.append(delta)
                        if on_chunk is not None:
                            on_chunk(delta)

                elif kind in ("response.completed", "response.incomplete"):
                    reply.usage = _read_usage(getattr(event, "response", None))

                elif kind == "error":
                    reply.error = str(getattr(event, "message", "ошибка потока"))

            reply.text = "".join(pieces).strip()

        except TutorUnavailable:
            raise
        except Exception as exc:  # сеть, лимиты, отказ сервиса
            reply.error = _human_error(exc)

        return reply

    # -- обычный ответ целиком ---------------------------------------------

    def complete(
        self,
        system: str,
        user: str,
        model: str | None = None,
        effort: str = config.EFFORT_MECHANICAL,
        max_output_tokens: int = 600,
        schema: dict | None = None,
    ) -> Reply:
        """Ответ целиком. ``schema`` включает строгий JSON по заданной форме."""
        client = self._ensure()
        model = model or config.MODEL_LIGHT
        reply = Reply()

        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": system,
            "input": [{"role": "user", "content": user}],
            "reasoning": {"effort": effort},
            "max_output_tokens": max_output_tokens,
        }
        if schema is not None:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema.get("name", "answer"),
                    "strict": True,
                    "schema": schema["schema"],
                }
            }

        try:
            response = self._with_retry(lambda: client.responses.create(**kwargs))
            reply.text = (getattr(response, "output_text", "") or "").strip()
            reply.usage = _read_usage(response)
        except TutorUnavailable:
            raise
        except Exception as exc:
            reply.error = _human_error(exc)

        return reply

    # -- служебное ---------------------------------------------------------

    @staticmethod
    def _with_retry(call: Callable[[], Any], attempts: int = 3) -> Any:
        """Повтор с нарастающей паузой: сеть моргает чаще, чем хотелось бы."""
        last: Exception | None = None
        for number in range(attempts):
            try:
                return call()
            except Exception as exc:
                if not _worth_retrying(exc):
                    raise
                last = exc
                time.sleep(0.8 * (2**number))
        raise last if last else RuntimeError("не удалось выполнить запрос")


def _worth_retrying(exc: Exception) -> bool:
    name = type(exc).__name__
    if name in ("APIConnectionError", "APITimeoutError", "InternalServerError"):
        return True
    status = getattr(exc, "status_code", None)
    return status in (429, 500, 502, 503, 504)


def _read_usage(response: Any) -> Usage:
    raw = getattr(response, "usage", None)
    if raw is None:
        return Usage()

    input_details = getattr(raw, "input_tokens_details", None)
    output_details = getattr(raw, "output_tokens_details", None)

    return Usage(
        input_tokens=int(getattr(raw, "input_tokens", 0) or 0),
        cached_tokens=int(getattr(input_details, "cached_tokens", 0) or 0),
        output_tokens=int(getattr(raw, "output_tokens", 0) or 0),
        reasoning_tokens=int(getattr(output_details, "reasoning_tokens", 0) or 0),
    )


def _human_error(exc: Exception) -> str:
    """Сообщение, которое можно показать ученику, а не трассировку."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)

    if name in ("APIConnectionError", "APITimeoutError"):
        return "Не получилось связаться с учителем — похоже, пропала сеть."
    if status == 401:
        return "Ключ OpenAI не подошёл. Проверь его в файле .env."
    if status == 429:
        return "Слишком много запросов подряд либо закончились средства на счёте."
    if status == 400 and "model" in str(exc).lower():
        return "Выбранная модель недоступна для этого ключа."
    if status and 500 <= status < 600:
        return "Сервис отвечает с ошибкой. Попробуй через минуту."

    return f"Не удалось получить ответ ({name})."


# Один клиент на приложение: создание дешёвое, но соединение переиспользуется.
_shared = LLMClient()


def shared() -> LLMClient:
    return _shared
