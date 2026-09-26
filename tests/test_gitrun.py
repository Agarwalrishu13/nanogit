"""The layer that talks to the real git program.

These tests run the real thing in a temporary folder with an identity set on
purpose, so they do not depend on whatever the machine running them happens to
have configured. If git is not installed, they are skipped rather than faked —
a stand-in for git would test nothing worth testing.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nanogit import gitrun

GIT = gitrun.find_git()


class ResultTests(unittest.TestCase):
    """The small judgements made about what git printed."""

    def test_a_clean_run_is_ok(self):
        self.assertTrue(gitrun.Result(("x",), 0, "done", "").ok)

    def test_a_timeout_is_never_ok(self):
        self.assertFalse(gitrun.Result(("x",), 0, "done", "", timed_out=True).ok)

    def test_nothing_to_commit_is_recognised(self):
        result = gitrun.Result(("commit",), 1, "nothing to commit, working tree clean", "")
        self.assertTrue(result.says_nothing_to_do())

    def test_a_real_failure_is_not_mistaken_for_nothing_to_do(self):
        result = gitrun.Result(("commit",), 128, "", "fatal: not a git repository")
        self.assertFalse(result.says_nothing_to_do())

    def test_a_missing_identity_is_recognised(self):
        result = gitrun.Result(
            ("commit",), 128, "",
            "*** Please tell me who you are.\n\nRun\n\n  git config --global user.email \"you@example.com\"\n",
        )
        self.assertTrue(result.needs_identity())

    def test_a_missing_identity_form_is_recognised_in_a_fresh_install(self):
        result = gitrun.Result(("commit",), 128, "", "fatal: unable to auto-detect email address")
        self.assertTrue(result.needs_identity())

    def test_hints_are_stripped_from_what_a_person_is_shown(self):
        result = gitrun.Result(
            ("commit",), 1, "",
            "hint: Waiting for your editor\nwarning: LF will be replaced by CRLF\nfatal: something real\n",
        )
        message = result.clean_error()
        self.assertEqual(message, "fatal: something real")

    def test_a_silent_failure_still_says_something(self):
        self.assertEqual(gitrun.Result(("x",), 1, "", "").clean_error(), "git did not say why.")

    def test_lines_skips_blanks(self):
        self.assertEqual(gitrun.Result(("x",), 0, "a\n\nb\n\n", "").lines(), ["a", "b"])


class MissingGitTests(unittest.TestCase):
    def test_a_computer_with_no_git_says_so_rather_than_crashing(self):
        with mock.patch.object(gitrun, "find_git", return_value=None):
            with self.assertRaises(gitrun.GitMissing) as caught:
                gitrun.Git()
        self.assertIn("was not found", str(caught.exception))

    def test_a_git_path_that_leads_nowhere_reports_instead_of_raising(self):
        broken = gitrun.Git("definitely-not-a-real-program-xyz")
        result = broken.run("--version")
        self.assertFalse(result.ok)
        self.assertNotEqual(result.code, 0)

    def test_the_advice_names_where_to_get_git(self):
        found = gitrun.find_git()
        if found:  # only meaningful on a machine that has it
            self.assertTrue(Path(found).exists())


@unittest.skipUnless(GIT, "git is not installed on this machine")
class GitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir()
        self.git = gitrun.Git(GIT)
        # Hermetic on purpose: no reliance on the machine's global git config.
        # A local identity can only be written once the folder IS a repository,
        # so the history starts here and every checkpoint below is signed by
        # "Test Person" no matter whose computer this is.
        self.git.init(self.root)
        self.git.set_identity(self.root, "Test Person", "test@localhost")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    # -- basics ------------------------------------------------------------
    def test_the_version_is_a_number(self):
        self.assertRegex(self.git.version(), r"^\d+\.\d+")

    def test_a_plain_folder_is_not_a_repo(self):
        # A folder of its own, outside the repository setUp created.
        plain = Path(tempfile.mkdtemp())
        try:
            self.assertFalse(self.git.is_repo(plain))
            self.assertFalse(self.git.is_own_repo(plain))
        finally:
            shutil.rmtree(plain, ignore_errors=True)

    def test_init_makes_it_one(self):
        result = self.git.init(self.root)
        self.assertTrue(result.ok, result.err)
        self.assertTrue(self.git.is_repo(self.root))
        self.assertTrue(self.git.is_own_repo(self.root))

    def test_init_uses_main_as_the_first_branch(self):
        self.git.init(self.root)
        branch = self.git.run("symbolic-ref", "--short", "HEAD", cwd=self.root).out.strip()
        self.assertEqual(branch, "main")

    def test_running_in_a_folder_that_does_not_exist_is_reported(self):
        result = self.git.run("status", cwd=self.root / "nowhere")
        self.assertFalse(result.ok)

    def test_a_bad_command_does_not_raise(self):
        result = self.git.run("this-is-not-a-git-command", cwd=self.root)
        self.assertFalse(result.ok)

    # -- saving ------------------------------------------------------------
    def test_a_first_commit_is_listed_in_the_log(self):
        self.git.init(self.root)
        self.write("notes.txt", "hello")
        self.assertTrue(self.git.commit_all(self.root, "First checkpoint").ok)
        entries = self.git.log(self.root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["message"], "First checkpoint")
        self.assertEqual(entries[0]["author"], "Test Person")
        self.assertEqual(self.git.count_checkpoints(self.root), 1)

    def test_committing_twice_with_no_change_says_so(self):
        self.git.init(self.root)
        self.write("notes.txt", "hello")
        self.git.commit_all(self.root, "One")
        again = self.git.commit_all(self.root, "Two")
        self.assertTrue(again.says_nothing_to_do())

    def test_the_log_is_newest_first(self):
        self.git.init(self.root)
        self.write("a.txt", "1")
        self.git.commit_all(self.root, "One")
        self.write("b.txt", "2")
        self.git.commit_all(self.root, "Two")
        messages = [entry["message"] for entry in self.git.log(self.root)]
        self.assertEqual(messages, ["Two", "One"])

    def test_the_log_is_empty_before_anything_is_saved(self):
        self.git.init(self.root)
        self.assertEqual(self.git.log(self.root), [])

    def test_the_author_and_time_come_back_in_a_usable_shape(self):
        self.git.init(self.root)
        self.write("a.txt", "1")
        self.git.commit_all(self.root, "One")
        entry = self.git.log(self.root)[0]
        self.assertEqual(len(entry["sha"]), 40)
        self.assertTrue(entry["when"].startswith("20"))
        self.assertNotIn("T", entry["when"][:10])

    # -- reading -----------------------------------------------------------
    def test_a_new_file_reads_as_new(self):
        self.git.init(self.root)
        self.write("a.txt", "1")
        self.git.commit_all(self.root, "One")
        self.write("b.txt", "2")
        changes = self.git.status(self.root)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["kind"], "new")
        self.assertEqual(changes[0]["path"], "b.txt")

    def test_a_modified_file_reads_as_changed(self):
        self.git.init(self.root)
        self.write("a.txt", "1")
        self.git.commit_all(self.root, "One")
        self.write("a.txt", "2")
        changes = self.git.status(self.root)
        self.assertEqual(changes[0]["kind"], "changed")

    def test_a_deleted_file_reads_as_gone(self):
        self.git.init(self.root)
        self.write("a.txt", "1")
        self.git.commit_all(self.root, "One")
        (self.root / "a.txt").unlink()
        changes = self.git.status(self.root)
        self.assertEqual(changes[0]["kind"], "gone")

    def test_a_clean_folder_reports_nothing(self):
        self.git.init(self.root)
        self.write("a.txt", "1")
        self.git.commit_all(self.root, "One")
        self.assertEqual(self.git.status(self.root), [])
        self.assertEqual(self.git.changed_files(self.root), [])

    def test_a_folder_inside_a_tracked_one_knows_it(self):
        self.git.init(self.root)
        self.write("a.txt", "1")
        self.git.commit_all(self.root, "One")
        inner = self.root / "inner"
        inner.mkdir()
        self.assertTrue(self.git.is_repo(inner))
        self.assertFalse(self.git.is_own_repo(inner))
        self.assertEqual(Path(self.git.top_level(inner)), self.root.resolve())

    # -- identity ----------------------------------------------------------
    def test_the_identity_can_be_set_and_read_back(self):
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        self.git.init(other)
        self.git.set_identity(other, "Priyanshu Agarwal", "priyanshu@localhost")
        name, email = self.git.identity(other)
        self.assertEqual(name, "Priyanshu Agarwal")
        self.assertEqual(email, "priyanshu@localhost")

    # -- leaving things out ------------------------------------------------
    def test_ignore_patterns_are_appended(self):
        self.assertTrue(self.git.ignore_file(self.root, [".env*", "*.key"]))
        text = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env*", text)

    def test_adding_a_pattern_twice_changes_nothing(self):
        self.git.ignore_file(self.root, [".env*"])
        self.assertFalse(self.git.ignore_file(self.root, [".env*"]))
        text = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertEqual(text.count(".env*"), 1)

    def test_an_existing_gitignore_is_kept(self):
        (self.root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        self.git.ignore_file(self.root, [".env*"])
        text = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("node_modules/", text)
        self.assertIn(".env*", text)

    def test_an_ignored_file_stays_out_of_the_checkpoint(self):
        self.git.init(self.root)
        (self.root / ".gitignore").write_text(".env\n", encoding="utf-8")
        self.write(".env", "SECRET=1")
        self.write("app.py", "print(1)")
        self.git.commit_all(self.root, "One")
        tracked = self.git.run("ls-files", cwd=self.root).lines()
        self.assertIn("app.py", tracked)
        self.assertNotIn(".env", tracked)

    # -- restoring ---------------------------------------------------------
    def test_restoring_puts_the_old_words_back(self):
        self.git.init(self.root)
        self.write("a.txt", "first")
        self.git.commit_all(self.root, "One")
        first = self.git.log(self.root)[0]["sha"]
        self.write("a.txt", "second")
        self.git.commit_all(self.root, "Two")
        self.assertTrue(self.git.restore_files(self.root, first).ok)
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "first")
        # The newer wording is still in the history, not thrown away.
        self.assertEqual([entry["message"] for entry in self.git.log(self.root)], ["Two", "One"])

    def test_restoring_refuses_anything_that_is_not_a_version(self):
        self.git.init(self.root)
        self.assertFalse(self.git.restore_files(self.root, "rm -rf /").ok)
        self.assertFalse(self.git.restore_files(self.root, "; drop tables").ok)
        self.assertFalse(self.git.restore_files(self.root, "").ok)

    def test_restoring_leaves_files_added_later_alone(self):
        self.git.init(self.root)
        self.write("old.txt", "old")
        self.git.commit_all(self.root, "One")
        first = self.git.log(self.root)[0]["sha"]
        self.write("new.txt", "new")
        self.git.commit_all(self.root, "Two")
        self.git.restore_files(self.root, first)
        self.assertTrue((self.root / "new.txt").exists())
        self.assertEqual(self.git.added_since(self.root, first), ["new.txt"])

    # -- remotes -----------------------------------------------------------
    def test_a_folder_with_no_remote_says_nothing_about_one(self):
        self.git.init(self.root)
        self.write("a.txt", "1")
        self.git.commit_all(self.root, "One")
        self.assertEqual(self.git.remote(self.root), "")
        self.assertEqual(self.git.unpushed(self.root), 0)

    def test_a_remote_can_be_added_and_read_back(self):
        self.git.init(self.root)
        self.assertTrue(self.git.track_remote(self.root, "https://github.com/example/thing.git").ok)
        self.assertEqual(self.git.remote(self.root), "https://github.com/example/thing.git")

    def test_adding_a_remote_twice_replaces_it_rather_than_failing(self):
        self.git.init(self.root)
        self.git.track_remote(self.root, "https://github.com/example/one.git")
        self.assertTrue(self.git.track_remote(self.root, "https://github.com/example/two.git").ok)
        self.assertEqual(self.git.remote(self.root), "https://github.com/example/two.git")

    def test_the_first_commit_can_be_found(self):
        self.git.init(self.root)
        self.write("a.txt", "1")
        self.git.commit_all(self.root, "One")
        self.write("b.txt", "2")
        self.git.commit_all(self.root, "Two")
        self.assertEqual(self.git.first_commit(self.root), self.git.log(self.root)[-1]["sha"])


class ManualCommandTests(unittest.TestCase):
    def test_the_hand_written_steps_are_the_real_ones(self):
        text = gitrun.manual_commands(Path("/tmp/demo"), "demo", private=True)
        self.assertIn("git remote add origin", text)
        self.assertIn("git push -u origin main", text)
        self.assertIn("private", text)

    def test_public_is_said_as_public(self):
        text = gitrun.manual_commands(Path("/tmp/demo"), "demo", private=False)
        self.assertIn("create a repository called demo", text)
        self.assertNotIn("*private*", text)


class GitHubToolTests(unittest.TestCase):
    def test_asking_who_is_signed_in_always_answers_even_with_no_tool(self):
        account = gitrun.gh_account()
        for key in ("installed", "logged_in", "account", "note"):
            self.assertIn(key, account)
        self.assertIsInstance(account["logged_in"], bool)

    def test_publishing_without_the_tool_is_reported_not_crashed(self):
        with mock.patch.object(gitrun, "gh", return_value=None):
            result = gitrun.gh_publish(Path("/tmp/nowhere"), "demo", True)
        self.assertFalse(result.ok)
        self.assertIn("not installed", result.err)


if __name__ == "__main__":
    unittest.main()
