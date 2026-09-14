"""Обмен кода подтверждения на доступ и его обновление.

Почему не штатный OAuth Home Assistant: он возвращает браузер на свой
адрес, а Яндекс разрешает в Redirect URI только подтверждённые домены —
`my.home-assistant.io` нам не принадлежит, и поменять адрес у приложения
нельзя даже при создании.

Зато Яндекс умеет отдавать на своей странице короткий код подтверждения.
Код — это не токен: его обмен даёт и `access_token`, и `refresh_token`,
поэтому владелец вставляет код один раз, а дальше доступ продлевается сам.
"""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import CONNECT_TIMEOUT, OAUTH2_TOKEN
from .tokens import explain, token_expires_at

class OAuthError(Exception):
    """Яндекс отказал в обмене или обновлении доступа."""


class YandexOAuth:
    """Разговор с oauth.yandex.ru — только про токены."""

    def __init__(self, session: ClientSession, client_id: str, secret: str) -> None:
        self._session = session
        self._client_id = client_id
        self._secret = secret

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Обменять код подтверждения на доступ."""
        return await self._post(
            {"grant_type": "authorization_code", "code": code.strip()}
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Продлить доступ по refresh-токену."""
        return await self._post(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def _post(self, data: dict[str, str]) -> dict[str, Any]:
        payload = {
            **data,
            "client_id": self._client_id,
            "client_secret": self._secret,
        }
        try:
            async with self._session.post(
                OAUTH2_TOKEN,
                data=payload,
                timeout=ClientTimeout(connect=CONNECT_TIMEOUT, total=60),
            ) as resp:
                body = await resp.json(content_type=None)
                if resp.status >= 400 or "access_token" not in body:
                    raise OAuthError(explain(body, resp.status))
        except ClientError as err:
            raise OAuthError(f"Яндекс недоступен: {err}") from err

        # Яндекс возвращает срок в секундах; храним момент, а не длительность:
        # иначе после перезапуска HA непонятно, от чего его отсчитывать.
        body["expires_at"] = token_expires_at(body)
        return body
