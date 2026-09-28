"""The web layer, driven over a real socket.

The app is started on a port and then talked to exactly as a browser would talk
to it — including the requests a hostile web page in another tab might try, which
matter more here than usual: this app writes files and can put a folder on the
internet.
"""

import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from nanogit import gitrun, httpbase, server

GIT_FOUND = bool(gitrun.find_git())
NO_GITHUB = {"installed": False, "logged_in": False, "account": "", "note": "not installed"}


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)

        cls._env = mock.patch.dict(os.environ, {"NANOGIT_HOME": str(cls.base / "home")})
        cls._env.start()
        cls._gh = mock.patch.object(gitrun, "gh_account", return_value=dict(NO_GITHUB))
        cls._gh.start()

        cls.app = server.create_app()
        cls.thread = threading.Thread(
            target=cls.app.serve,
            kwargs={"host": "127.0.0.1", "port": 18900, "open_browser": False, "quiet": True},
            daemon=True,
        )
        cls.thread.start()
        for _ in range(200):
            if cls.app.url:
                break
            time.sleep(0.05)
        cls.base_url = cls.app.url
        if not cls.base_url:
            raise RuntimeError("the app never started listening")

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.thread.join(timeout=5)
        cls._gh.stop()
        cls._env.stop()
        cls._tmp.cleanup()

    def setUp(self):
        self.folder = self.base / ("case-%s" % self.id().split(".")[-1])
        self.folder.mkdir(exist_ok=True)
        (self.folder / "notes.txt").write_text("hello\n", encoding="utf-8")

    # -- talking to it -----------------------------------------------------
    def call(self, method, path, body=None, headers=None):
        data = None
        final = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            final.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(self.base_url + path, data=data, headers=final, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def get_json(self, path):
        status, text = self.call("GET", path)
        return status, json.loads(text)

    def post_json(self, path, body, headers=None):
        status, text = self.call("POST", path, body, headers)
        return status, json.loads(text)

    # -- the page ----------------------------------------------------------
    def test_the_page_is_served(self):
        status, text = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("nanoGit", text)
        self.assertIn("Drag a folder here", text)

    def test_the_stylesheet_and_the_script_are_served(self):
        for path, marker in (("/style.css", "--accent"), ("/app.js", "nanoGit")):
            status, text = self.call("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn(marker, text)

    def test_the_page_is_served_for_a_pretty_address(self):
        status, text = self.call("GET", "/settings")
        self.assertEqual(status, 200)
        self.assertIn("<!DOCTYPE html>", text)

    def test_a_file_that_is_not_there_is_a_404(self):
        status, _ = self.call("GET", "/nothing-here.png")
        self.assertEqual(status, 404)

    def test_an_unknown_api_address_says_so_in_words(self):
        status, payload = self.get_json("/api/nonsense")
        self.assertEqual(status, 404)
        self.assertIn("no such address", payload["error"])

    # -- what the page asks on load ---------------------------------------
    def test_health_says_what_this_computer_has(self):
        status, payload = self.get_json("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("found", payload["git"])
        self.assertIn("installed", payload["gh"])
        self.assertIn("settings", payload)

    def test_health_explains_a_missing_git(self):
        with mock.patch.object(gitrun, "find_git", return_value=None):
            _, payload = self.get_json("/api/health")
        self.assertFalse(payload["git"]["found"])
        self.assertIn("git-scm.com", payload["git"]["sentence"])

    def test_recent_folders_starts_empty_and_can_be_filled(self):
        status, payload = self.get_json("/api/recent")
        self.assertEqual(status, 200)
        self.assertIsInstance(payload["folders"], list)

    def test_settings_can_be_saved_and_read_back(self):
        status, payload = self.post_json("/api/settings", {"author_name": "Priyanshu"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["settings"]["author_name"], "Priyanshu")

    # -- looking at a folder ----------------------------------------------
    def test_a_folder_can_be_looked_at(self):
        status, payload = self.post_json("/api/survey", {"path": str(self.folder)})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["file_count"], 1)
        self.assertIn("status", payload)

    def test_a_folder_that_is_not_there_is_a_readable_error(self):
        status, payload = self.post_json("/api/survey", {"path": str(self.base / "nowhere")})
        self.assertEqual(status, 400)
        self.assertIn("nothing at", payload["error"])

    def test_a_file_instead_of_a_folder_is_refused_plainly(self):
        status, payload = self.post_json("/api/survey", {"path": str(self.folder / "notes.txt")})
        self.assertEqual(status, 400)
        self.assertIn("is a file", payload["error"])

    def test_no_folder_at_all_is_refused(self):
        status, payload = self.post_json("/api/survey", {})
        self.assertEqual(status, 400)
        self.assertIn("No folder", payload["error"])

    def test_the_folder_picker_can_list_places(self):
        status, payload = self.get_json("/api/browse")
        self.assertEqual(status, 200)
        self.assertTrue(payload["places"])

    def test_the_folder_picker_lists_subfolders(self):
        (self.folder / "inner").mkdir(exist_ok=True)
        status, payload = self.get_json("/api/browse?path=" + urllib.request.quote(str(self.folder)))
        self.assertEqual(status, 200)
        self.assertIn("inner", [item["name"] for item in payload["folders"]])

    def test_looking_for_a_dragged_folder_by_name(self):
        (self.base / "dragged-project").mkdir(exist_ok=True)
        status, payload = self.post_json("/api/locate", {"name": "dragged-project"})
        self.assertEqual(status, 200)
        self.assertIn("matches", payload)
        self.assertIn("searching_in", payload)

    def test_asking_for_a_folder_by_a_name_nobody_has_gives_nothing(self):
        status, payload = self.post_json("/api/locate", {"name": "no-such-folder-anywhere-xyz"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["matches"], [])

    # -- the requests a hostile page would try -----------------------------
    def test_a_post_from_another_website_is_refused(self):
        for origin in ("https://evil.example", "http://192.168.1.5"):
            status, payload = self.post_json(
                "/api/start", {"path": str(self.folder)}, headers={"Origin": origin}
            )
            self.assertEqual(status, 403, origin)
            self.assertIn("did not come from this app", payload["error"])

    def test_a_post_from_the_app_itself_is_allowed(self):
        status, payload = self.post_json(
            "/api/survey", {"path": str(self.folder)}, headers={"Origin": self.base_url}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_a_form_style_post_is_refused(self):
        # A browser can send this cross-site without asking permission first, so
        # it is exactly the shape of request that must not be trusted.
        status, payload = self.post_json(
            "/api/start", {"path": str(self.folder)}, headers={"Content-Type": "text/plain"}
        )
        self.assertEqual(status, 403)

    def test_a_get_that_changes_nothing_is_never_blocked(self):
        status, _ = self.call("GET", "/api/health", headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 200)

    def test_a_get_never_changes_anything(self):
        status, payload = self.get_json("/api/status?path=" + urllib.request.quote(str(self.folder)))
        self.assertEqual(status, 200)
        self.assertFalse(payload["tracked"])

    # -- the whole journey -------------------------------------------------
    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_start_then_checkpoint_then_history_over_http(self):
        status, payload = self.post_json(
            "/api/start", {"path": str(self.folder), "name": "Over HTTP", "description": "A test folder."}
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue((self.folder / "README.md").exists())
        self.assertTrue(payload["status"]["tracked"])
        self.assertEqual(payload["status"]["checkpoints"], 1)

        (self.folder / "second.txt").write_text("more\n", encoding="utf-8")
        status, payload = self.post_json("/api/checkpoint", {"path": str(self.folder), "message": "Second"})
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"]["checkpoints"], 2)

        status, payload = self.get_json("/api/history?path=" + urllib.request.quote(str(self.folder)))
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["entries"]), 2)
        self.assertEqual(payload["entries"][0]["message"], "Second")

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_going_back_over_http(self):
        self.post_json("/api/start", {"path": str(self.folder), "name": "Going Back"})
        first = self.get_json("/api/history?path=" + urllib.request.quote(str(self.folder)))[1]["entries"][0]["sha"]
        (self.folder / "notes.txt").write_text("changed\n", encoding="utf-8")
        self.post_json("/api/checkpoint", {"path": str(self.folder)})

        status, payload = self.post_json("/api/go-back", {"path": str(self.folder), "sha": first})
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual((self.folder / "notes.txt").read_text(encoding="utf-8"), "hello\n")

    def test_going_back_to_a_nonsense_version_is_refused(self):
        status, payload = self.post_json("/api/go-back", {"path": str(self.folder), "sha": "; rm -rf /"})
        self.assertEqual(status, 400)
        self.assertIn("not a version", payload["error"])

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_something_private_can_be_left_out_over_http(self):
        self.post_json("/api/start", {"path": str(self.folder)})
        status, payload = self.post_json(
            "/api/leave-out", {"path": str(self.folder), "patterns": ["passwords.txt", "*.key"]}
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["changed"])
        written = (self.folder / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("passwords.txt", written)
        self.assertIn("*.key", written)

    def test_leaving_out_nothing_at_all_is_refused(self):
        status, payload = self.post_json("/api/leave-out", {"path": str(self.folder), "patterns": []})
        self.assertEqual(status, 400)
        self.assertIn("Nothing was given", payload["error"])

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_readiness_says_what_is_missing(self):
        self.post_json("/api/start", {"path": str(self.folder)})
        status, payload = self.get_json("/api/readiness?path=" + urllib.request.quote(str(self.folder)))
        self.assertEqual(status, 200)
        self.assertIn("tracked", payload)
        self.assertIn("explain", payload)

    def test_a_publish_without_a_folder_is_refused(self):
        status, payload = self.post_json("/api/publish", {})
        self.assertEqual(status, 400)
        self.assertIn("No folder", payload["error"])

    def test_the_whole_page_survives_the_app_crashing_on_one_route(self):
        with mock.patch.object(server.repo, "readiness", side_effect=RuntimeError("boom")):
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                status, payload = self.get_json("/api/readiness?path=" + urllib.request.quote(str(self.folder)))
        self.assertEqual(status, 500)
        self.assertIn("went wrong inside the app", payload["error"])

    # -- the 1.0 buttons ----------------------------------------------------
    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def _start_two_checkpoints(self):
        self.post_json("/api/start", {"path": str(self.folder), "name": "HTTP"})
        (self.folder / "second.txt").write_text("more\n", encoding="utf-8")
        self.post_json("/api/checkpoint", {"path": str(self.folder), "message": "Second"})

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_looking_inside_a_checkpoint_over_http(self):
        self._start_two_checkpoints()
        history = self.get_json("/api/history?full=1&path=" + urllib.request.quote(str(self.folder)))[1]
        self.assertTrue(history["entries"][0]["what"]["text"])
        first = history["entries"][-1]
        status, payload = self.get_json(
            "/api/checkpoint-files?path=" + urllib.request.quote(str(self.folder)) + "&sha=" + first["sha"]
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        paths = [row["path"] for row in payload["files"]]
        self.assertIn("notes.txt", paths)
        self.assertNotIn("second.txt", paths)

    def test_looking_inside_a_made_up_checkpoint_is_refused(self):
        status, payload = self.get_json(
            "/api/checkpoint-files?path=" + urllib.request.quote(str(self.folder)) + "&sha=zzzz"
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["ok"])
        self.assertIn("not a version", payload["error"])

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_bringing_back_a_file_over_http(self):
        self._start_two_checkpoints()
        history = self.get_json("/api/history?path=" + urllib.request.quote(str(self.folder)))[1]
        (self.folder / "second.txt").unlink()
        first_with_file = history["entries"][0]["sha"]  # the checkpoint that still had it
        status, payload = self.post_json(
            "/api/bring-back", {"path": str(self.folder), "sha": first_with_file, "file": "second.txt"}
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual((self.folder / "second.txt").read_text(encoding="utf-8"), "more\n")

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_bringing_back_across_the_folder_fence_is_refused(self):
        self._start_two_checkpoints()
        history = self.get_json("/api/history?path=" + urllib.request.quote(str(self.folder)))[1]
        sha = history["entries"][0]["sha"]
        status, payload = self.post_json(
            "/api/bring-back", {"path": str(self.folder), "sha": sha, "file": "../escape.txt"}
        )
        self.assertEqual(status, 400)
        self.assertIn("not a file", payload["error"])

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_taking_back_over_http_keeps_the_work(self):
        self._start_two_checkpoints()
        status, payload = self.post_json("/api/take-back", {"path": str(self.folder)})
        self.assertEqual(status, 200, payload)
        self.assertTrue((self.folder / "second.txt").is_file())
        self.assertEqual(payload["status"]["checkpoints"], 1)

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_tidying_up_over_http(self):
        self._start_two_checkpoints()
        (self.folder / ".git" / "index.lock").write_text("")
        status, payload = self.get_json("/api/status?path=" + urllib.request.quote(str(self.folder)))
        self.assertTrue(payload["interrupted"])
        status, payload = self.post_json("/api/tidy-up", {"path": str(self.folder)})
        self.assertEqual(status, 200, payload)
        self.assertFalse((self.folder / ".git" / "index.lock").exists())

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_copying_the_history_over_http(self):
        self._start_two_checkpoints()
        stick = self.base / "stick"
        stick.mkdir(exist_ok=True)
        status, payload = self.post_json(
            "/api/copy-history", {"path": str(self.folder), "destination": str(stick)}
        )
        self.assertEqual(status, 200, payload)
        self.assertTrue(Path(payload["file"]).is_file())

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_online_check_over_http_for_an_offline_folder(self):
        self._start_two_checkpoints()
        status, payload = self.post_json("/api/online-check", {"path": str(self.folder)})
        self.assertEqual(status, 200)
        self.assertIn("not been put online", payload["explain"])

    @unittest.skipUnless(GIT_FOUND, "git is not installed on this machine")
    def test_get_latest_over_http_for_an_offline_folder_is_a_kind_no(self):
        self._start_two_checkpoints()
        status, payload = self.post_json("/api/get-latest", {"path": str(self.folder)})
        self.assertEqual(status, 400)
        self.assertIn("nothing to get", payload["error"])

    def test_the_new_buttons_are_guarded_like_the_old_ones(self):
        for route in ("/api/take-back", "/api/bring-back", "/api/tidy-up", "/api/copy-history", "/api/get-latest"):
            status, payload = self.post_json(
                route, {"path": str(self.folder)}, headers={"Origin": "https://evil.example"}
            )
            self.assertEqual(status, 403, route)
            self.assertIn("did not come from this app", payload["error"], route)
        # The read-only ones stay readable, because they change nothing.
        status, _ = self.call("GET", "/api/checkpoint-files?path=" + urllib.request.quote(str(self.folder)) + "&sha=z",
                              headers={"Origin": "https://evil.example"})
        self.assertNotEqual(status, 403)

    def test_the_auto_setting_round_trips(self):
        status, payload = self.get_json("/api/settings")
        self.assertIn("auto_checkpoint_minutes", payload["settings"])
        status, payload = self.post_json("/api/settings", {"auto_checkpoint_minutes": 1440})
        self.assertEqual(payload["settings"]["auto_checkpoint_minutes"], 1440)
        status, payload = self.post_json("/api/settings", {"auto_checkpoint_minutes": 0})
        self.assertEqual(payload["settings"]["auto_checkpoint_minutes"], 0)


class FreePortTests(unittest.TestCase):
    def test_a_busy_port_is_stepped_over(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(("127.0.0.1", 0))
            holder.listen(1)
            busy = holder.getsockname()[1]
            self.assertNotEqual(httpbase.free_port(busy, tries=5), busy)

    def test_a_free_port_is_used_as_is(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
        self.assertEqual(httpbase.free_port(free), free)


if __name__ == "__main__":
    unittest.main()
