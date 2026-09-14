"""Учётные данные приложения Яндекса.

Пользователь заводит приложение на oauth.yandex.ru и отдаёт HA только
ClientID и секрет. Всё остальное — переход на страницу разрешений, обмен
кода на токен и его обновление — делает сам Home Assistant.
"""

from __future__ import annotations

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Адреса OAuth Яндекса."""
    return AuthorizationServer(authorize_url=OAUTH2_AUTHORIZE, token_url=OAUTH2_TOKEN)


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Подсказки в диалоге ввода ClientID и секрета."""
    return {
        "oauth_console_url": "https://oauth.yandex.ru/client/new/",
        "more_info_url": "https://github.com/pecherskiy-v/yandex-backup-agent",
    }
