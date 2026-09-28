"""Command line entry point.

Three ways in, in increasing order of nerdiness::

    python start.py              # start the app and open the browser
    python -m nanogit            # the same thing
    python -m nanogit doctor     # say what is installed, and stop
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from . import APP_NAME, TAGLINE, __version__, native_picker, repo, store, survey
from .server import PORT


def _doctor() -> int:
    print()
    print("  %s %s — what this computer has" % (APP_NAME, __version__))
    print("  " + "-" * 62)
    print("  Python %s" % sys.version.split()[0])
    print("  You are in: %s" % Path.cwd())
    print("  nanoGit remembers things in: %s" % store.data_dir())
    print()

    git = repo.open_git()
    if git:
        print("  git:  found at %s" % git.exe)
        print("        version %s" % git.version())
        inside = git.is_repo(Path.cwd())
        print("        this folder %s" % ("is already tracked" if inside else "is not tracked"))
    else:
        print("  git:  NOT FOUND")
        print()
        for line in _wrap(repo.git_missing_sentence(), 74):
            print("        " + line)
    print()

    account = repo.gitrun.gh_account()
    if not account["installed"]:
        print("  GitHub tool (gh): not installed — folders can still be kept safe, just not put online")
        print("                    from here. cli.github.com has it.")
    elif not account["logged_in"]:
        print("  GitHub tool (gh): installed, but not signed in. Run:  gh auth login")
    else:
        print("  GitHub tool (gh): signed in as %s" % account["account"])
    print()

    picker = native_picker.available()
    print("  System folder window: %s" % ("yes" if picker["ok"] else "no — " + picker["why"]))
    name, address = repo.default_identity()
    print("  Checkpoints would be signed: %s <%s>" % (name, address))
    print("  Where a dragged folder is looked for:")
    for root in survey.search_roots():
        print("        %s" % root)
    print()

    recent = store.recent_folders()
    if recent:
        print("  Folders you have looked after")
        for item in recent[:6]:
            print("        %s" % item["path"])
        print()

    print("  The words nanoGit uses instead of git's")
    for plain, git_word in [
        ("Checkpoint", "commit"),
        ("History", "repository"),
        ("Go back to this version", "checkout"),
        ("Bring it back", "show sha:path"),
        ("Take back the last checkpoint", "reset --soft"),
        ("Save a checkpoint", "add + commit"),
        ("Get the latest version", "fetch + merge --ff-only"),
        ("Copy the history to a file", "bundle"),
        ("Put it online", "push"),
        ("Things to leave out", ".gitignore"),
    ]:
        print("        %-30s %s" % (plain, git_word))
    print()
    return 0


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines, line = [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nanogit",
        description="%s — %s." % (APP_NAME, TAGLINE),
        epilog="Run it with no arguments and a browser window opens.",
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "doctor", "version"])
    parser.add_argument("--port", type=int, default=PORT, help="which port to use (default %d)" % PORT)
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    parser.add_argument("--version", action="store_true", help="print the version and stop")
    args = parser.parse_args(argv)

    if args.version or args.command == "version":
        print("%s %s" % (APP_NAME, __version__))
        return 0
    if args.command == "doctor":
        return _doctor()

    from .server import create_app

    # The 'save by itself' helper, for whoever turned it on. It only ever
    # touches the folder most recently looked after, and only after the wait
    # they chose — and it stops existing the moment this window closes.
    stop_autosave = threading.Event()
    threading.Thread(target=repo.auto_loop, args=(stop_autosave,), daemon=True, name="nanogit-autosave").start()

    app = create_app()
    try:
        app.serve(host=args.host, port=args.port, open_browser=not args.no_browser)
    except OSError as exc:
        print("\n  Could not start on %s:%d (%s).\n  Try a different port: --port %d\n"
              % (args.host, args.port, exc, args.port + 1))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
