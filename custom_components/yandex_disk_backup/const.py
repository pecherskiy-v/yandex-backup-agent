"""Константы интеграции «Яндекс.Диск (копии)»."""

from __future__ import annotations

DOMAIN = "yandex_disk_backup"

CONF_TOKEN = "token"
CONF_FOLDER = "folder"

DEFAULT_FOLDER = "Home Assistant/backups"

#: Слушатели, которых менеджер копий просит позвать при появлении агента.
DATA_BACKUP_AGENT_LISTENERS = f"{DOMAIN}.backup_agent_listeners"

API = "https://cloud-api.yandex.net/v1/disk"

#: Сколько ждать ответа. Загрузка большого архива идёт часами на медленном
#: канале, поэтому общий таймаут щедрый, а вот соединение должно установиться
#: быстро — иначе мы часами ждём мёртвый хост.
CONNECT_TIMEOUT = 15
TOTAL_TIMEOUT = 43200
