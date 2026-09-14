"""Тонкий клиент Яндекс.Диска поверх его REST API.

Почему не WebDAV: у Диска он есть, но большие файлы через него не уезжают —
сервер принимает тело PUT и не отвечает, соединение висит и умирает по
таймауту. REST-загрузка устроена иначе: сначала берётся одноразовая ссылка,
и файл льётся уже на storage-узел, как это делает родной клиент.

Здесь только транспорт. Всё, что можно посчитать без сети, лежит в `paths`.

Токен не хранится: он берётся у Home Assistant перед каждым запросом. HA
сам обновляет его по refresh-токену, поэтому долгая загрузка не обрывается
на полпути из-за протухшего доступа, а нам не нужно ничего перевыпускать.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import json
import logging
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import API, CONNECT_TIMEOUT, TOTAL_TIMEOUT
from .paths import folder_chain, normalize_folder, pick_metadata_names, remote_path

_LOGGER = logging.getLogger(__name__)

#: Диск отдаёт листинг страницами; у копий их редко больше одной.
PAGE = 200


class YandexDiskError(Exception):
    """Любая ошибка Диска, уже с человеческим текстом."""


class YandexDiskAuthError(YandexDiskError):
    """Токен не принят или протух."""


class YandexDiskNotFound(YandexDiskError):
    """Файла или папки на Диске нет."""


class YandexDisk:
    """Операции, которые нужны агенту копий, и ни одной лишней."""

    def __init__(
        self,
        session: ClientSession,
        token: Callable[[], Awaitable[str]],
        folder: str,
    ) -> None:
        self._session = session
        self._token = token
        self.folder = normalize_folder(folder)

    async def _auth_headers(self) -> dict[str, str]:
        """Свежий токен на каждый запрос — его мог обновить HA."""
        return {
            "Authorization": f"OAuth {await self._token()}",
            "Accept": "application/json",
        }

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        allow: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        """Вызов API с разбором ошибки в исключение.

        `allow` — коды, которые для вызывающего не ошибка (например 409
        «папка уже есть»): вернётся пустой словарь.
        """
        url = f"{API}{path}"
        timeout = ClientTimeout(connect=CONNECT_TIMEOUT, total=120)
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                headers=await self._auth_headers(),
                timeout=timeout,
            ) as resp:
                if resp.status in allow:
                    return {}
                if resp.status == 401:
                    raise YandexDiskAuthError(
                        "Яндекс не принял токен — он отозван или истёк"
                    )
                if resp.status == 404:
                    raise YandexDiskNotFound(f"на Диске нет {params or path}")
                if resp.status >= 400:
                    raise YandexDiskError(await _explain(resp))
                if resp.status == 204:
                    return {}
                # По длине тела судить нельзя: часть ответов Диск отдаёт
                # chunked, без Content-Length — и ссылка на загрузку как раз
                # из таких. Раньше мы принимали их за пустые.
                body = (await resp.text()).strip()
                if not body:
                    return {}
                try:
                    return json.loads(body)
                except ValueError as err:
                    raise YandexDiskError(
                        f"Диск ответил не JSON: {body[:120]}"
                    ) from err
        except ClientError as err:
            raise YandexDiskError(f"Диск недоступен: {err}") from err

    async def account(self) -> dict[str, Any]:
        """Сведения о Диске — заодно проверка токена.

        Поля перечисляем явно: без `fields` Диск не отдаёт блок `user`, и
        запись получает имя «Яндекс.Диск · disk» вместо логина.
        """
        return await self._call(
            "GET",
            "/",
            params={"fields": "user.login,user.display_name,total_space,used_space"},
        )

    async def ensure_folder(self) -> None:
        """Создать папку копий вместе со всеми родительскими."""
        for step in folder_chain(self.folder):
            await self._call(
                "PUT", "/resources", params={"path": step}, allow=(409,)
            )

    async def list_metadata_names(self) -> list[str]:
        """Имена всех файлов метаданных в папке копий.

        Пустая или отсутствующая папка — не ошибка: копий просто нет.
        """
        names: list[str] = []
        offset = 0
        while True:
            try:
                body = await self._call(
                    "GET",
                    "/resources",
                    params={
                        "path": self.folder,
                        "limit": PAGE,
                        "offset": offset,
                        "fields": "_embedded.items.name,_embedded.items.type,"
                        "_embedded.total",
                    },
                )
            except YandexDiskNotFound:
                return []
            embedded = body.get("_embedded") or {}
            items = embedded.get("items") or []
            names.extend(pick_metadata_names(items))
            offset += len(items)
            if not items or offset >= int(embedded.get("total") or 0):
                return names

    async def upload(
        self,
        name: str,
        stream: AsyncIterator[bytes],
        *,
        size: int | None = None,
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        """Залить файл: взять одноразовую ссылку и отдать тело на неё.

        Размер передаём заголовком, если знаем: иначе aiohttp уйдёт в
        chunked, а именно на нём Диск и спотыкается.
        """
        href = (
            await self._call(
                "GET",
                "/resources/upload",
                params={"path": remote_path(self.folder, name), "overwrite": "true"},
            )
        ).get("href")
        if not href:
            raise YandexDiskError("Диск не дал ссылку на загрузку")

        headers = {}
        if size is not None:
            headers["Content-Length"] = str(size)

        body = _counted(stream, on_progress) if on_progress else stream
        timeout = ClientTimeout(connect=CONNECT_TIMEOUT, total=TOTAL_TIMEOUT)
        try:
            async with self._session.put(
                href, data=body, headers=headers, timeout=timeout
            ) as resp:
                if resp.status >= 400:
                    raise YandexDiskError(await _explain(resp))
        except ClientError as err:
            raise YandexDiskError(f"загрузка сорвалась: {err}") from err

    async def upload_bytes(self, name: str, payload: bytes) -> None:
        """Залить маленький файл целиком — им бывают только метаданные."""

        async def one_chunk() -> AsyncIterator[bytes]:
            yield payload

        await self.upload(name, one_chunk(), size=len(payload))

    async def download(self, name: str) -> AsyncIterator[bytes]:
        """Отдать содержимое файла кусками."""
        href = (
            await self._call(
                "GET",
                "/resources/download",
                params={"path": remote_path(self.folder, name)},
            )
        ).get("href")
        if not href:
            raise YandexDiskError("Диск не дал ссылку на скачивание")

        timeout = ClientTimeout(connect=CONNECT_TIMEOUT, total=TOTAL_TIMEOUT)
        try:
            resp = await self._session.get(href, timeout=timeout)
            if resp.status >= 400:
                raise YandexDiskError(await _explain(resp))
        except ClientError as err:
            raise YandexDiskError(f"скачивание сорвалось: {err}") from err

        async def chunks() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    yield chunk
            finally:
                resp.release()

        return chunks()

    async def read_bytes(self, name: str) -> bytes:
        """Прочитать файл целиком — только для метаданных."""
        buffer = bytearray()
        async for chunk in await self.download(name):
            buffer.extend(chunk)
        return bytes(buffer)

    async def delete(self, name: str) -> None:
        """Удалить файл мимо корзины.

        Мимо — потому что корзина Диска считается в тот же объём, и копии,
        которые HA считает удалёнными, продолжали бы занимать место.
        """
        await self._call(
            "DELETE",
            "/resources",
            params={"path": remote_path(self.folder, name), "permanently": "true"},
            allow=(404,),
        )


async def _counted(
    stream: AsyncIterator[bytes], on_progress: Callable[[int], None]
) -> AsyncIterator[bytes]:
    """Обёртка, которая считает отданные байты для индикатора в интерфейсе."""
    sent = 0
    async for chunk in stream:
        sent += len(chunk)
        on_progress(sent)
        yield chunk


async def _explain(resp: Any) -> str:
    """Достать из ответа человеческую причину отказа."""
    try:
        body = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001 — тело может быть чем угодно
        body = None
    if isinstance(body, dict):
        message = body.get("message") or body.get("description") or body.get("error")
        if message:
            return f"{message} (HTTP {resp.status})"
    return f"Диск ответил HTTP {resp.status}"
