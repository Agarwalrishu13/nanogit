"""The real folder-picking window from the operating system.

Typing a path is the one thing that stops a non-technical person in their
tracks, so where Python can show the folder dialog that Windows and Linux
already have, nanoGit shows it. tkinter ships with Python, so this costs no
dependency.

Two honest caveats, both handled rather than hidden:

* On macOS, Tk insists on running on the main thread, and this app's main
  thread belongs to the web server. Rather than risk freezing the window, the
  built-in folder list is used there instead.
* On Linux, tkinter is a separate package (``python3-tk``) that is often not
  installed. If it is missing, ``available()`` says so and the page falls back.
"""

from __future__ import annotations

import sys
import threading

# One dialog at a time: two Tk roots in two threads is a reliable way to hang.
_LOCK = threading.Lock()


def available() -> dict:
    """Whether a native dialog can be shown, and if not, why not."""
    if sys.platform == "darwin":
        return {"ok": False, "why": "macOS needs its dialogs on the main thread, so nanoGit uses its own folder list here."}
    try:
        import tkinter  # noqa: F401
    except Exception as exc:
        return {"ok": False, "why": "The Python here was built without tkinter (%s)." % exc}
    return {"ok": True, "why": ""}


def choose(initial: str = "", title: str = "Choose the folder to look after") -> dict:
    """Open the operating system's folder picker and wait for an answer."""
    ready = available()
    if not ready["ok"]:
        return {"ok": False, "why": ready["why"]}
    if not _LOCK.acquire(blocking=False):
        return {"ok": False, "why": "A folder window is already open."}
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        root.update()
        try:
            root.attributes("-topmost", True)
        except tkinter.TclError:
            pass
        try:
            picked = filedialog.askdirectory(initialdir=initial or None, title=title, mustexist=True)
        finally:
            root.destroy()
        if not picked:
            return {"ok": True, "cancelled": True, "path": ""}
        return {"ok": True, "cancelled": False, "path": str(picked)}
    except Exception as exc:  # no display, no Tk, a window manager that says no
        return {"ok": False, "why": "Could not open the system folder window (%s)." % exc}
    finally:
        _LOCK.release()
