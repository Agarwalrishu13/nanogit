"""The pages and the addresses the page talks to.

Every mutating address refuses requests that did not come from this app's own
page. That matters more here than in most local apps: this one can write files
and put a folder on the internet, so a stray web page in another tab must not
be able to drive it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from . import APP_NAME, __version__, native_picker, repo, store, survey
from .httpbase import App, Error, Json

PORT = 8778

# Origins the page is allowed to be served from.
_OWN_ORIGINS = ("127.0.0.1", "localhost", "::1", "[::1]")


def _same_origin(request) -> bool:
    """Reject a request that a different website made on the user's behalf.

    Checks two things, and both have to pass: the request says it is JSON (which
    a browser will not send to another site without asking first), and if it
    carries an Origin header that origin is this app.
    """
    origin = request.header("Origin")
    if origin:
        host = urlparse(origin).hostname or ""
        if host not in _OWN_ORIGINS:
            return False
    kind = (request.header("Content-Type") or "").split(";")[0].strip().lower()
    if kind and kind != "application/json":
        return False
    return True


def _guard(request):
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not _same_origin(request):
        return Error("That request did not come from this app's own page, so it was refused.", 403)
    return None


def _folder(request, key: str = "path") -> tuple[str, object]:
    """The folder from a request body, checked to exist."""
    payload = request.json({}) or {}
    value = (payload.get(key) or request.q(key) or "").strip().strip('"')
    if not value:
        return "", Error("No folder was given.")
    target = Path(value)
    if not target.exists():
        return "", Error("There is nothing at %s" % value)
    if not target.is_dir():
        return "", Error("%s is a file, not a folder." % value)
    return str(target), None


def create_app() -> App:
    app = App(APP_NAME, Path(__file__).parent / "web", __version__)

    # -- what the page asks when it loads ---------------------------------
    @app.get("/api/health")
    def health(request):
        git = repo.open_git()
        return Json(
            {
                "ok": True,
                "app": APP_NAME,
                "version": __version__,
                "python": sys.version.split()[0],
                "git": {
                    "found": git is not None,
                    "path": git.exe if git else "",
                    "version": git.version() if git else "",
                    "sentence": "" if git else repo.git_missing_sentence(),
                },
                "gh": repo.gitrun.gh_account(),
                "picker": native_picker.available(),
                "settings": _public_settings(),
            }
        )

    @app.get("/api/recent")
    def recent(request):
        return Json({"ok": True, "folders": store.recent_folders()})

    @app.post("/api/recent/forget")
    def forget(request):
        guard = _guard(request)
        if guard:
            return guard
        payload = request.json({}) or {}
        if payload.get("path"):
            store.forget_folder(payload["path"])
        return Json({"ok": True, "folders": store.recent_folders()})

    @app.get("/api/settings")
    def get_settings(request):
        return Json({"ok": True, "settings": _public_settings()})

    @app.post("/api/settings")
    def set_settings(request):
        guard = _guard(request)
        if guard:
            return guard
        payload = request.json({}) or {}
        allowed = {k: v for k, v in payload.items() if k in store.DEFAULT_SETTINGS}
        store.save_settings(allowed)
        return Json({"ok": True, "settings": _public_settings()})

    # -- finding a folder --------------------------------------------------
    @app.get("/api/browse")
    def browse(request):
        return Json(survey.browse(request.q("path", "")))

    @app.post("/api/locate")
    def locate(request):
        guard = _guard(request)
        if guard:
            return guard
        payload = request.json({}) or {}
        name = (payload.get("name") or "").strip()
        matches = survey.locate_by_name(name)
        return Json({"ok": True, "name": name, "matches": matches, "searching_in": [str(p) for p in survey.search_roots()]} )

    @app.post("/api/pick-folder")
    def pick_folder(request):
        guard = _guard(request)
        if guard:
            return guard
        payload = request.json({}) or {}
        return Json(native_picker.choose(initial=payload.get("from") or "", title=payload.get("title") or
                                         "Choose the folder to look after"))

    @app.post("/api/reveal")
    def reveal(request):
        guard = _guard(request)
        if guard:
            return guard
        folder, problem = _folder(request)
        if problem:
            return problem
        opened = _open_in_file_manager(folder)
        return Json({"ok": opened, "error": "" if opened else "Could not open that folder."})

    # -- looking at it -----------------------------------------------------
    @app.post("/api/survey")
    def look(request):
        guard = _guard(request)
        if guard:
            return guard
        folder, problem = _folder(request)
        if problem:
            return problem
        facts = survey.survey(folder)
        git = repo.open_git()
        facts["status"] = repo.status(git, folder) if git else {"ok": True, "tracked": False}
        return Json(facts)

    @app.get("/api/preview")
    def preview(request):
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "files": [], "why": "git was not found on this computer."})
        return Json(repo.preview_changes(git, request.q("path", "")))

    @app.get("/api/status")
    def status(request):
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()})
        folder, problem = _folder(request)
        if problem:
            return problem
        return Json(repo.status(git, folder))

    @app.get("/api/history")
    def history(request):
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence(), "entries": []})
        folder, problem = _folder(request)
        if problem:
            return problem
        return Json(repo.history(git, folder, with_what=request.q("full") == "1"))

    @app.get("/api/checkpoint-files")
    def checkpoint_files(request):
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence(), "files": []})
        folder, problem = _folder(request)
        if problem:
            return problem
        return Json(repo.checkpoint_files(git, folder, request.q("sha", "")))

    # -- changing it -------------------------------------------------------
    @app.post("/api/start")
    def start(request):
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        payload = request.json({}) or {}
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        result = repo.start(
            git,
            folder,
            name=payload.get("name", ""),
            description=payload.get("description", ""),
            author_name=payload.get("author_name", ""),
            author_email=payload.get("author_email", ""),
            extra_ignores=payload.get("extra_ignores") or [],
            remember_author=bool(payload.get("remember_author")),
        )
        return Json(result, status=200 if result.get("ok") else 400)

    @app.post("/api/checkpoint")
    def checkpoint(request):
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        payload = request.json({}) or {}
        result = repo.checkpoint(git, folder, payload.get("message", ""))
        return Json(result, status=200 if result.get("ok") else 400)

    @app.post("/api/go-back")
    def go_back(request):
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        payload = request.json({}) or {}
        result = repo.go_back(git, folder, payload.get("sha", ""))
        return Json(result, status=200 if result.get("ok") else 400)

    @app.post("/api/take-back")
    def take_back(request):
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        result = repo.take_back(git, folder)
        return Json(result, status=200 if result.get("ok") else 400)

    @app.post("/api/bring-back")
    def bring_back(request):
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        payload = request.json({}) or {}
        result = repo.bring_back(git, folder, payload.get("sha", ""), payload.get("file", ""))
        return Json(result, status=200 if result.get("ok") else 400)

    @app.post("/api/tidy-up")
    def tidy_up(request):
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        result = repo.tidy_up(git, folder)
        return Json(result, status=200 if result.get("ok") else 400)

    @app.post("/api/copy-history")
    def copy_history(request):
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        payload = request.json({}) or {}
        result = repo.copy_history(git, folder, payload.get("destination", ""))
        return Json(result, status=200 if result.get("ok") else 400)

    @app.post("/api/online-check")
    def online_check(request):
        # Reads only, but it asks fetch to update what origin is known to have,
        # so it gets the same stranger protection as the other POSTs.
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        return Json(repo.online_check(git, folder))

    @app.post("/api/get-latest")
    def get_latest(request):
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        result = repo.get_latest(git, folder)
        return Json(result, status=200 if result.get("ok") else 400)

    @app.post("/api/leave-out")
    def leave_out(request):
        """Add paths to .gitignore — the safe half of the publish question."""
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        payload = request.json({}) or {}
        patterns = [p for p in (payload.get("patterns") or []) if isinstance(p, str) and p.strip()]
        if not patterns:
            return Json({"ok": False, "error": "Nothing was given to leave out."}, status=400)
        changed = git.ignore_file(folder, ["", "# Left out because they look private."] + patterns)
        return Json(
            {
                "ok": True,
                "changed": changed,
                "patterns": patterns,
                "sentence": ("Added %d line%s to .gitignore." % (len(patterns), "" if len(patterns) == 1 else "s"))
                if changed
                else "Those were already listed in .gitignore.",
            }
        )

    # -- putting it online -------------------------------------------------
    @app.get("/api/readiness")
    def readiness(request):
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()})
        folder, problem = _folder(request)
        if problem:
            return problem
        return Json(repo.readiness(git, folder))

    @app.post("/api/publish")
    def publish(request):
        guard = _guard(request)
        if guard:
            return guard
        git = repo.open_git()
        if not git:
            return Json({"ok": False, "error": repo.git_missing_sentence()}, status=400)
        folder, problem = _folder(request)
        if problem:
            return problem
        payload = request.json({}) or {}
        result = repo.publish(
            git,
            folder,
            name=payload.get("name", ""),
            private=bool(payload.get("private", True)),
            description=payload.get("description", ""),
            allow_secrets=bool(payload.get("allow_secrets")),
        )
        return Json(result, status=200 if result.get("ok") else 400)

    return app


def _public_settings() -> dict:
    settings = store.load_settings()
    return {
        "author_name": settings.get("author_name", ""),
        "author_email": settings.get("author_email", ""),
        "remember_author": settings.get("remember_author", False),
        "last_folder": settings.get("last_folder", ""),
        "publish_private": settings.get("publish_private", True),
        "auto_checkpoint_minutes": settings.get("auto_checkpoint_minutes", 0),
        "data_dir": str(store.data_dir()),
    }


def _open_in_file_manager(path: str) -> bool:
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(Path(path))])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(Path(path))])
        else:
            subprocess.Popen(["xdg-open", str(Path(path))])
        return True
    except Exception:
        return False


def main() -> None:
    app = create_app()
    app.serve(port=PORT)
