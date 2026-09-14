"""Имена и пути на Диске — без сети и без зависимостей, чтобы можно было
проверить тестами на любой машине.

Раскладка на Диске повторяет то, что делает штатный агент WebDAV: рядом с
архивом лежит файл метаданных с тем же именем. Список копий строится по
метаданным, а не по архивам: архив без метаданных HA всё равно не покажет.
"""

from __future__ import annotations

METADATA_SUFFIX = ".metadata.json"


def normalize_folder(folder: str) -> str:
    """Привести папку к виду `disk:/a/b` без хвостового слеша.

    Пользователь пишет папку как ему удобно — `/Backups`, `Backups/`,
    `disk:/Backups`. На API уходит всегда одна и та же форма.
    """
    text = (folder or "").strip().replace("\\", "/")
    if text.startswith("disk:"):
        text = text[len("disk:"):]
    parts = [p for p in text.split("/") if p and p not in (".", "..")]
    return "disk:/" + "/".join(parts)


def folder_chain(folder: str) -> list[str]:
    """Все папки от корня до `folder` — их создают по очереди.

    API Диска не умеет `mkdir -p`: каждый уровень создаётся отдельно.
    """
    parts = normalize_folder(folder)[len("disk:/"):].split("/")
    chain: list[str] = []
    current = "disk:"
    for part in parts:
        if not part:
            continue
        current = f"{current}/{part}"
        chain.append(current)
    return chain


def remote_path(folder: str, name: str) -> str:
    """Путь файла внутри папки копий."""
    return f"{normalize_folder(folder)}/{name}"


def metadata_name(tar_name: str) -> str:
    """Имя файла метаданных для архива."""
    return tar_name.rsplit(".", 1)[0] + METADATA_SUFFIX


def is_metadata(name: str) -> bool:
    return name.endswith(METADATA_SUFFIX)


def pick_metadata_names(items: list[dict]) -> list[str]:
    """Выбрать из ответа листинга имена файлов метаданных.

    Папки пропускаем: вложенных копий не бывает, а имя папки может
    случайно оканчиваться на `.metadata.json`.
    """
    names = []
    for item in items:
        if item.get("type") != "file":
            continue
        name = item.get("name") or ""
        if is_metadata(name):
            names.append(name)
    return names
