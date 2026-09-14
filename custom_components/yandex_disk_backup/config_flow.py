"""Подключение: ClientID с секретом, код подтверждения, папка.

Код вставляется один раз. Дальше доступ продлевается сам по refresh-токену,
так что возвращаться к этой форме не придётся — разве что доступ отзовут в
настройках Яндекса.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import YandexDisk, YandexDiskAuthError, YandexDiskError
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_CODE,
    CONF_FOLDER,
    CONF_TOKEN,
    DEFAULT_FOLDER,
    DOMAIN,
)
from .oauth import OAuthError, YandexOAuth
from .tokens import authorize_url
from .paths import normalize_folder

_LOGGER = logging.getLogger(__name__)

APP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_CLIENT_SECRET): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)
CODE_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})
FOLDER_SCHEMA = vol.Schema({vol.Optional(CONF_FOLDER, default=DEFAULT_FOLDER): str})


class YandexDiskBackupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Три коротких шага вместо выпуска токена руками."""

    VERSION = 1

    def __init__(self) -> None:
        self._app: dict[str, str] = {}
        self._token: dict[str, Any] = {}
        self._login = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """ClientID и секрет приложения Яндекса."""
        if user_input is not None:
            self._app = {
                CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
            }
            return await self.async_step_code()

        return self.async_show_form(step_id="user", data_schema=APP_SCHEMA)

    async def async_step_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Разрешение в Яндексе и код подтверждения с его страницы."""
        errors: dict[str, str] = {}
        link = authorize_url(self._app[CONF_CLIENT_ID])

        if user_input is not None:
            oauth = YandexOAuth(
                async_get_clientsession(self.hass),
                self._app[CONF_CLIENT_ID],
                self._app[CONF_CLIENT_SECRET],
            )
            try:
                self._token = await oauth.exchange_code(user_input[CONF_CODE])
            except OAuthError as err:
                _LOGGER.debug("Код не обменялся: %s", err, exc_info=True)
                errors[CONF_CODE] = "invalid_code"
            else:
                return await self._identify()

        return self.async_show_form(
            step_id="code",
            data_schema=CODE_SCHEMA,
            errors=errors,
            description_placeholders={"authorize_url": link},
        )

    async def _identify(self) -> ConfigFlowResult:
        """Узнать, чей это Диск, и не дать подключить его дважды."""
        disk = YandexDisk(
            async_get_clientsession(self.hass),
            _fixed_token(self._token["access_token"]),
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

        await self.async_set_unique_id(self._login)
        if self.source == SOURCE_REAUTH:
            # Чужой Диск вместо прежнего сделал бы старые копии недоступными.
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            entry = self._get_reauth_entry()
            return self.async_update_reload_and_abort(
                entry, data={**entry.data, **self._app, CONF_TOKEN: self._token}
            )

        self._abort_if_unique_id_configured()
        return await self.async_step_folder()

    async def async_step_folder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Куда класть копии. Папку создаём сразу — права проверяются здесь.

        Иначе о нехватке прав узнаёшь ночью, когда не уедет первая копия.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            folder = normalize_folder(user_input.get(CONF_FOLDER, DEFAULT_FOLDER))
            disk = YandexDisk(
                async_get_clientsession(self.hass),
                _fixed_token(self._token["access_token"]),
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
                    data={
                        **self._app,
                        CONF_TOKEN: self._token,
                        CONF_FOLDER: folder,
                    },
                )

        return self.async_show_form(
            step_id="folder",
            data_schema=FOLDER_SCHEMA,
            errors=errors,
            description_placeholders={"login": self._login},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Доступ отозвали — берём новый код, приложение и папку не трогаем."""
        self._app = {
            CONF_CLIENT_ID: entry_data[CONF_CLIENT_ID],
            CONF_CLIENT_SECRET: entry_data[CONF_CLIENT_SECRET],
        }
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_code()

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
                # Старые копии остаются в прежней папке: HA перестанет их
                # показывать, но и не удалит — переносить решает владелец.
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
