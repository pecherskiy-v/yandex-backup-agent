"""Интеграция «Яндекс.Диск (копии)» — место хранения резервных копий HA."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YandexDisk, YandexDiskAuthError, YandexDiskError
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_FOLDER,
    CONF_TOKEN,
    DATA_BACKUP_AGENT_LISTENERS,
    DEFAULT_FOLDER,
    DOMAIN,
)
from .oauth import OAuthError, YandexOAuth
from .tokens import token_is_fresh

type YandexDiskConfigEntry = ConfigEntry[YandexDisk]


async def async_setup_entry(hass: HomeAssistant, entry: YandexDiskConfigEntry) -> bool:
    """Проверить доступ, создать папку и отдать агента менеджеру копий."""
    oauth = YandexOAuth(
        async_get_clientsession(hass),
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
    )
    # Обновление идёт под замком: параллельные запросы агента иначе
    # обменяли бы один refresh-токен несколько раз подряд.
    lock = asyncio.Lock()

    async def access_token() -> str:
        """Действующий токен; продлевается сам, не дожидаясь отказа."""
        async with lock:
            token = entry.data[CONF_TOKEN]
            if token_is_fresh(token):
                return token["access_token"]

            try:
                fresh = await oauth.refresh(token["refresh_token"])
            except OAuthError as err:
                # Refresh отозвали — сам не починится, просим новый код.
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN, translation_key="token_refresh_failed"
                ) from err

            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_TOKEN: fresh}
            )
            return fresh["access_token"]

    disk = YandexDisk(
        async_get_clientsession(hass),
        access_token,
        entry.data.get(CONF_FOLDER, DEFAULT_FOLDER),
    )

    try:
        await disk.account()
        await disk.ensure_folder()
    except YandexDiskAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="token_refresh_failed"
        ) from err
    except YandexDiskError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err

    entry.runtime_data = disk

    def notify_backup_listeners() -> None:
        for listener in hass.data.get(DATA_BACKUP_AGENT_LISTENERS, []):
            listener()

    entry.async_on_unload(entry.async_on_state_change(notify_backup_listeners))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: YandexDiskConfigEntry) -> bool:
    """Выгрузить запись. Держать нечего: сессия общая, своих задач нет."""
    return True
