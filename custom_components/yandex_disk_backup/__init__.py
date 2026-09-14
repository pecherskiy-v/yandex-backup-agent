"""Интеграция «Яндекс.Диск (копии)» — место хранения резервных копий HA."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YandexDisk, YandexDiskAuthError, YandexDiskError
from .const import CONF_FOLDER, CONF_TOKEN, DATA_BACKUP_AGENT_LISTENERS, DEFAULT_FOLDER, DOMAIN

type YandexDiskConfigEntry = ConfigEntry[YandexDisk]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: YandexDiskConfigEntry) -> bool:
    """Проверить токен, убедиться в наличии папки и отдать агента менеджеру копий."""
    disk = YandexDisk(
        async_get_clientsession(hass),
        entry.data[CONF_TOKEN],
        entry.data.get(CONF_FOLDER, DEFAULT_FOLDER),
    )

    try:
        await disk.account()
        await disk.ensure_folder()
    except YandexDiskAuthError as err:
        # Протухший токен сам не починится — просим перевыпустить, а не повторяем.
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="invalid_token"
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
