"""The folder survey, tested against real folders built on the spot.

Nothing here is mocked: every folder is made in a temporary directory, looked
at, and thrown away. That is the only way to be sure the app is right about
somebody's actual files.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nanogit import survey


class SurveyTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, relative: str, text: str = "hello\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def survey(self, **kwargs):
        return survey.survey(str(self.root), **kwargs)


class CountingTests(SurveyTestCase):
    def test_counts_files_and_total_size(self):
        self.write("a.txt", "x" * 100)
        self.write("b.txt", "y" * 50)
        self.write("deeper/c.txt", "z" * 25)
        facts = self.survey()
        self.assertEqual(facts["file_count"], 3)
        self.assertEqual(facts["total_size"], 175)
        self.assertTrue(facts["ok"])

    def test_an_empty_folder_is_fine(self):
        facts = self.survey()
        self.assertEqual(facts["file_count"], 0)
        self.assertEqual(facts["total_size_text"], "0 bytes")
        self.assertEqual(facts["big_files"], [])

    def test_the_swamps_are_skipped(self):
        self.write("keep.txt")
        self.write(".git/config", "[core]")
        self.write("node_modules/left-pad/index.js", "module.exports = 1;")
        self.write("__pycache__/thing.cpython-311.pyc", "junk")
        self.write(".venv/lib/thing.py", "import os")
        facts = self.survey()
        self.assertEqual(facts["file_count"], 1)

    def test_a_missing_folder_is_an_error_not_a_crash(self):
        facts = survey.survey(str(self.root / "not-here"))
        self.assertFalse(facts["ok"])
        self.assertIn("no folder", facts["error"])

    def test_a_file_instead_of_a_folder_is_an_error(self):
        path = self.write("just-a-file.txt")
        facts = survey.survey(str(path))
        self.assertFalse(facts["ok"])


class ClassificationTests(SurveyTestCase):
    def test_a_python_project(self):
        self.write("requirements.txt", "flask\n")
        self.write("app.py", "import flask\n")
        facts = self.survey()
        self.assertEqual(facts["language"], "Python")
        self.assertIn("Python", facts["kind"])
        self.assertIn("requirements.txt", facts["markers"])

    def test_a_javascript_project(self):
        self.write("package.json", '{"name": "x"}')
        self.write("index.js", "console.log(1)")
        facts = self.survey()
        self.assertEqual(facts["language"], "JavaScript")

    def test_a_website_with_no_marker_files(self):
        self.write("index.html", "<h1>hi</h1>")
        self.write("style.css", "body{}")
        facts = self.survey()
        self.assertEqual(facts["kind"], "a website")

    def test_a_dotnet_project(self):
        self.write("Thing.sln", "Microsoft Visual Studio Solution File")
        facts = self.survey()
        self.assertIn(".NET", facts["kind"])

    def test_a_folder_of_documents(self):
        self.write("report.pdf", "%PDF-1.4")
        self.write("notes.docx", "PK")
        facts = self.survey()
        self.assertEqual(facts["kind"], "a folder of documents")

    def test_a_folder_of_pictures(self):
        self.write("one.jpg", "jpeg")
        self.write("two.png", "png")
        facts = self.survey()
        self.assertEqual(facts["kind"], "a folder of pictures")

    def test_media(self):
        self.write("clip.mp4", "video")
        self.write("song.mp3", "audio")
        facts = self.survey()
        self.assertIn("audio and video", facts["kind"])

    def test_an_unknown_folder_says_so_honestly(self):
        self.write("thing.xyzzy", "?")
        self.write("other.qqq", "?")
        facts = self.survey()
        self.assertEqual(facts["kind"], "a folder of files")

    def test_the_root_names_are_listed_for_the_readme_writer(self):
        self.write("run.sh", "#!/bin/sh")
        self.write("deep/inner.txt")
        facts = self.survey()
        self.assertIn("run.sh", facts["root_names"])
        self.assertNotIn("inner.txt", facts["root_names"])

    def test_a_readme_is_found_and_its_first_line_used(self):
        self.write("README.md", "# Crop Prices\n\nA school project about mandi rates.\n")
        facts = self.survey()
        self.assertTrue(facts["has_readme"])
        self.assertEqual(facts["description"], "Crop Prices")

    def test_a_missing_readme_leaves_the_description_empty(self):
        self.write("a.txt")
        facts = self.survey()
        self.assertFalse(facts["has_readme"])
        self.assertEqual(facts["description"], "")


class SecretTests(SurveyTestCase):
    def test_a_dotenv_file_is_found(self):
        self.write(".env", "SECRET=1")
        facts = self.survey()
        self.assertEqual([item["path"] for item in facts["secrets"]], [".env"])
        self.assertIn(".env*", facts["suggested_ignores"])

    def test_a_private_key_file_is_found(self):
        self.write("server.key", "-----BEGIN RSA PRIVATE KEY-----\n")
        facts = self.survey()
        self.assertEqual(len(facts["secrets"]), 1)

    def test_a_private_key_hiding_inside_an_ordinary_file_is_found(self):
        self.write("notes.txt", "here you go:\n-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n")
        facts = self.survey()
        self.assertEqual([item["path"] for item in facts["secrets"]], ["notes.txt"])

    def test_an_amazon_key_in_a_script_is_found(self):
        self.write("upload.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        facts = self.survey()
        self.assertEqual([item["path"] for item in facts["secrets"]], ["upload.py"])

    def test_a_password_written_in_plain_sight_is_found(self):
        self.write("config.ini", 'password = "hunter2hunter2"\n')
        facts = self.survey()
        self.assertEqual(len(facts["secrets"]), 1)

    def test_a_credentials_json_is_found(self):
        self.write("credentials.json", '{"token": "abc"}')
        facts = self.survey()
        self.assertEqual(len(facts["secrets"]), 1)

    def test_an_ssh_key_inside_a_hidden_folder_is_found(self):
        # .ssh is hidden, and normally skipped as a swamp — but not this one.
        self.write(".ssh/id_rsa", "-----BEGIN RSA PRIVATE KEY-----\n")
        facts = self.survey()
        self.assertEqual(len(facts["secrets"]), 1)

    def test_ordinary_files_are_not_accused(self):
        self.write("app.py", "import os\n\n\ndef main():\n    return os.getcwd()\n")
        self.write("README.md", "# A project\n\nNothing secret here.\n")
        self.write("package.json", '{"name": "x", "version": "1.0.0"}')
        facts = self.survey()
        self.assertEqual(facts["secrets"], [])

    def test_the_word_password_in_prose_is_not_a_secret(self):
        self.write("notes.md", "Remember to change your password on the school portal.\n")
        facts = self.survey()
        self.assertEqual(facts["secrets"], [])

    def test_a_large_file_is_not_content_scanned(self):
        # The scan only ever reads the first 256 KB, so an enormous file full of
        # keys is decided by its name — and this one has an innocent name.
        big = self.root / "huge.txt"
        big.write_text("x" * (300 * 1024) + 'password = "abcdefghij"', encoding="utf-8")
        facts = self.survey()
        self.assertEqual(facts["secrets"], [])


class BigFileTests(SurveyTestCase):
    def test_a_large_file_is_warned_about_but_allowed(self):
        self.write("media/clip.bin", "x" * 200)
        with mock.patch.object(survey, "BIG_WARN_BYTES", 100):
            facts = self.survey()
        self.assertEqual(len(facts["big_files"]), 1)
        self.assertFalse(facts["big_files"][0]["blocking"])

    def test_a_file_too_big_for_github_is_marked_blocking(self):
        self.write("dump.sql", "x" * 500)
        with mock.patch.object(survey, "BIG_WARN_BYTES", 100), mock.patch.object(survey, "BIG_REFUSE_BYTES", 400):
            facts = self.survey()
        self.assertTrue(facts["big_files"][0]["blocking"])
        self.assertIn("dump.sql", facts["suggested_ignores"])

    def test_largest_first(self):
        self.write("small.bin", "x" * 120)
        self.write("large.bin", "x" * 900)
        with mock.patch.object(survey, "BIG_WARN_BYTES", 100):
            facts = self.survey()
        self.assertEqual(facts["biggest"][0]["path"], "large.bin")


class TextHelperTests(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(survey.human_size(0), "0 bytes")
        self.assertEqual(survey.human_size(999), "999 bytes")
        self.assertEqual(survey.human_size(1024), "1.0 KB")
        self.assertEqual(survey.human_size(1536), "1.5 KB")
        self.assertEqual(survey.human_size(5 * 1024 * 1024), "5.0 MB")

    def test_slugify(self):
        self.assertEqual(survey.slugify("My Project"), "My-Project")
        self.assertEqual(survey.slugify("crop prices!! 2024"), "crop-prices-2024")
        self.assertEqual(survey.slugify(""), "my-project")
        self.assertEqual(survey.slugify("///"), "my-project")

    def test_nice_title(self):
        self.assertEqual(survey.nice_title("/tmp/my_cool_project"), "My Cool Project")
        self.assertEqual(survey.nice_title("/tmp/Already Fine"), "Already Fine")

    def test_a_name_that_is_all_punctuation_still_gives_a_title(self):
        self.assertTrue(survey.nice_title("/tmp/---"))


class BrowseTests(SurveyTestCase):
    def test_no_path_lists_places_to_start(self):
        data = survey.browse("")
        self.assertTrue(data["ok"])
        self.assertTrue(data["places"])
        self.assertEqual(data["folders"], [])

    def test_a_path_lists_its_folders_only(self):
        self.write("inner/thing.txt")
        self.write("loose.txt")
        data = survey.browse(str(self.root))
        names = [item["name"] for item in data["folders"]]
        self.assertIn("inner", names)
        self.assertNotIn("loose.txt", names)

    def test_a_tracked_folder_is_marked(self):
        (self.root / "tracked" / ".git").mkdir(parents=True)
        data = survey.browse(str(self.root))
        entry = next(item for item in data["folders"] if item["name"] == "tracked")
        self.assertEqual(entry["mark"], "tracked")

    def test_hidden_folders_are_left_out(self):
        (self.root / ".hidden").mkdir()
        data = survey.browse(str(self.root))
        self.assertNotIn(".hidden", [item["name"] for item in data["folders"]])

    def test_a_bad_path_is_an_error_not_a_crash(self):
        data = survey.browse(str(self.root / "nope"))
        self.assertFalse(data["ok"])


class LocateTests(SurveyTestCase):
    """'Find the folder I dragged in' — the thing that makes dragging work."""

    def test_finds_a_folder_a_few_levels_down(self):
        (self.root / "work" / "clients" / "acme").mkdir(parents=True)
        found = survey.locate_by_name("acme", roots=[self.root])
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].endswith("acme"))

    def test_matching_is_case_insensitive(self):
        (self.root / "MyProject").mkdir()
        found = survey.locate_by_name("myproject", roots=[self.root])
        self.assertEqual(len(found), 1)

    def test_the_shallowest_match_comes_first(self):
        (self.root / "DeEp" / "target").mkdir(parents=True)
        (self.root / "target").mkdir()
        found = survey.locate_by_name("target", roots=[self.root])
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0], str(self.root / "target"))

    def test_nothing_found_gives_an_empty_list(self):
        self.assertEqual(survey.locate_by_name("does-not-exist", roots=[self.root]), [])

    def test_a_blank_name_finds_nothing(self):
        self.assertEqual(survey.locate_by_name("", roots=[self.root]), [])
        self.assertEqual(survey.locate_by_name("..", roots=[self.root]), [])

    def test_hidden_folders_are_never_suggested(self):
        (self.root / ".secret-project").mkdir()
        self.assertEqual(survey.locate_by_name(".secret-project", roots=[self.root]), [])

    def test_node_modules_is_not_searched(self):
        (self.root / "node_modules" / "left-pad").mkdir(parents=True)
        self.assertEqual(survey.locate_by_name("left-pad", roots=[self.root]), [])

    def test_a_root_that_does_not_exist_is_skipped(self):
        self.assertEqual(survey.locate_by_name("x", roots=[self.root / "missing"]), [])


if __name__ == "__main__":
    unittest.main()
