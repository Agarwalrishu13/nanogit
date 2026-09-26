"""The README writer.

The thing being tested here is not the wording — it is that the README never
claims to know something it does not, and never overwrites writing that is
already there.
"""

import tempfile
import unittest
from pathlib import Path

from nanogit import readme


def fake_survey(**overrides) -> dict:
    base = {
        "ok": True,
        "path": "/tmp/crop-prices",
        "name": "crop-prices",
        "title": "Crop Prices",
        "file_count": 12,
        "total_size_text": "1.4 MB",
        "kind": "a Python project",
        "language": "Python",
        "because": "requirements.txt",
        "breakdown": [{"what": "Python", "count": 8}, {"what": "documents", "count": 4}],
        "biggest": [{"path": "data/prices.csv", "size_text": "1.1 MB"}],
        "secrets": [],
        "markers": ["requirements.txt"],
        "root_names": ["requirements.txt", "app.py"],
        "suggested_ignores": [],
        "has_readme": False,
    }
    base.update(overrides)
    return base


class BuildTests(unittest.TestCase):
    def test_the_name_goes_at_the_top(self):
        text = readme.build(fake_survey(), "Crop Prices", "")
        self.assertTrue(text.startswith("# Crop Prices\n"))

    def test_a_missing_description_leaves_a_space_to_write_one(self):
        text = readme.build(fake_survey(), "Crop Prices", "")
        self.assertIn("somewhere to write it", text)

    def test_a_given_description_is_used_as_it_is(self):
        text = readme.build(fake_survey(), "Crop Prices", "A school project about mandi rates.")
        self.assertIn("A school project about mandi rates.", text)

    def test_what_is_in_it_counts_and_weighs_the_folder(self):
        text = readme.build(fake_survey(), "Crop Prices", "")
        self.assertIn("12 files, 1.4 MB in total", text)
        self.assertIn("Largest file: `data/prices.csv` (1.1 MB)", text)

    def test_the_footer_says_a_program_wrote_this(self):
        text = readme.build(fake_survey(), "Crop Prices", "")
        self.assertIn("written by", text)
        self.assertIn("nanoGit", text)
        self.assertIn("edit it, it is yours", text)

    def test_private_files_are_named_and_explained(self):
        facts = fake_survey(secrets=[{"path": ".env", "what": "a file that usually holds a password or a key"}])
        text = readme.build(facts, "Crop Prices", "")
        self.assertIn("Things deliberately left out", text)
        self.assertIn("`.env`", text)


class HowToRunTests(unittest.TestCase):
    def test_python_with_requirements(self):
        text = readme.how_to_run(fake_survey())
        self.assertIn("pip install -r requirements.txt", text)

    def test_python_with_pyproject(self):
        text = readme.how_to_run(fake_survey(markers=["pyproject.toml"], root_names=["pyproject.toml"]))
        self.assertIn("pip install -e .", text)

    def test_node(self):
        text = readme.how_to_run(fake_survey(markers=["package.json"], root_names=["package.json"]))
        self.assertIn("npm install", text)

    def test_rust(self):
        text = readme.how_to_run(fake_survey(markers=["Cargo.toml"], root_names=["Cargo.toml"]))
        self.assertIn("cargo run", text)

    def test_go(self):
        text = readme.how_to_run(fake_survey(markers=["go.mod"], root_names=["go.mod"]))
        self.assertIn("go run .", text)

    def test_a_plain_website(self):
        text = readme.how_to_run(fake_survey(kind="a website", markers=[], root_names=["index.html", "style.css"]))
        self.assertIn("index.html", text)

    def test_something_unrecognised_gets_an_apology_not_a_guess(self):
        text = readme.how_to_run(fake_survey(kind="a folder of files", markers=[], root_names=["thing.dat"]))
        self.assertIn("could not tell", text)

    def test_the_readme_shows_the_apology_instead_of_inventing_steps(self):
        facts = fake_survey(kind="a folder of files", markers=[], root_names=["thing.dat"])
        text = readme.build(facts, "Odd Folder", "")
        self.assertIn("yours to write", text)
        self.assertNotIn("npm install", text)


class WriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_it_writes_the_file(self):
        result = readme.write(self.root, fake_survey(), "Crop Prices", "About prices.")
        self.assertTrue(result["written"])
        written = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("# Crop Prices", written)

    def test_an_existing_readme_is_never_touched(self):
        (self.root / "README.md").write_text("# Mine. Hand-written.\n", encoding="utf-8")
        result = readme.write(self.root, fake_survey(), "Crop Prices", "")
        self.assertFalse(result["written"])
        self.assertIn("already a README", result["why"])
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), "# Mine. Hand-written.\n")

    def test_force_replaces_it_when_asked(self):
        (self.root / "README.md").write_text("# Mine.\n", encoding="utf-8")
        result = readme.write(self.root, fake_survey(), "Crop Prices", "", force=True)
        self.assertTrue(result["written"])
        self.assertIn("# Crop Prices", (self.root / "README.md").read_text(encoding="utf-8"))

    def test_the_file_uses_unix_line_endings(self):
        readme.write(self.root, fake_survey(), "Crop Prices", "")
        raw = (self.root / "README.md").read_bytes()
        self.assertNotIn(b"\r\n", raw)


class BaseIgnoreTests(unittest.TestCase):
    def test_computer_and_editor_junk_is_covered(self):
        joined = "\n".join(readme.BASE_IGNORES)
        for pattern in (".DS_Store", "Thumbs.db", "desktop.ini", ".vscode/", "__pycache__/"):
            self.assertIn(pattern, joined)

    def test_the_ignore_block_is_comments_and_patterns_only(self):
        for line in readme.BASE_IGNORES:
            self.assertTrue(line.startswith("#") or line.strip())


if __name__ == "__main__":
    unittest.main()
