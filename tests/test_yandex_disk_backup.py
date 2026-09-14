"""Пути и имена файлов агента Яндекс.Диска.

Сеть тут не нужна: всё, что можно посчитать без Диска, вынесено в `paths`,
и именно это проверяется. Остальной код компонента живёт внутри Home
Assistant и здесь не импортируется — aiohttp на машине разработчика нет.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "custom_components" / "yandex_disk_backup" / "paths.py"

spec = importlib.util.spec_from_file_location("yadisk_paths", SRC)
paths = importlib.util.module_from_spec(spec)
sys.modules["yadisk_paths"] = paths
spec.loader.exec_module(paths)


class NormalizeFolder(unittest.TestCase):
    def test_forms_collapse_to_one(self):
        """Как папку ни напиши — на API уходит одна и та же форма."""
        for written in ("Backups", "/Backups", "Backups/", "disk:/Backups",
                        "//Backups//", "\\Backups"):
            with self.subTest(written=written):
                self.assertEqual(paths.normalize_folder(written), "disk:/Backups")

    def test_keeps_spaces_and_nesting(self):
        self.assertEqual(
            paths.normalize_folder("Home Assistant/backups"),
            "disk:/Home Assistant/backups",
        )

    def test_drops_dot_segments(self):
        """`..` не должен выводить из папки копий на чужой Диск."""
        self.assertEqual(paths.normalize_folder("a/../../b"), "disk:/a/b")

    def test_empty_is_root(self):
        self.assertEqual(paths.normalize_folder(""), "disk:/")


class FolderChain(unittest.TestCase):
    def test_every_level_listed(self):
        """У Диска нет mkdir -p: каждый уровень создаётся отдельно."""
        self.assertEqual(
            paths.folder_chain("Home Assistant/backups"),
            ["disk:/Home Assistant", "disk:/Home Assistant/backups"],
        )

    def test_single_level(self):
        self.assertEqual(paths.folder_chain("/Backups"), ["disk:/Backups"])

    def test_root_has_nothing_to_create(self):
        self.assertEqual(paths.folder_chain(""), [])


class Names(unittest.TestCase):
    def test_remote_path_joins(self):
        self.assertEqual(
            paths.remote_path("Backups/", "copy.tar"), "disk:/Backups/copy.tar"
        )

    def test_metadata_name_replaces_extension(self):
        self.assertEqual(
            paths.metadata_name("Automatic_backup_2026.9.2.tar"),
            "Automatic_backup_2026.9.2.metadata.json",
        )

    def test_metadata_name_keeps_dots_in_name(self):
        """Точки в имени — это версия HA, а не расширение."""
        self.assertTrue(paths.metadata_name("a.b.c.tar").endswith(".metadata.json"))
        self.assertTrue(paths.metadata_name("a.b.c.tar").startswith("a.b.c"))

    def test_is_metadata(self):
        self.assertTrue(paths.is_metadata("x.metadata.json"))
        self.assertFalse(paths.is_metadata("x.tar"))


class PickMetadata(unittest.TestCase):
    def test_only_metadata_files(self):
        items = [
            {"type": "file", "name": "a.tar"},
            {"type": "file", "name": "a.metadata.json"},
            {"type": "file", "name": "b.metadata.json"},
        ]
        self.assertEqual(
            paths.pick_metadata_names(items), ["a.metadata.json", "b.metadata.json"]
        )

    def test_folder_with_metadata_name_ignored(self):
        """Папка может называться как угодно — читать её как файл нельзя."""
        items = [{"type": "dir", "name": "old.metadata.json"}]
        self.assertEqual(paths.pick_metadata_names(items), [])

    def test_empty_listing(self):
        self.assertEqual(paths.pick_metadata_names([]), [])


if __name__ == "__main__":
    unittest.main()
