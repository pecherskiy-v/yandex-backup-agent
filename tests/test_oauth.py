"""Срок жизни доступа, ссылка на разрешение и разбор отказов Яндекса.

Сеть не нужна: проверяется только то, что считается на месте. Обмен кода и
обновление ходят наружу и живут в `oauth`, который тянет aiohttp.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "custom_components" / "yandex_disk_backup"


def _load(name):
    """Загрузить модуль компонента поодиночке.

    Импортировать пакет целиком нельзя: его `__init__` тянет Home Assistant.
    Поэтому подкладываем пустышку-пакет, чтобы относительные импорты внутри
    модулей находили соседей.
    """
    package = sys.modules.setdefault("ydb", types.ModuleType("ydb"))
    package.__path__ = [str(SRC)]

    spec = importlib.util.spec_from_file_location(f"ydb.{name}", SRC / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# `tokens` намеренно не тянет ни aiohttp, ни Home Assistant — иначе эти
# проверки нельзя было бы гонять на машине разработчика.
oauth = _load("tokens")


class Expiry(unittest.TestCase):
    def test_expires_at_counted_from_now(self):
        """Храним момент, а не длительность: после перезапуска HA от неё
        нечего отсчитывать."""
        self.assertEqual(
            oauth.token_expires_at({"expires_in": 100}, now=1000.0), 1100.0
        )

    def test_missing_expires_in_is_already_stale(self):
        self.assertEqual(oauth.token_expires_at({}, now=1000.0), 1000.0)

    def test_fresh_token(self):
        token = {"expires_at": 10000.0}
        self.assertTrue(oauth.token_is_fresh(token, now=1000.0))

    def test_margin_before_expiry(self):
        """За час до конца токен считается несвежим — иначе он протухнет
        посреди многочасовой загрузки архива."""
        token = {"expires_at": 5000.0}
        self.assertFalse(
            oauth.token_is_fresh(token, now=5000.0 - oauth.EXPIRY_MARGIN + 1)
        )
        self.assertTrue(
            oauth.token_is_fresh(token, now=5000.0 - oauth.EXPIRY_MARGIN - 1)
        )

    def test_token_without_expiry_is_stale(self):
        self.assertFalse(oauth.token_is_fresh({}, now=0.0))


class AuthorizeUrl(unittest.TestCase):
    def test_asks_for_code_not_token(self):
        """Нужен именно код: его обмен даёт refresh-токен, а неявный поток —
        нет, и тогда доступ пришлось бы продлевать руками."""
        url = oauth.authorize_url("abc123")
        self.assertIn("response_type=code", url)
        self.assertIn("client_id=abc123", url)

    def test_escapes_client_id(self):
        self.assertIn("client_id=a%2Bb", oauth.authorize_url("a+b"))


class Explain(unittest.TestCase):
    def test_known_errors_are_translated(self):
        self.assertIn("уже использован", oauth.explain({"error": "invalid_grant"}, 400))
        self.assertIn("секрет", oauth.explain({"error": "invalid_client"}, 401))

    def test_unknown_error_keeps_description(self):
        self.assertIn(
            "что-то своё",
            oauth.explain({"error": "x", "error_description": "что-то своё"}, 400),
        )

    def test_non_json_body(self):
        self.assertIn("500", oauth.explain("<html>", 500))


if __name__ == "__main__":
    unittest.main()
