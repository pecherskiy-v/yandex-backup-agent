"""Сервис `yandex_disk_backup.upload_existing` — залить на Диск копию,
которая уже лежит в другом месте хранения.

Штатная кнопка «Загрузить в другое место» в Home Assistant 2026.9 ведёт
через приём файла Supervisor'ом и падает там на своём же баге
(`hassio/backup.py`, `KeyError: '.cloud_backup'`) — независимо от того, куда
копию отправляют. Здесь файл никуда не выгружается наружу: поток берётся
у агента-источника и сразу отдаётся нашему, всё внутри HA.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import logging

import voluptuous as vol

from homeassistant.components.backup import BackupAgent, BackupNotFound
from homeassistant.components.backup.const import DATA_MANAGER
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_UPLOAD_EXISTING = "upload_existing"
ATTR_BACKUP_ID = "backup_id"
ATTR_SOURCE = "source_agent_id"

DEFAULT_SOURCE = "hassio.local"

SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BACKUP_ID): cv.string,
        vol.Optional(ATTR_SOURCE, default=DEFAULT_SOURCE): cv.string,
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Зарегистрировать сервис один раз на всю интеграцию."""

    async def upload_existing(call: ServiceCall) -> None:
        manager = hass.data[DATA_MANAGER]
        backup_id = call.data[ATTR_BACKUP_ID]
        source_id = call.data[ATTR_SOURCE]

        source = manager.backup_agents.get(source_id)
        if source is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_source",
                translation_placeholders={"agent_id": source_id},
            )

        targets = [
            agent
            for agent_id, agent in manager.backup_agents.items()
            if agent_id.startswith(f"{DOMAIN}.")
        ]
        if not targets:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_target"
            )

        try:
            meta = await source.async_get_backup(backup_id)
        except BackupNotFound as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_backup",
                translation_placeholders={"backup_id": backup_id},
            ) from err

        async def open_stream() -> AsyncIterator[bytes]:
            return await source.async_download_backup(backup_id)

        for target in targets:
            _LOGGER.info(
                "Переливаю копию %s (%s) из %s на %s",
                meta.name,
                backup_id,
                source_id,
                target.name,
            )
            await target.async_upload_backup(
                open_stream=open_stream,
                backup=meta,
                # Прогресс некуда показывать: сервис не создаёт задание в
                # менеджере копий, за ходом видно по журналу.
                on_progress=lambda **kwargs: None,
            )
            _LOGGER.info("Копия %s теперь есть на %s", meta.name, target.name)

    hass.services.async_register(
        DOMAIN, SERVICE_UPLOAD_EXISTING, upload_existing, schema=SCHEMA
    )
