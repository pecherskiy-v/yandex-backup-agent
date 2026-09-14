"""Мастер подключения: токен Яндекса и папка для копий."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import YandexDisk, YandexDiskAuthError, YandexDiskError
from .const import CONF_FOLDER, CONF_TOKEN, DEFAULT_FOLDER, DOMAIN
from .paths import normalize_folder

_LOGGER = logging.getLogger(__name__)

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_FOLDER, default=DEFAULT_FOLDER): str,
    }
)


class YandexDiskBackupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Один шаг: проверить токен и сразу создать папку."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            login, errors = await self._check(
                user_input[CONF_TOKEN], user_input.get(CONF_FOLDER, DEFAULT_FOLDER)
            )
            if not errors:
                # Один Диск — одна запись: иначе копии разъедутся по дублям.
                await self.async_set_unique_id(login)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Яндекс.Диск · {login}",
                    data={
                        CONF_TOKEN: user_input[CONF_TOKEN],
                        CONF_FOLDER: normalize_folder(
                            user_input.get(CONF_FOLDER, DEFAULT_FOLDER)
                        ),
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Токен отозвали — просим новый, не теряя настроенную папку."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            folder = entry.data.get(CONF_FOLDER, DEFAULT_FOLDER)
            login, errors = await self._check(user_input[CONF_TOKEN], folder)
            if not errors:
                await self.async_set_unique_id(login)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: user_input[CONF_TOKEN]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    async def _check(self, token: str, folder: str) -> tuple[str, dict[str, str]]:
        """Сходить на Диск: токен живой, папка есть или создалась.

        Папку проверяем прямо в мастере — иначе о нехватке прав узнаешь
        только ночью, когда не уедет первая копия.
        """
        disk = YandexDisk(async_get_clientsession(self.hass), token, folder)
        try:
            account = await disk.account()
            await disk.ensure_folder()
        except YandexDiskAuthError:
            return "", {CONF_TOKEN: "invalid_token"}
        except YandexDiskError as err:
            _LOGGER.debug("Диск недоступен: %s", err, exc_info=True)
            return "", {"base": "cannot_connect"}

        user = account.get("user") or {}
        return user.get("login") or user.get("uid") or "disk", {}
