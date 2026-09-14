"""Подключение через OAuth Яндекса плюс выбор папки.

Ручной токен здесь не спрашивают: ClientID и секрет вводятся один раз в
«Учётных данных приложения», дальше Home Assistant сам открывает страницу
разрешений Яндекса и сам обновляет доступ.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YandexDisk, YandexDiskAuthError, YandexDiskError
from .const import CONF_FOLDER, DEFAULT_FOLDER, DOMAIN
from .paths import normalize_folder

_LOGGER = logging.getLogger(__name__)


class YandexDiskOAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Мастер: разрешение в Яндексе, потом папка на Диске."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, Any] = {}
        self._login: str = ""

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Доступ отозвали — проходим авторизацию заново, папку не трогаем."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Доступ получен: узнаём, чей это Диск."""
        disk = YandexDisk(
            async_get_clientsession(self.hass),
            _fixed_token(data["token"]["access_token"]),
            DEFAULT_FOLDER,
        )
        try:
            account = await disk.account()
        except YandexDiskAuthError:
            return self.async_abort(reason="invalid_auth")
        except YandexDiskError as err:
            _LOGGER.debug("Диск недоступен: %s", err, exc_info=True)
            return self.async_abort(reason="cannot_connect")

        user = account.get("user") or {}
        self._login = user.get("login") or user.get("uid") or "disk"
        self._data = data

        await self.async_set_unique_id(self._login)
        if self.source == SOURCE_REAUTH:
            # Чужой Диск вместо прежнего сделал бы копии недоступными.
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )

        self._abort_if_unique_id_configured()
        return await self.async_step_folder()

    async def async_step_folder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Куда класть копии. Папку сразу создаём — права проверяются здесь.

        Иначе о нехватке прав узнаёшь ночью, когда не уедет первая копия.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            folder = normalize_folder(user_input.get(CONF_FOLDER, DEFAULT_FOLDER))
            disk = YandexDisk(
                async_get_clientsession(self.hass),
                _fixed_token(self._data["token"]["access_token"]),
                folder,
            )
            try:
                await disk.ensure_folder()
            except YandexDiskError as err:
                _LOGGER.debug("Папка не создалась: %s", err, exc_info=True)
                errors[CONF_FOLDER] = "cannot_create_folder"
            else:
                return self.async_create_entry(
                    title=f"Яндекс.Диск · {self._login}",
                    data={**self._data, CONF_FOLDER: folder},
                )

        return self.async_show_form(
            step_id="folder",
            data_schema=vol.Schema(
                {vol.Optional(CONF_FOLDER, default=DEFAULT_FOLDER): str}
            ),
            errors=errors,
            description_placeholders={"login": self._login},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return YandexDiskOptionsFlow()


class YandexDiskOptionsFlow(OptionsFlow):
    """Смена папки без переподключения Диска."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        current = entry.data.get(CONF_FOLDER, DEFAULT_FOLDER)

        if user_input is not None:
            folder = normalize_folder(user_input[CONF_FOLDER])
            disk = entry.runtime_data
            previous, disk.folder = disk.folder, folder
            try:
                await disk.ensure_folder()
            except YandexDiskError as err:
                _LOGGER.debug("Папка не создалась: %s", err, exc_info=True)
                disk.folder = previous
                errors[CONF_FOLDER] = "cannot_create_folder"
            else:
                # Старые копии остаются лежать в прежней папке: HA перестанет
                # их показывать, но и не удалит — переносить решает владелец.
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_FOLDER: folder}
                )
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_FOLDER, default=current): str}),
            errors=errors,
        )


def _fixed_token(token: str):
    """Готовый токен в виде функции — API ждёт именно её."""

    async def getter() -> str:
        return token

    return getter
