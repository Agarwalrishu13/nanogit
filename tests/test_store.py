"""What nanoGit remembers between visits.

Every test here runs against a temporary NANOGIT_HOME, so nobody's real
``~/.nanogit`` is ever read or written.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nanogit import store


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {"NANOGIT_HOME": str(self.home)})
        self._env.start()
        self.addCleanup(self._env.stop)

    def tearDown(self):
        self._tmp.cleanup()


class SettingsTests(StoreTestCase):
    def test_the_defaults_are_sensible(self):
        settings = store.load_settings()
        self.assertEqual(settings["author_name"], "")
        self.assertTrue(settings["publish_private"])

    def test_saving_and_loading(self):
        store.save_settings({"author_name": "Priyanshu", "author_email": "p@localhost"})
        loaded = store.load_settings()
        self.assertEqual(loaded["author_name"], "Priyanshu")
        self.assertEqual(loaded["author_email"], "p@localhost")

    def test_saving_one_thing_keeps_the_others(self):
        store.save_settings({"author_name": "One"})
        store.save_settings({"author_email": "two@localhost"})
        loaded = store.load_settings()
        self.assertEqual(loaded["author_name"], "One")
        self.assertEqual(loaded["author_email"], "two@localhost")

    def test_keys_nobody_knows_are_ignored(self):
        store.save_settings({"author_name": "Fine", "rm -rf": "no"})
        self.assertNotIn("rm -rf", store.load_settings())

    def test_a_corrupt_settings_file_is_survived(self):
        store.data_dir().joinpath("settings.json").write_text("{ this is not json", encoding="utf-8")
        self.assertEqual(store.load_settings()["author_name"], "")

    def test_a_settings_file_that_is_a_list_is_survived(self):
        store.data_dir().joinpath("settings.json").write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(store.load_settings()["author_name"], "")

    def test_the_data_folder_is_made_if_it_is_missing(self):
        self.assertTrue(store.data_dir().is_dir())

    def test_the_folder_is_named_after_the_app(self):
        self.assertEqual(store.APP_DIR_NAME, ".nanogit")


class RecentFolderTests(StoreTestCase):
    def test_nothing_remembered_at_first(self):
        self.assertEqual(store.recent_folders(), [])

    def test_a_folder_that_exists_is_remembered(self):
        store.remember_folder(self.home, "My Project")
        entries = store.recent_folders()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], str(self.home))
        self.assertEqual(entries[0]["note"], "My Project")

    def test_the_newest_is_first(self):
        second = self.home / "second"
        second.mkdir()
        store.remember_folder(self.home, "first")
        store.remember_folder(second, "second")
        self.assertEqual(store.recent_folders()[0]["note"], "second")

    def test_the_same_folder_is_not_listed_twice(self):
        store.remember_folder(self.home, "one")
        store.remember_folder(self.home, "two")
        self.assertEqual(len(store.recent_folders()), 1)
        self.assertEqual(store.recent_folders()[0]["note"], "two")

    def test_forgetting(self):
        store.remember_folder(self.home, "x")
        store.forget_folder(self.home)
        self.assertEqual(store.recent_folders(), [])

    def test_a_folder_that_has_since_been_deleted_is_not_offered(self):
        gone = self.home / "gone"
        gone.mkdir()
        store.remember_folder(gone, "gone")
        gone.rmdir()
        self.assertEqual(store.recent_folders(), [])

    def test_the_list_does_not_grow_for_ever(self):
        for index in range(store.MAX_RECENT + 6):
            folder = self.home / ("f%d" % index)
            folder.mkdir()
            store.remember_folder(folder, str(index))
        self.assertEqual(len(store.recent_folders()), store.MAX_RECENT)
        self.assertEqual(store.recent_folders()[0]["note"], str(store.MAX_RECENT + 5))

    def test_a_corrupt_recent_file_is_survived(self):
        store.data_dir().joinpath("recent.json").write_text("nonsense", encoding="utf-8")
        self.assertEqual(store.recent_folders(), [])

    def test_a_recent_file_of_the_wrong_shape_is_survived(self):
        store.data_dir().joinpath("recent.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
        self.assertEqual(store.recent_folders(), [])

    def test_remembering_survives_a_read_only_folder(self):
        # Nothing about a read-only home directory should stop the app working.
        with mock.patch.object(store, "_write", side_effect=OSError("read-only")):
            store.remember_folder(self.home, "x")  # must not raise


if __name__ == "__main__":
    unittest.main()
