"""Что можно посчитать про токены без сети.

Вынесено из `oauth`, чтобы проверять тестами на любой машине: сам `oauth`
тянет aiohttp, которого вне Home Assistant обычно нет.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

from .const import OAUTH2_AUTHORIZE  # noqa: TID252

#: За сколько секунд до истечения обновлять доступ. Запас нужен, чтобы
#: токен не протух посреди многочасовой загрузки архива.
EXPIRY_MARGIN = 3600


def authorize_url(client_id: str) -> str:
    """Ссылка, по которой владелец разрешает доступ и получает код."""
    return f"{OAUTH2_AUTHORIZE}?" + urlencode(
        {"response_type": "code", "client_id": client_id}
    )


def token_expires_at(token: dict[str, Any], now: float | None = None) -> float:
    """Момент истечения доступа в виде отметки времени."""
    return (now if now is not None else time.time()) + float(
        token.get("expires_in") or 0
    )


def token_is_fresh(token: dict[str, Any], now: float | None = None) -> bool:
    """Годится ли сохранённый доступ прямо сейчас."""
    moment = now if now is not None else time.time()
    return float(token.get("expires_at") or 0) - EXPIRY_MARGIN > moment


def explain(body: Any, status: int) -> str:
    """Человеческая причина отказа из ответа Яндекса."""
    if isinstance(body, dict):
        known = {
            "invalid_grant": "код недействителен или уже использован",
            "invalid_client": "не тот ClientID или секрет приложения",
            "unauthorized_client": "приложению не выданы права на Диск",
        }
        code = body.get("error")
        text = known.get(code) or body.get("error_description") or code
        if text:
            return f"{text} (HTTP {status})"
    return f"Яндекс ответил HTTP {status}"
