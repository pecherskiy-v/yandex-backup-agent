"""Интеграция «Яндекс.Диск (копии)» — место хранения резервных копий HA."""

from __future__ import annotations

from aiohttp import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YandexDisk, YandexDiskAuthError, YandexDiskError
from .const import CONF_FOLDER, DATA_BACKUP_AGENT_LISTENERS, DEFAULT_FOLDER, DOMAIN

type YandexDiskConfigEntry = ConfigEntry[YandexDisk]


async def async_setup_entry(hass: HomeAssistant, entry: YandexDiskConfigEntry) -> bool:
    """Поднять сессию OAuth, проверить доступ и отдать агента менеджеру копий."""
    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    async def access_token() -> str:
        """Действующий токен: HA обновит его сам, если срок вышел."""
        try:
            await session.async_ensure_token_valid()
        except ClientError as err:
            # Отказ обновить — почти всегда отозванный доступ. Просим
            # переавторизоваться, а не молчим до ночной копии.
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="token_refresh_failed"
            ) from err
        return session.token["access_token"]

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
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    return True


async def _reload_on_options(
    hass: HomeAssistant, entry: YandexDiskConfigEntry
) -> None:
    """Папку сменили — пересобрать агента, иначе он пишет по-старому."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: YandexDiskConfigEntry) -> bool:
    """Выгрузить запись. Держать нечего: сессия общая, своих задач нет."""
    return True
