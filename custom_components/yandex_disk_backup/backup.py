"""Агент резервных копий: Яндекс.Диск как место хранения.

Раскладка на Диске такая же, как у штатного агента WebDAV — архив плюс
файл метаданных рядом. Список копий строится по метаданным: в них лежит всё,
что интерфейс показывает о копии, и читать ради этого гигабайтный архив не
нужно. Метаданные маленькие, но их столько же, сколько копий, поэтому список
кэшируется, а кэш сбрасывается сразу после записи и удаления.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from functools import wraps
import logging
from time import time
from typing import Any, Concatenate

from homeassistant.components.backup import (
    AgentBackup,
    BackupAgent,
    BackupAgentError,
    BackupNotFound,
    OnProgressCallback,
    suggested_filename,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.json import json_dumps
from homeassistant.util.async_ import gather_with_limited_concurrency
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads_object

from . import YandexDiskConfigEntry
from .api import YandexDiskAuthError, YandexDiskError, YandexDiskNotFound
from .const import DATA_BACKUP_AGENT_LISTENERS, DOMAIN
from .paths import metadata_name

_LOGGER = logging.getLogger(__name__)

CACHE_TTL = 300
METADATA_CONCURRENCY = 4


async def async_get_backup_agents(hass: HomeAssistant) -> list[BackupAgent]:
    """Отдать по агенту на каждую настроенную учётную запись Диска."""
    entries: list[YandexDiskConfigEntry] = hass.config_entries.async_loaded_entries(
        DOMAIN
    )
    return [YandexDiskBackupAgent(entry) for entry in entries]


@callback
def async_register_backup_agents_listener(
    hass: HomeAssistant, *, listener: Callable[[], None], **kwargs: Any
) -> Callable[[], None]:
    """Дать менеджеру копий знать, когда агенты появляются и исчезают."""
    hass.data.setdefault(DATA_BACKUP_AGENT_LISTENERS, []).append(listener)

    @callback
    def remove_listener() -> None:
        hass.data[DATA_BACKUP_AGENT_LISTENERS].remove(listener)
        if not hass.data[DATA_BACKUP_AGENT_LISTENERS]:
            del hass.data[DATA_BACKUP_AGENT_LISTENERS]

    return remove_listener


def handle_disk_errors[_R, **P](
    func: Callable[Concatenate[YandexDiskBackupAgent, P], Coroutine[Any, Any, _R]],
) -> Callable[Concatenate[YandexDiskBackupAgent, P], Coroutine[Any, Any, _R]]:
    """Превратить ошибки Диска в те, что понимает менеджер копий.

    Без этого интерфейс показывает «неизвестная ошибка» вместо причины.
    """

    @wraps(func)
    async def wrapper(
        self: YandexDiskBackupAgent, *args: P.args, **kwargs: P.kwargs
    ) -> _R:
        try:
            return await func(self, *args, **kwargs)
        except YandexDiskAuthError as err:
            raise BackupAgentError(f"Яндекс.Диск: {err}") from err
        except YandexDiskError as err:
            _LOGGER.debug("Полная ошибка: %s", err, exc_info=True)
            raise BackupAgentError(f"Яндекс.Диск: {err}") from err
        except TimeoutError as err:
            raise BackupAgentError("Яндекс.Диск не ответил вовремя") from err

    return wrapper


def suggested_filenames(backup: AgentBackup) -> tuple[str, str]:
    """Имена архива и файла метаданных для копии."""
    tar_name = f"{suggested_filename(backup).rsplit('.', 1)[0]}.tar"
    return tar_name, metadata_name(tar_name)


class YandexDiskBackupAgent(BackupAgent):
    """Место хранения копий на Яндекс.Диске."""

    domain = DOMAIN

    def __init__(self, entry: YandexDiskConfigEntry) -> None:
        super().__init__()
        self._disk = entry.runtime_data
        self.name = entry.title
        self.unique_id = entry.entry_id
        self._cache: dict[str, AgentBackup] = {}
        self._cache_until = time()

    @handle_disk_errors
    async def async_upload_backup(
        self,
        *,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
        backup: AgentBackup,
        on_progress: OnProgressCallback,
        **kwargs: Any,
    ) -> None:
        """Залить архив, следом метаданные.

        Порядок важен: метаданные — признак того, что копия доехала целиком.
        Оборвись загрузка архива — на Диске останется огрызок, но в списке
        копий он не появится и на восстановление не предложится.
        """
        tar_name, meta_name = suggested_filenames(backup)

        await self._disk.upload(
            tar_name,
            await open_stream(),
            size=backup.size,
            on_progress=lambda sent: on_progress(bytes_uploaded=sent),
        )
        await self._disk.upload_bytes(
            meta_name, json_dumps(backup.as_dict()).encode("utf-8")
        )

        _LOGGER.debug("Копия уехала на Диск: %s", tar_name)
        self._cache_until = time()

    @handle_disk_errors
    async def async_download_backup(
        self, backup_id: str, **kwargs: Any
    ) -> AsyncIterator[bytes]:
        """Отдать архив копии."""
        backup = await self._find(backup_id)
        tar_name, _ = suggested_filenames(backup)
        return await self._disk.download(tar_name)

    @handle_disk_errors
    async def async_delete_backup(self, backup_id: str, **kwargs: Any) -> None:
        """Удалить архив и метаданные."""
        backup = await self._find(backup_id)
        tar_name, meta_name = suggested_filenames(backup)

        await self._disk.delete(tar_name)
        await self._disk.delete(meta_name)

        _LOGGER.debug("Копия удалена с Диска: %s", tar_name)
        self._cache_until = time()

    @handle_disk_errors
    async def async_list_backups(self, **kwargs: Any) -> list[AgentBackup]:
        """Список копий на Диске."""
        return list((await self._metadata()).values())

    @handle_disk_errors
    async def async_get_backup(self, backup_id: str, **kwargs: Any) -> AgentBackup:
        """Одна копия по идентификатору."""
        return await self._find(backup_id)

    async def _find(self, backup_id: str) -> AgentBackup:
        backup = (await self._metadata()).get(backup_id)
        if backup is None:
            raise BackupNotFound(f"На Яндекс.Диске нет копии {backup_id}")
        return backup

    async def _metadata(self) -> dict[str, AgentBackup]:
        """Прочитать метаданные всех копий, не чаще раза в CACHE_TTL секунд."""
        if time() <= self._cache_until:
            return self._cache

        async def read(name: str) -> AgentBackup | None:
            try:
                raw = await self._disk.read_bytes(name)
            except YandexDiskNotFound:
                # Файл исчез между листингом и чтением — просто пропускаем.
                return None
            try:
                return AgentBackup.from_dict(json_loads_object(raw))
            except (*JSON_DECODE_EXCEPTIONS, KeyError, TypeError, ValueError) as err:
                _LOGGER.warning("Пропускаю испорченные метаданные %s: %s", name, err)
                return None

        names = await self._disk.list_metadata_names()
        found = await gather_with_limited_concurrency(
            METADATA_CONCURRENCY, *(read(name) for name in names)
        )

        self._cache = {item.backup_id: item for item in found if item}
        self._cache_until = time() + CACHE_TTL
        return self._cache
