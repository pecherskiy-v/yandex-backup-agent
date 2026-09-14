"""Константы интеграции «Яндекс.Диск (копии)»."""

from __future__ import annotations

DOMAIN = "yandex_disk_backup"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_CODE = "code"
CONF_FOLDER = "folder"
CONF_TOKEN = "token"

DEFAULT_FOLDER = "Home Assistant/backups"

#: Слушатели, которых менеджер копий просит позвать при появлении агента.
DATA_BACKUP_AGENT_LISTENERS = f"{DOMAIN}.backup_agent_listeners"

OAUTH2_AUTHORIZE = "https://oauth.yandex.ru/authorize"
OAUTH2_TOKEN = "https://oauth.yandex.ru/token"

API = "https://cloud-api.yandex.net/v1/disk"

#: Сколько ждать ответа. Загрузка большого архива идёт часами на медленном
#: канале, поэтому общий таймаут щедрый, а вот соединение должно установиться
#: быстро — иначе мы часами ждём мёртвый хост.
CONNECT_TIMEOUT = 15
TOTAL_TIMEOUT = 43200
