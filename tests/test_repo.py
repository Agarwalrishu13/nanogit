"""The buttons, tested end to end against real folders and real git.

This is the file that matters most. Each test builds a folder, presses the thing
a person would press, and then looks at the folder on disk to see what actually
happened — including the promises that nothing is deleted and nothing private
is ever saved.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nanogit import gitrun, repo, store

GIT = gitrun.find_git()

NO_GITHUB = {"installed": False, "logged_in": False, "account": "", "note": "not installed"}


@unittest.skipUnless(GIT, "git is not installed on this machine")
class RepoTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = self.base / "project"
        self.root.mkdir()

        # Never read or write the real ~/.nanogit during a test run.
        self._env = mock.patch.dict(os.environ, {"NANOGIT_HOME": str(self.base / "home")})
        self._env.start()
        self.addCleanup(self._env.stop)

        # Never call out to GitHub. Signed-out is the honest default to test with.
        self._gh = mock.patch.object(gitrun, "gh_account", return_value=dict(NO_GITHUB))
        self._gh.start()
        self.addCleanup(self._gh.stop)

        self.git = gitrun.Git(GIT)
        self._identity = mock.patch.object(
            gitrun.Git, "identity", return_value=("Test Person", "test@localhost")
        )
        self._identity.start()
        self.addCleanup(self._identity.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str = "hello\n") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def start(self, **kwargs):
        return repo.start(self.git, str(self.root), **kwargs)

    def status(self):
        return repo.status(self.git, str(self.root))


class StartTests(RepoTestCase):
    def test_it_writes_a_readme(self):
        self.write("app.py", "print(1)\n")
        result = self.start(name="Crop Prices", description="A school project.")
        self.assertTrue(result["ok"], result)
        text = (self.root / "README.md").read_text(encoding="utf-8")
        self.assertIn("# Crop Prices", text)
        self.assertIn("A school project.", text)

    def test_it_writes_a_gitignore_covering_the_usual_junk(self):
        self.write("a.txt")
        self.start()
        text = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".DS_Store", text)
        self.assertIn("__pycache__/", text)

    def test_it_starts_the_history_and_saves_a_first_checkpoint(self):
        self.write("a.txt")
        self.start()
        state = self.status()
        self.assertTrue(state["tracked"])
        self.assertEqual(state["checkpoints"], 1)
        self.assertEqual(state["changes"], [])

    def test_a_private_looking_file_is_left_out_and_explained(self):
        self.write(".env", "AWS_KEY=AKIAIOSFODNN7EXAMPLE\n")
        self.write("app.py", "print(1)\n")
        result = self.start()
        self.assertTrue(result["ok"], result)

        ignored = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env*", ignored)
        saved = self.git.run("ls-files", cwd=self.root).lines()
        self.assertIn("app.py", saved)
        self.assertNotIn(".env", saved)

        said = " ".join(result["steps"])
        self.assertIn("look private", said)

    def test_an_existing_readme_is_never_overwritten(self):
        self.write("README.md", "# Hand written. Keep this.\n")
        result = self.start()
        self.assertEqual((self.root / "README.md").read_text(encoding="utf-8"), "# Hand written. Keep this.\n")
        self.assertIn("already a README", " ".join(result["steps"]))

    def test_pressing_it_twice_does_not_start_a_second_history(self):
        self.write("a.txt")
        self.start()
        first_count = self.status()["checkpoints"]
        second = self.start()
        self.assertTrue(second["ok"], second)
        state = self.status()
        self.assertEqual(state["checkpoints"], first_count)
        self.assertEqual(len(self.git.run("remote", "-v", cwd=self.root).lines()), 0)

    def test_an_empty_folder_is_not_an_error(self):
        result = self.start()
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.root / "README.md").exists())
        self.assertIn("empty", " ".join(result["steps"]))

    def test_it_says_what_it_did_in_plain_sentences(self):
        self.write("a.txt")
        result = self.start()
        self.assertGreaterEqual(len(result["steps"]), 3)
        for step in result["steps"]:
            self.assertFalse(step.startswith(" "), step)
            self.assertTrue(step.endswith("."), step)

    def test_a_folder_inside_another_tracked_folder_is_refused(self):
        outer = self.base / "outer"
        outer.mkdir()
        self.git.init(outer)
        inner = outer / "inner"
        inner.mkdir()
        (inner / "a.txt").write_text("x", encoding="utf-8")

        result = repo.start(self.git, str(inner))
        self.assertFalse(result["ok"])
        self.assertIn("inside", result["error"])
        self.assertFalse((inner / ".git").exists())

    def test_a_folder_that_is_not_there_is_refused(self):
        result = repo.start(self.git, str(self.base / "nowhere"))
        self.assertFalse(result["ok"])
        self.assertIn("no folder", result["error"])

    def test_the_folder_is_remembered_afterwards(self):
        self.write("a.txt")
        self.start(name="Crop Prices")
        self.assertEqual([item["note"] for item in store.recent_folders()], ["Crop Prices"])

    def test_settings_are_kept_when_the_person_asks(self):
        self.write("a.txt")
        self.start(author_name="Priyanshu", author_email="p@localhost", remember_author=True)
        self.assertEqual(store.load_settings()["author_name"], "Priyanshu")

    def test_settings_are_not_kept_when_they_did_not_ask(self):
        self.write("a.txt")
        self.start(author_name="Priyanshu", author_email="p@localhost", remember_author=False)
        self.assertEqual(store.load_settings()["author_name"], "")


class StatusTests(RepoTestCase):
    def test_a_plain_folder_is_reported_as_untracked(self):
        state = self.status()
        self.assertTrue(state["ok"])
        self.assertFalse(state["tracked"])
        self.assertEqual(state["change_summary"], "")

    def test_changes_are_counted_and_described(self):
        self.write("a.txt")
        self.start()
        self.write("a.txt", "changed")
        self.write("b.txt", "new")
        state = self.status()
        self.assertEqual(len(state["changes"]), 2)
        self.assertIn("2 files", state["change_summary"])
        self.assertIn("new", state["change_summary"])

    def test_everything_saved_is_said_in_words(self):
        self.write("a.txt")
        self.start()
        self.assertEqual(self.status()["change_summary"], "Everything is saved.")

    def test_a_missing_folder_is_reported(self):
        state = repo.status(self.git, str(self.base / "nowhere"))
        self.assertFalse(state["ok"])
        self.assertIn("no folder", state["error"])

    def test_it_knows_which_folder_it_is_inside(self):
        outer = self.base / "outer"
        outer.mkdir()
        self.git.init(outer)
        (outer / "a.txt").write_text("x", encoding="utf-8")
        self.git.commit_all(outer, "One")
        inner = outer / "inner"
        inner.mkdir()
        state = repo.status(self.git, str(inner))
        self.assertFalse(state["tracked"])
        self.assertTrue(state["inside_other_repo"])


class SummariseTests(unittest.TestCase):
    def test_nothing_changed(self):
        self.assertEqual(repo.summarise([]), "Everything is saved.")

    def test_one_file(self):
        self.assertIn("1 file", repo.summarise([{"kind": "changed"}]))

    def test_a_mixture(self):
        text = repo.summarise([{"kind": "new"}, {"kind": "new"}, {"kind": "changed"}])
        self.assertIn("3 files", text)
        self.assertIn("2 new", text)
        self.assertIn("1 changed", text)


class CheckpointTests(RepoTestCase):
    def test_a_change_can_be_saved(self):
        self.write("a.txt")
        self.start()
        self.write("a.txt", "changed")
        result = repo.checkpoint(self.git, str(self.root))
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.status()["checkpoints"], 2)
        self.assertEqual(self.status()["changes"], [])

    def test_the_person_word_for_it_is_used(self):
        self.write("a.txt")
        self.start()
        self.write("b.txt")
        repo.checkpoint(self.git, str(self.root), "Added the budget sheet")
        self.assertIn("Added the budget sheet", self.git.log(str(self.root))[0]["message"])

    def test_the_automatic_message_says_what_changed(self):
        self.write("a.txt")
        self.start()
        self.write("b.txt")
        repo.checkpoint(self.git, str(self.root))
        message = self.git.log(str(self.root))[0]["message"]
        self.assertTrue(message.startswith("Checkpoint"))
        self.assertIn("1 file", message)

    def test_saving_with_nothing_to_save_is_harmless(self):
        self.write("a.txt")
        self.start()
        result = repo.checkpoint(self.git, str(self.root))
        self.assertTrue(result["ok"])
        self.assertIn("nothing to save", " ".join(result["steps"]))
        self.assertEqual(self.status()["checkpoints"], 1)

    def test_a_newly_created_folder_with_no_history_gets_one(self):
        self.write("a.txt")
        result = repo.checkpoint(self.git, str(self.root))
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.status()["checkpoints"], 1)


class HistoryTests(RepoTestCase):
    def test_the_newest_checkpoint_is_first_and_the_first_is_marked(self):
        self.write("a.txt")
        self.start()
        self.write("b.txt")
        repo.checkpoint(self.git, str(self.root), "Second")
        entries = repo.history(self.git, str(self.root))["entries"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["message"], "Second")
        self.assertTrue(entries[-1]["was_first"])
        self.assertFalse(entries[0]["was_first"])

    def test_every_checkpoint_says_when_in_words(self):
        self.write("a.txt")
        self.start()
        entries = repo.history(self.git, str(self.root))["entries"]
        self.assertIn("today", entries[0]["when_text"])

    def test_an_untracked_folder_has_an_empty_history(self):
        self.write("a.txt")
        result = repo.history(self.git, str(self.root))
        self.assertEqual(result["entries"], [])
        self.assertIn("not tracked", result["note"])


class GoBackTests(RepoTestCase):
    def test_the_old_words_come_back(self):
        self.write("a.txt", "the first version")
        self.start()
        first = self.git.log(str(self.root))[0]["sha"]
        self.write("a.txt", "the second version")
        repo.checkpoint(self.git, str(self.root), "Second")

        result = repo.go_back(self.git, str(self.root), first)
        self.assertTrue(result["ok"], result)
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "the first version")

    def test_the_newer_version_is_still_in_the_history(self):
        self.write("a.txt", "first")
        self.start()
        first = self.git.log(str(self.root))[0]["sha"]
        self.write("a.txt", "second")
        repo.checkpoint(self.git, str(self.root), "Second")
        repo.go_back(self.git, str(self.root), first)
        messages = [entry["message"] for entry in self.git.log(str(self.root))]
        self.assertIn("Second", messages)
        self.assertIn("First checkpoint", messages)

    def test_unsaved_work_is_saved_first_and_nothing_is_lost(self):
        self.write("a.txt", "first")
        self.start()
        first = self.git.log(str(self.root))[0]["sha"]
        self.write("a.txt", "work in progress nobody saved")

        result = repo.go_back(self.git, str(self.root), first)
        self.assertTrue(result["ok"], result)

        messages = [entry["message"] for entry in self.git.log(str(self.root))]
        self.assertTrue(any("before going back" in message for message in messages), messages)
        # The words that were never saved are still in a checkpoint.
        saved = self.git.run("show", "HEAD:a.txt", cwd=self.root).out
        self.assertIn("work in progress", saved)
        # ...and the file itself is back to how it was at the chosen checkpoint.
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "first")

    def test_files_added_later_are_left_alone(self):
        self.write("old.txt", "old")
        self.start()
        first = self.git.log(str(self.root))[0]["sha"]
        self.write("new.txt", "new")
        repo.checkpoint(self.git, str(self.root), "Second")

        result = repo.go_back(self.git, str(self.root), first)
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.root / "new.txt").exists())
        self.assertIn("nothing was deleted", " ".join(result["steps"]))

    def test_a_version_that_is_not_a_version_is_refused(self):
        self.write("a.txt")
        self.start()
        for bad in ("", "rm -rf /", "; rm -rf /", "main", "HEAD~1", "zzzz"):
            result = repo.go_back(self.git, str(self.root), bad)
            self.assertFalse(result["ok"], bad)

    def test_a_version_from_somewhere_else_is_refused(self):
        self.write("a.txt")
        self.start()
        result = repo.go_back(self.git, str(self.root), "0123456789abcdef0123456789abcdef01234567")
        self.assertFalse(result["ok"])
        self.assertIn("not in this folder", result["error"])

    def test_nothing_was_actually_deleted_after_going_back(self):
        self.write("keep.txt", "important")
        self.start()
        first = self.git.log(str(self.root))[0]["sha"]
        self.write("another.txt", "also important")
        repo.checkpoint(self.git, str(self.root), "Second")
        repo.go_back(self.git, str(self.root), first)
        self.assertTrue((self.root / "keep.txt").exists())
        self.assertTrue((self.root / "another.txt").exists())


class ReadinessTests(RepoTestCase):
    def test_an_untracked_folder_is_told_to_save_first(self):
        self.write("a.txt")
        ready = repo.readiness(self.git, str(self.root))
        self.assertFalse(ready["tracked"])
        self.assertFalse(ready["can_publish"])
        self.assertIn("first time", ready["explain"])

    def test_a_tracked_folder_with_no_github_tool_is_told_where_to_get_it(self):
        self.write("a.txt")
        self.start()
        ready = repo.readiness(self.git, str(self.root))
        self.assertTrue(ready["tracked"])
        self.assertFalse(ready["can_publish"])
        self.assertIn("cli.github.com", ready["explain"])
        self.assertIn("by hand", ready["explain"])

    def test_it_lists_the_private_looking_files_before_anything_is_uploaded(self):
        self.write(".env", "SECRET=1")
        self.write("a.txt")
        self.start()
        ready = repo.readiness(self.git, str(self.root))
        self.assertEqual([item["path"] for item in ready["secrets"]], [".env"])

    def test_ready_when_github_is_signed_in(self):
        self.write("a.txt")
        self.start()
        with mock.patch.object(
            gitrun, "gh_account",
            return_value={"installed": True, "logged_in": True, "account": "someone", "note": "ready"},
        ):
            ready = repo.readiness(self.git, str(self.root))
        self.assertTrue(ready["can_publish"])
        self.assertIn("someone", ready["explain"])


class PublishTests(RepoTestCase):
    def test_a_private_looking_file_stops_the_upload(self):
        # Tracked by hand, so there is no .gitignore leaving .env out.
        self.git.init(self.root)
        self.write(".env", "AWS_KEY=AKIAIOSFODNN7EXAMPLE\n")
        self.write("a.txt")
        self.git.commit_all(self.root, "One")

        with mock.patch.object(gitrun, "gh_publish") as publish:
            result = repo.publish(self.git, str(self.root), name="demo", private=True)
        self.assertFalse(result["ok"])
        self.assertIn("look private", result["error"])
        self.assertIn("Leave them out", result["ask"])
        publish.assert_not_called()

    def test_uploading_anyway_is_possible_when_the_person_insists(self):
        self.git.init(self.root)
        self.write(".env", "AWS_KEY=AKIAIOSFODNN7EXAMPLE\n")
        self.write("a.txt")
        self.git.commit_all(self.root, "One")
        with mock.patch.object(gitrun, "gh_publish") as publish:
            publish.return_value = gitrun.Result(("gh",), 0, "https://github.com/someone/demo", "")
            result = repo.publish(self.git, str(self.root), name="demo", private=True, allow_secrets=True)
        self.assertTrue(result["ok"], result)
        publish.assert_called_once()

    def test_a_created_repository_comes_back_with_its_address(self):
        self.write("a.txt")
        self.start()
        with mock.patch.object(gitrun, "gh_account", return_value=dict(NO_GITHUB, installed=True, logged_in=True, account="someone")):
            with mock.patch.object(gitrun, "gh_publish") as publish:
                publish.return_value = gitrun.Result(
                    ("gh",), 0, "https://github.com/someone/demo\n", ""
                )
                result = repo.publish(self.git, str(self.root), name="Demo Project", private=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["url"], "https://github.com/someone/demo")
        self.assertIn("private", " ".join(result["steps"]).lower())

    def test_a_name_that_is_already_taken_is_explained(self):
        self.write("a.txt")
        self.start()
        with mock.patch.object(gitrun, "gh_publish") as publish:
            publish.return_value = gitrun.Result(
                ("gh",), 1, "", "GraphQL: Name already exists on this account (createRepository)"
            )
            result = repo.publish(self.git, str(self.root), name="demo", private=True)
        self.assertFalse(result["ok"])
        self.assertIn("already a repository", result["error"])

    def test_a_file_too_big_for_github_stops_it_before_the_upload(self):
        self.write("a.txt")
        self.start()
        with mock.patch("nanogit.survey.BIG_WARN_BYTES", 1), mock.patch("nanogit.survey.BIG_REFUSE_BYTES", 1):
            with mock.patch.object(gitrun, "gh_publish") as publish:
                result = repo.publish(self.git, str(self.root), name="demo", private=True)
        self.assertFalse(result["ok"])
        publish.assert_not_called()

    def test_a_folder_that_already_points_somewhere_sends_the_new_checkpoints(self):
        self.write("a.txt")
        self.start()
        self.git.track_remote(self.root, "https://github.com/someone/demo.git")
        with mock.patch.object(gitrun.Git, "run", autospec=True) as run:
            run.return_value = gitrun.Result(("push",), 0, "ok", "")
            result = repo.publish(self.git, str(self.root), name="demo", private=True)
        self.assertTrue(result["ok"], result)
        self.assertIn("new checkpoints", " ".join(result["steps"]))


class IdentityTests(RepoTestCase):
    def test_the_default_identity_is_not_empty(self):
        name, email = repo.default_identity()
        self.assertTrue(name)
        self.assertIn("@", email)

    def test_a_github_account_gives_the_private_no_reply_address(self):
        with mock.patch.object(
            gitrun, "gh_account",
            return_value={"installed": True, "logged_in": True, "account": "someone", "note": "ready"},
        ):
            name, email = repo.default_identity()
        self.assertEqual(email, "someone@users.noreply.github.com")

    def test_a_remembered_identity_is_used(self):
        store.save_settings({"author_name": "Remembered", "author_email": "r@localhost", "remember_author": True})
        self.assertEqual(repo.default_identity(), ("Remembered", "r@localhost"))

    def test_a_remembered_identity_is_ignored_when_they_said_not_to(self):
        store.save_settings({"author_name": "Remembered", "author_email": "r@localhost", "remember_author": False})
        name, _ = repo.default_identity()
        self.assertNotEqual(name, "Remembered")

    def test_a_checkpoint_ends_up_signed(self):
        self.write("a.txt")
        self.start()
        entry = self.git.log(str(self.root))[0]
        self.assertTrue(entry["author"])


class FriendlyWhenTests(unittest.TestCase):
    def test_today(self):
        import datetime as dt

        now = dt.datetime.now().astimezone().isoformat()
        self.assertIn("today", repo._friendly_when(now))

    def test_an_unreadable_stamp_is_shown_as_it_is(self):
        self.assertEqual(repo._friendly_when("whenever"), "whenever")

    def test_nothing_at_all(self):
        self.assertEqual(repo._friendly_when(""), "an unknown date")


class GitMissingSentenceTests(unittest.TestCase):
    def test_the_advice_says_where_to_get_git(self):
        text = repo.git_missing_sentence()
        self.assertIn("git-scm.com", text)
        self.assertIn("install", text.lower())


class CheckpointFilesTests(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.write("a.txt", "one\n")
        self.write("sub/b.txt", "two\n")
        self.start()
        self.first = self.git.log(self.root)[0]
        self.write("a.txt", "one\nchanged\n")
        self.write("c.txt", "three\n")
        repo.checkpoint(self.git, str(self.root), "second")
        self.second = self.git.log(self.root)[0]

    def test_looking_inside_a_checkpoint_lists_everything_it_holds(self):
        inside = repo.checkpoint_files(self.git, str(self.root), self.first["sha"])
        self.assertTrue(inside["ok"])
        paths = [row["path"] for row in inside["files"]]
        self.assertIn("a.txt", paths)
        self.assertIn("sub/b.txt", paths)
        self.assertNotIn("c.txt", paths)

    def test_a_file_what_changed_sentence_comes_along(self):
        inside = repo.checkpoint_files(self.git, str(self.root), self.second["sha"])
        self.assertEqual(inside["what"]["files"], 2)
        self.assertEqual(inside["what"]["counts"].get("new"), 1)
        self.assertEqual(inside["what"]["counts"].get("changed"), 1)
        self.assertIn("+", inside["what"]["text"])

    def test_gone_now_flags_what_the_folder_no_longer_has(self):
        (self.root / "sub" / "b.txt").unlink()
        repo.checkpoint(self.git, str(self.root), "removed b")
        inside = repo.checkpoint_files(self.git, str(self.root), self.first["sha"])
        by_path = {row["path"]: row for row in inside["files"]}
        self.assertTrue(by_path["sub/b.txt"]["gone_now"])
        self.assertFalse(by_path["a.txt"]["gone_now"])

    def test_a_made_up_checkpoint_is_refused_without_throwing(self):
        inside = repo.checkpoint_files(self.git, str(self.root), "; rm -rf /")
        self.assertFalse(inside["ok"])
        self.assertIn("not a version", inside["error"])

    def test_a_checkpoint_from_somewhere_else_is_refused(self):
        other = self.base / "elsewhere"
        other.mkdir()
        git2 = gitrun.Git(GIT)
        git2.init(other)
        git2.set_identity(other, "T", "t@localhost")
        (other / "x.txt").write_text("x\n")
        git2.commit_all(other, "x")
        foreign = git2.log(other)[0]
        inside = repo.checkpoint_files(self.git, str(self.root), foreign["sha"])
        self.assertFalse(inside["ok"])
        self.assertIn("not in this folder", inside["error"])

    def test_the_history_can_be_asked_for_what_changed(self):
        result = repo.history(self.git, str(self.root), with_what=True)
        self.assertTrue(result["entries"][0]["what"]["text"])
        plain = repo.history(self.git, str(self.root))
        self.assertEqual(plain["entries"][0]["what"], {})


class BringBackTests(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.write("photo.bin", "original-bytes\n")
        self.start()
        self.first = self.git.log(self.root)[0]

    def test_a_deleted_file_comes_back_byte_for_byte(self):
        blob = bytes(range(256))
        (self.root / "photo.bin").write_bytes(blob)
        repo.checkpoint(self.git, str(self.root), "binary version")
        saved = self.git.log(self.root)[0]
        (self.root / "photo.bin").unlink()
        result = repo.bring_back(self.git, str(self.root), saved["sha"], "photo.bin")
        self.assertTrue(result["ok"], result)
        self.assertEqual((self.root / "photo.bin").read_bytes(), blob)
        self.assertIn("Brought back", " ".join(result["steps"]))

    def test_unsaved_work_is_checkpointed_before_a_file_is_replaced(self):
        repo.checkpoint(self.git, str(self.root))  # everything saved
        self.write("photo.bin", "work in progress\n")
        result = repo.bring_back(self.git, str(self.root), self.first["sha"], "photo.bin")
        self.assertTrue(result["ok"], result)
        self.assertEqual((self.root / "photo.bin").read_text(encoding="utf-8"), "original-bytes\n")
        steps = " ".join(result["steps"])
        self.assertIn("Saved a checkpoint", steps)   # the current work, saved first
        self.assertIn("Brought back", steps)
        messages = {entry["message"] for entry in self.git.log(self.root)}
        self.assertTrue(any("automatically before bringing back photo.bin" in m for m in messages), messages)

    def test_a_file_that_already_matches_is_not_touched(self):
        result = repo.bring_back(self.git, str(self.root), self.first["sha"], "photo.bin")
        self.assertTrue(result["ok"])
        self.assertIn("already exactly", result["steps"][0])

    def test_a_path_traversal_is_refused(self):
        self.write("outside.txt", "should never be overwritten\n")
        (self.base / "outside-target").mkdir()
        for evil in ("../outside.txt", "..\\outside.txt", "/etc/passwd", "sub/../../outside.txt"):
            result = repo.bring_back(self.git, str(self.root), self.first["sha"], evil)
            self.assertFalse(result["ok"], evil)
        self.assertEqual((self.root / "outside.txt").read_text(encoding="utf-8"), "should never be overwritten\n")

    def test_a_file_the_checkpoint_does_not_have_is_named_in_the_answer(self):
        result = repo.bring_back(self.git, str(self.root), self.first["sha"], "never-existed.txt")
        self.assertFalse(result["ok"])
        self.assertIn("never-existed.txt", result["error"])

    def test_a_made_up_checkpoint_is_refused(self):
        result = repo.bring_back(self.git, str(self.root), "zzzz", "photo.bin")
        self.assertFalse(result["ok"])


class TakeBackTests(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.write("a.txt", "one\n")
        self.start()

    def test_taking_back_unsaves_the_checkpoint_but_never_the_work(self):
        self.write("b.txt", "two\n")
        repo.checkpoint(self.git, str(self.root), "added b")
        self.assertEqual(self.git.count_checkpoints(self.root), 2)
        result = repo.take_back(self.git, str(self.root))
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.git.count_checkpoints(self.root), 1)
        self.assertTrue((self.root / "b.txt").is_file())  # the promise: nothing is deleted
        paths = [change["path"] for change in result["status"]["changes"]]
        self.assertIn("b.txt", paths)
        self.assertIn("added b", result["steps"][0])

    def test_the_first_checkpoint_is_the_floor(self):
        result = repo.take_back(self.git, str(self.root))
        self.assertFalse(result["ok"])
        self.assertIn("first checkpoint", result["error"])
        self.assertEqual(self.git.count_checkpoints(self.root), 1)

    def test_an_interrupted_save_is_tidied_first(self):
        (self.root / ".git" / "index.lock").write_text("")
        result = repo.take_back(self.git, str(self.root))
        self.assertFalse(result["ok"])
        self.assertTrue(result["interrupted"])

    def test_an_untracked_folder_is_refused_plainly(self):
        plain = self.base / "plain"
        plain.mkdir()
        result = repo.take_back(self.git, str(plain))
        self.assertFalse(result["ok"])


class TidyUpTests(RepoTestCase):
    def test_nothing_to_tidy_is_a_fine_answer(self):
        self.write("a.txt")
        self.start()
        result = repo.tidy_up(self.git, str(self.root))
        self.assertTrue(result["ok"])
        self.assertIn("nothing to tidy", result["steps"][0])

    def test_the_interrupted_save_is_reported_and_cleared(self):
        self.write("a.txt")
        self.start()
        (self.root / ".git" / "index.lock").write_text("")
        self.assertTrue(repo.status(self.git, str(self.root))["interrupted"])
        result = repo.tidy_up(self.git, str(self.root))
        self.assertTrue(result["ok"])
        self.assertFalse((self.root / ".git" / "index.lock").exists())
        # Everything else is exactly as it was.
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "hello\n")
        self.assertFalse(repo.status(self.git, str(self.root))["interrupted"])


class CopyHistoryTests(RepoTestCase):
    def test_the_whole_history_lands_in_one_file_and_verifies(self):
        self.write("a.txt", "one\n")
        self.start()
        self.write("b.txt", "two\n")
        repo.checkpoint(self.git, str(self.root), "two")
        stick = self.base / "usb-stick"
        stick.mkdir()
        result = repo.copy_history(self.git, str(self.root), str(stick))
        self.assertTrue(result["ok"], result)
        bundle = Path(result["file"])
        self.assertTrue(bundle.is_file())
        self.assertIn(".bundle", bundle.name)
        self.assertIn("2 checkpoints", " ".join(result["steps"]))
        self.assertTrue(self.git.bundle_verify(self.root, bundle).ok)

    def test_a_copy_inside_the_folder_it_copies_is_refused(self):
        self.write("a.txt")
        self.start()
        result = repo.copy_history(self.git, str(self.root), str(self.root))
        self.assertFalse(result["ok"])
        self.assertIn("outside", result["error"])

    def test_no_history_means_nothing_to_copy(self):
        (self.root / "a.txt").write_text("x")
        result = repo.copy_history(self.git, str(self.root), str(self.base))
        self.assertFalse(result["ok"])
        self.assertIn("first", result["error"])

    def test_a_nowhere_destination_is_refused(self):
        self.write("a.txt")
        self.start()
        result = repo.copy_history(self.git, str(self.root), str(self.base / "nowhere"))
        self.assertFalse(result["ok"])
        self.assertIn("no folder", result["error"])

    def test_no_destination_at_all_is_refused(self):
        self.write("a.txt")
        self.start()
        result = repo.copy_history(self.git, str(self.root), "")
        self.assertFalse(result["ok"])


class OnlineCopyTests(RepoTestCase):
    """Get the latest version, against a bare folder standing in for GitHub."""

    def setUp(self):
        super().setUp()
        self.write("a.txt", "one\n")
        self.start()
        self.bare = self.base / "remote.git"
        self.assertTrue(self.git.run("init", "--bare", "-b", "main", str(self.bare), cwd=self.base).ok)
        self.git.track_remote(self.root, str(self.bare))
        self.assertTrue(self.git.run("push", "-u", "origin", "main", cwd=self.root).ok)

    def push_from_elsewhere(self, name="b.txt", text="from elsewhere\n"):
        other = self.base / "other"
        self.assertTrue(self.git.run("clone", str(self.bare), str(other), cwd=self.base).ok)
        self.git.set_identity(other, "Other", "other@localhost")
        (other / name).write_text(text)
        self.assertTrue(self.git.commit_all(other, "from the other computer").ok)
        self.assertTrue(self.git.run("push", "origin", "main", cwd=other).ok)

    def test_a_folder_without_online_home_is_answered_kindly(self):
        plain = self.base / "plain"
        plain.mkdir()
        repo.start(self.git, str(plain))
        check = repo.online_check(self.git, str(plain))
        self.assertIn("not been put online", check["explain"])
        result = repo.get_latest(self.git, str(plain))
        self.assertFalse(result["ok"])

    def test_matching_copies_are_reported(self):
        check = repo.online_check(self.git, str(self.root))
        self.assertTrue(check["reachable"])
        self.assertEqual(check["incoming"], 0)
        self.assertEqual(check["outgoing"], 0)
        self.assertIn("matches", check["explain"])

    def test_something_waiting_online_comes_down_on_request(self):
        self.push_from_elsewhere()
        check = repo.online_check(self.git, str(self.root))
        self.assertEqual(check["incoming"], 1)
        result = repo.get_latest(self.git, str(self.root))
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.root / "b.txt").is_file())
        self.assertIn("Brought down 1 checkpoint", " ".join(result["steps"]))

    def test_unsaved_work_stops_the_download_with_an_explanation(self):
        self.push_from_elsewhere()
        self.write("dirty.txt", "unsaved\n")
        result = repo.get_latest(self.git, str(self.root))
        self.assertFalse(result["ok"])
        self.assertIn("Save a checkpoint first", result["error"])
        self.assertFalse((self.root / "b.txt").exists())  # left exactly as it was

    def test_both_sides_moving_is_a_refusal_not_a_mess(self):
        self.push_from_elsewhere()
        self.write("c.txt", "local move\n")
        self.assertTrue(self.git.commit_all(self.root, "local move").ok)
        check = repo.online_check(self.git, str(self.root))
        self.assertTrue(check["incoming"] and check["outgoing"])
        self.assertIn("different", check["explain"])
        result = repo.get_latest(self.git, str(self.root))
        self.assertFalse(result["ok"])
        self.assertIn("left as it is", result["error"])

    def test_already_up_to_date_is_a_fine_answer(self):
        result = repo.get_latest(self.git, str(self.root))
        self.assertTrue(result["ok"])
        self.assertIn("up to date", result["steps"][0])


class AutoCheckTests(RepoTestCase):
    def make_old(self, days_ago_iso="2020-01-01T00:00:00+00:00"):
        """Rewrite the newest checkpoint's date, so the saver sees an overdue folder."""
        import subprocess
        import os as _os
        env = dict(_os.environ, GIT_COMMITTER_DATE=days_ago_iso)
        done = subprocess.run(
            ["git", "commit", "--amend", "--no-edit", "-q", "--allow-empty", "--date", days_ago_iso],
            cwd=str(self.root), env=env, capture_output=True, text=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_it_never_runs_unless_asked(self):
        self.write("a.txt")
        self.start()
        self.write("b.txt", "two\n")
        result = repo.auto_check_once(self.git)
        self.assertFalse(result["saved"])
        self.assertEqual(self.git.count_checkpoints(self.root), 1)

    def test_an_overdue_folder_with_changes_gets_saved(self):
        self.write("a.txt")
        self.start()
        self.make_old()
        store.save_settings({"auto_checkpoint_minutes": 1440, "last_folder": str(self.root)})
        self.write("b.txt", "two\n")
        result = repo.auto_check_once(self.git)
        self.assertTrue(result["saved"], result)
        self.assertEqual(self.git.count_checkpoints(self.root), 2)
        self.assertIn("Automatic checkpoint", self.git.log(self.root)[0]["message"])

    def test_a_recently_saved_folder_is_left_alone(self):
        self.write("a.txt")
        self.start()
        store.save_settings({"auto_checkpoint_minutes": 1440, "last_folder": str(self.root)})
        self.write("b.txt", "two\n")
        result = repo.auto_check_once(self.git)
        self.assertFalse(result["saved"])
        self.assertEqual(result["why"], "saved recently enough")

    def test_nothing_changed_means_nothing_saved(self):
        self.write("a.txt")
        self.start()
        self.make_old()
        store.save_settings({"auto_checkpoint_minutes": 1440, "last_folder": str(self.root)})
        result = repo.auto_check_once(self.git)
        self.assertFalse(result["saved"])
        self.assertEqual(result["why"], "nothing changed")

    def test_an_interrupted_save_means_it_stays_quiet(self):
        self.write("a.txt")
        self.start()
        self.make_old()
        store.save_settings({"auto_checkpoint_minutes": 1440, "last_folder": str(self.root)})
        (self.root / ".git" / "index.lock").write_text("")
        result = repo.auto_check_once(self.git)
        self.assertFalse(result["saved"])

    def test_a_folder_that_is_not_tracked_is_not_started_by_it(self):
        plain = self.base / "plain"
        plain.mkdir()
        (plain / "x.txt").write_text("x")
        store.save_settings({"auto_checkpoint_minutes": 1440, "last_folder": str(plain)})
        result = repo.auto_check_once(self.git)
        self.assertFalse(result["saved"])
        self.assertFalse((plain / ".git").exists())


class StatusExtrasTests(RepoTestCase):
    def test_the_fresh_fields_are_always_present(self):
        state = repo.status(self.git, str(self.root))
        for key in ("last_when_text", "days_since_last", "interrupted"):
            self.assertIn(key, state)

    def test_a_saved_folder_says_when_in_words(self):
        self.write("a.txt")
        self.start()
        state = repo.status(self.git, str(self.root))
        self.assertIn("today", state["last_when_text"])
        self.assertEqual(state["days_since_last"], 0)


class LeaveOutTests(RepoTestCase):
    def test_a_pattern_can_be_added_after_the_fact(self):
        self.write("a.txt")
        self.start()
        self.write("passwords.txt", "hunter2")
        self.assertTrue(self.git.ignore_file(self.root, ["passwords.txt"]))
        self.assertIn("passwords.txt", (self.root / ".gitignore").read_text(encoding="utf-8"))

    def test_the_ignored_check_is_not_fooled_by_a_similar_name(self):
        self.write("a.txt")
        self.start()
        self.git.ignore_file(self.root, [".env"])
        self.assertTrue(repo._ignored(self.root, ".env"))
        self.assertFalse(repo._ignored(self.root, "environment.py"))

    def test_a_folder_rule_covers_what_is_inside_it(self):
        self.write("a.txt")
        self.start()
        self.git.ignore_file(self.root, ["private/"])
        self.assertTrue(repo._ignored(self.root, "private/notes.txt"))


if __name__ == "__main__":
    unittest.main()
