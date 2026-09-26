"""Everything nanoGit remembers between visits.

Settings and the list of folders you have already looked after live in
``~/.nanogit``. Nothing here is ever uploaded anywhere, and deleting the folder
makes the app forget everything it knew.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

APP_DIR_NAME = ".nanogit"

DEFAULT_SETTINGS = {
    # The name and address written on every checkpoint. Kept per folder unless
    # the person asks for it to be remembered; nobody is asked to learn what a
    # git identity is.
    "author_name": "",
    "author_email": "",
    "remember_author": False,
    # Where "open the folder" and "publish" default to.
    "last_folder": "",
    "publish_private": True,
}

MAX_RECENT = 12


def data_dir() -> Path:
    override = os.environ.get("NANOGIT_HOME")
    base = Path(override) if override else Path.home() / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _settings_path() -> Path:
    return data_dir() / "settings.json"


def _recent_path() -> Path:
    return data_dir() / "recent.json"


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if isinstance(stored, dict):
        settings.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    return settings


def save_settings(patch: dict) -> dict:
    settings = load_settings()
    settings.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS})
    _write(_settings_path(), settings)
    return settings


def _write(path: Path, payload) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def recent_folders() -> list[dict]:
    try:
        stored = json.loads(_recent_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(stored, list):
        return []
    out = []
    for item in stored:
        if isinstance(item, dict) and item.get("path"):
            # A folder that has since been moved or deleted is not offered.
            if Path(item["path"]).is_dir():
                out.append(item)
    return out


def remember_folder(path, note: str = "") -> None:
    resolved = str(path)
    entries = [item for item in recent_folders() if item.get("path") != resolved]
    entries.insert(0, {"path": resolved, "note": note, "at": time.time()})
    try:
        _write(_recent_path(), entries[:MAX_RECENT])
    except OSError:
        pass  # a read-only home directory is not worth failing a job over


def forget_folder(path) -> None:
    resolved = str(path)
    try:
        _write(_recent_path(), [i for i in recent_folders() if i.get("path") != resolved])
    except OSError:
        pass
