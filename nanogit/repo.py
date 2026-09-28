"""The things nanoGit actually does to a folder.

Every function here is named after what a person asked for — "keep this safe",
"save a checkpoint", "go back", "put it online" — rather than after the git
command it happens to run. Each one returns a list of plain sentences
describing what it did, which is what the page shows.

Three rules hold everywhere in this file:

1. Nothing is ever deleted.
2. Nothing is ever force-pushed, reset hard, or thrown away.
3. Anything that would fail in a confusing way is checked for first, and
   explained in a sentence instead.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import re
from pathlib import Path

from . import gitrun, readme, store, survey
from .gitrun import Git, GitMissing

# How many checkpoints get a "what changed" sentence when the history is
# asked for in full. Older ones still show; this is only about the cost of
# asking git, once per checkpoint, what was inside.
WHAT_SUMMARY_LIMIT = 40

# The file list shown for "look inside a checkpoint" stops somewhere sensible.
FILES_LIST_LIMIT = 400


def default_identity() -> tuple[str, str]:
    """A sensible name and address to sign checkpoints with.

    Nobody should have to learn what a git identity is to keep a folder safe, so
    a reasonable one is chosen and can be changed from the page. If the GitHub
    tool is signed in, the private no-reply address is used, because a real one
    would end up in the history forever.
    """
    settings = store.load_settings()
    if settings.get("remember_author") and settings.get("author_name"):
        return settings["author_name"], settings["author_email"]

    try:
        who = getpass.getuser()
    except Exception:  # a machine with no notion of a user
        who = "Someone"
    account = gitrun.gh_account()
    if account.get("logged_in"):
        return who, "%s@users.noreply.github.com" % account["account"]
    return who, "%s@localhost" % who.replace(" ", ".")


def open_git() -> Git | None:
    try:
        return Git()
    except GitMissing:
        return None


def git_missing_sentence() -> str:
    return (
        "This computer does not have git on it, and nanoGit drives the real git program rather than "
        "pretending to be one. Install it from git-scm.com/downloads — on Windows that is a "
        "next-next-finish installer — then reopen nanoGit."
    )


# --------------------------------------------------------------------------
# Looking at a folder that is already tracked
# --------------------------------------------------------------------------
def status(git: Git, folder) -> dict:
    """Where this folder stands: tracked or not, saved or not, online or not."""
    target = Path(folder)
    if not target.is_dir():
        return {"ok": False, "error": "There is no folder at %s" % folder}

    exists = git.is_repo(folder)
    own = git.is_own_repo(folder)
    out = {
        "ok": True,
        "path": str(target),
        "name": target.name,
        "tracked": exists and own,
        "inside_other_repo": (git.top_level(folder) if exists and not own else ""),
        "checkpoints": 0,
        "changes": [],
        "change_summary": "",
        "remote": "",
        "unpushed": 0,
        "identity": {"name": "", "email": ""},
        "first_when": "",
        "last_when": "",
        "last_when_text": "",
        "days_since_last": None,
        "interrupted": False,
    }
    out["interrupted"] = bool(git.interrupted_lock(folder))
    if not out["tracked"]:
        return out

    changes = git.status(folder)
    out["changes"] = changes
    out["change_summary"] = summarise(changes)
    out["checkpoints"] = git.count_checkpoints(folder)
    out["remote"] = git.remote(folder)
    out["unpushed"] = git.unpushed(folder)
    name, email = git.identity(folder)
    out["identity"] = {"name": name, "email": email}
    history = git.log(folder, limit=1)
    if history:
        out["last_when"] = history[0]["when"]
        out["last_when_text"] = _friendly_when(history[0]["when"])
        out["days_since_last"] = _days_since(history[0]["when"])
    first = git.log(folder, limit=1000)
    if first:
        out["first_when"] = first[-1]["when"]
    return out


def summarise(changes: list[dict]) -> str:
    """'3 files changed, 2 of them new' — and nothing at all when nothing has."""
    if not changes:
        return "Everything is saved."
    counts: dict[str, int] = {}
    for change in changes:
        counts[change["kind"]] = counts.get(change["kind"], 0) + 1
    parts = ["%d %s" % (count, "file" if count == 1 else "files") for count in [len(changes)]]
    detail = ", ".join("%d %s" % (n, word) for word, n in sorted(counts.items()))
    return "%s since the last checkpoint (%s)." % (parts[0], detail)


# --------------------------------------------------------------------------
# The main event: keep this folder safe
# --------------------------------------------------------------------------
def start(git: Git, folder, name: str = "", description: str = "", author_name: str = "", author_email: str = "", extra_ignores: list[str] | None = None, remember_author: bool = False) -> dict:
    """Write a README and a .gitignore, start the history, save a first checkpoint.

    This is the one button on the front page. It is safe to press on a folder
    that is already tracked: it will not re-initialise anything, and it will not
    overwrite a README that is already there.
    """
    target = Path(folder)
    if not target.is_dir():
        return {"ok": False, "error": "There is no folder at %s" % folder}
    if not (target / ".git").exists() and survey._inside_other_repo(target):
        parent = survey._inside_other_repo(target)
        return {
            "ok": False,
            "error": "This folder is inside %s, which is already tracked. Tracking a folder inside another one "
                     "makes both of them confusing. Use %s itself, or move this folder somewhere of its own."
                     % (parent, parent),
        }

    steps: list[str] = []
    facts = survey.survey(folder)
    name = (name or facts["title"]).strip()
    description = (description or facts["description"] or "").strip()

    already = git.is_repo(folder) and git.is_own_repo(folder)

    # 1. Leave the private things out before anything is saved.
    ignores = list(readme.BASE_IGNORES)
    suggested = list(facts.get("suggested_ignores") or [])
    for pattern in extra_ignores or []:
        if pattern not in suggested:
            suggested.append(pattern)
    if suggested:
        ignores += ["", "# Things that look private, left out on purpose."] + suggested
    if git.ignore_file(folder, ignores):
        if suggested:
            steps.append(
                "Wrote .gitignore \u2014 the usual junk, plus %d thing%s that look private."
                % (len(suggested), "" if len(suggested) == 1 else "s")
            )
        else:
            steps.append("Wrote .gitignore, so the usual junk stays out of the history.")

    # 2. A README, so the folder explains itself to whoever finds it next.
    if not already or not (target / "README.md").exists():
        result = readme.write(folder, facts, name, description)
        steps.append(result["why"])

    # 3. Start the history.
    if not already:
        init = git.init(folder)
        if not init.ok:
            return {"ok": False, "error": "Could not start the history: %s" % init.clean_error(), "steps": steps}
        steps.append("Started the history for this folder.")

    # 4. A name to sign checkpoints with.
    who, address = git.identity(folder)
    if not who or not address:
        who, address = (author_name.strip() or None, author_email.strip() or None)
        if not who or not address:
            fallback_name, fallback_address = default_identity()
            who = who or fallback_name
            address = address or fallback_address
        git.set_identity(folder, who, address)
        steps.append("Checkpoints will be signed \u201c%s\u201d. You can change that under Settings." % who)

    if remember_author and author_name:
        store.save_settings({"author_name": author_name, "author_email": author_email, "remember_author": True})

    # 5. The first checkpoint.
    changes = git.status(folder)
    if changes:
        message = "First checkpoint" if not git.count_checkpoints(folder) else "Checkpoint from nanoGit"
        saved = git.commit_all(folder, message)
        signed_as = ""
        if not saved.ok and saved.needs_identity():
            fallback_name, fallback_address = default_identity()
            git.set_identity(folder, fallback_name, fallback_address)
            retry = git.commit_all(folder, message)
            if retry.ok:
                saved = retry
                signed_as = fallback_name
        if saved.ok:
            if facts["file_count"] == 0:
                steps.append("The folder was empty, so the first checkpoint just holds the README and the .gitignore.")
            else:
                steps.append("Saved a checkpoint with %d file%s in it."
                             % (len(changes), "" if len(changes) == 1 else "s"))
            if signed_as:
                steps.append("It was signed \u201c%s\u201d. You can change that under Settings." % signed_as)
        elif saved.says_nothing_to_do():
            steps.append("There was nothing new to save yet.")
        else:
            steps.append("The first save did not go through: %s" % saved.clean_error())
    else:
        if git.count_checkpoints(folder):
            steps.append("Nothing has changed since the last checkpoint, so there was nothing new to save.")
        else:
            steps.append(
                "The folder is empty, so there was nothing to save yet \u2014 the history is ready for when there is."
            )

    store.remember_folder(folder, name)
    store.save_settings({"last_folder": str(target)})
    return {
        "ok": True,
        "steps": steps,
        "status": status(git, folder),
        "survey": facts,
        "readme": str(target / "README.md"),
    }


# The glance before saving: never more than a page of it.
MAX_DIFF_FILES = 12
MAX_LINES_PER_FILE = 4
MAX_TEXT_BYTES = 256 * 1024


def _looks_like_text(path) -> bool:
    """A cheap, honest check: a NUL byte in the first kilobyte means binary."""
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(1024)
    except OSError:
        return False
    return b"\x00" not in chunk


def preview_changes(git: Git, folder) -> dict:
    """What a checkpoint is about to save, piece by piece, before saving.

    Changed text files show a few of the real changed lines; new text files
    show their first lines; pictures and other binary things just say that
    they changed. Never more than twelve files and four lines each — this is
    a glance, not a diff viewer.
    """
    if not git.is_own_repo(folder) or not git.count_checkpoints(folder):
        return {"ok": True, "files": [],
                "why": "This folder has no history yet, so the first checkpoint saves everything in it."}
    changes = git.status(folder)
    files: list[dict] = []
    for change in changes[:MAX_DIFF_FILES]:
        entry = {"path": change["path"], "kind": change["kind"], "lines": []}
        target = Path(folder) / change["path"]
        if change["kind"] == "new":
            try:
                if target.is_file() and target.stat().st_size <= MAX_TEXT_BYTES and _looks_like_text(target):
                    entry["lines"] = ["+ " + line for line in target.read_text(
                        encoding="utf-8", errors="replace").splitlines()[:MAX_LINES_PER_FILE]]
            except OSError:
                pass
        elif change["kind"] in ("changed", "renamed", "gone"):
            diff = git.run("diff", "HEAD", "--", change["path"], cwd=folder)
            entry["lines"] = [line for line in diff.lines()
                              if line[:1] in "+-" and line[:3] not in ("+++", "---")][:MAX_LINES_PER_FILE]
        files.append(entry)
    return {"ok": True, "files": files, "total": len(changes)}


def checkpoint(git: Git, folder, message: str = "") -> dict:
    """Save everything in the folder as it is now."""
    if not git.is_own_repo(folder):
        # No history here yet: starting it is what saving means. start() writes
        # the README and the .gitignore, and refuses a folder inside another
        # tracked one, which is exactly the right answer here too.
        return start(git, folder)

    changes = git.status(folder)
    if not changes:
        return {"ok": True, "steps": ["Nothing has changed since the last checkpoint, so there was nothing to save."],
                "status": status(git, folder)}

    if not git.count_checkpoints(folder):
        return start(git, folder)
    store.save_settings({"last_folder": str(Path(folder))})

    stamp = _dt.datetime.now().strftime("%d %b %Y, %H:%M")
    # The person's words are saved as they typed them; when nothing was typed,
    # the summary of what changed becomes the message.
    text = (message or "").strip() or "Checkpoint — %s" % summarise(changes).rstrip(".")
    saved = git.commit_all(folder, text)
    if saved.ok:
        steps = ["Saved a checkpoint: %s" % summarise(changes)]
    elif saved.says_nothing_to_do():
        steps = ["Nothing had actually changed, so no checkpoint was needed."]
    elif saved.needs_identity():
        who, address = default_identity()
        git.set_identity(folder, who, address)
        retry = git.commit_all(folder, text)
        steps = ["Saved a checkpoint, signed \u201c%s\u201d." % who] if retry.ok \
            else ["Could not save: %s" % retry.clean_error()]
    else:
        return {"ok": False, "error": saved.clean_error(), "steps": ["Could not save a checkpoint."],
                "status": status(git, folder)}
    return {"ok": True, "steps": steps, "status": status(git, folder)}


def history(git: Git, folder, limit: int = 60, with_what: bool = False) -> dict:
    """The checkpoints, newest first, each with the sentence to show for it.

    ``with_what`` also answers "what changed in this one?" for the newest
    checkpoints. It is capped because each answer is a git command of its own.
    """
    if not (git.is_repo(folder) and git.is_own_repo(folder)):
        return {"ok": True, "entries": [], "note": "This folder is not tracked yet."}
    entries = git.log(folder, limit=limit)
    for index, entry in enumerate(entries):
        entry["when_text"] = _friendly_when(entry["when"])
        entry["was_first"] = index == len(entries) - 1
        if with_what and index < WHAT_SUMMARY_LIMIT:
            entry["what"] = _change_words(git.change_list(folder, entry["sha"]))
        else:
            entry["what"] = {}
    return {"ok": True, "entries": entries, "note": ""}


def _change_words(items: list[dict]) -> dict:
    """'3 files: 1 new, 2 changed · +45 −12' — one checkpoint, in words."""
    counts: dict[str, int] = {}
    added = deleted = 0
    have_lines = False
    for item in items:
        kind = item.get("kind") or "changed"
        counts[kind] = counts.get(kind, 0) + 1
        if isinstance(item.get("added"), int):
            added += item["added"]
            have_lines = True
        if isinstance(item.get("deleted"), int):
            deleted += item["deleted"]
            have_lines = True
    total = len(items)
    text = "%d file%s" % (total, "" if total == 1 else "s")
    detail = ", ".join("%d %s" % (n, word) for word, n in sorted(counts.items()))
    if detail:
        text += ": " + detail
    if have_lines and (added or deleted):
        text += " · +%d −%d" % (added, deleted)
    return {"files": total, "counts": counts, "added": added, "deleted": deleted, "text": text}


def _safe_relative(path: str) -> str:
    """A path inside the folder, or nothing at all.

    The one place a typed-in path could escape the folder is here, so '..' and
    absolute paths are refused outright rather than negotiated with.
    """
    cleaned = (path or "").strip().replace("\\", "/").lstrip("/")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def _days_since(stamp: str) -> "int | None":
    """How many calendar days ago an ISO timestamp was — None when unreadable."""
    if not stamp:
        return None
    try:
        when = _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None
    return (_dt.datetime.now(when.tzinfo).date() - when.date()).days


def go_back(git: Git, folder, sha: str) -> dict:
    """Put the files back the way they were at a checkpoint.

    The current state is saved first, so pressing this can never lose work — and
    files added after that checkpoint are left alone rather than deleted. Both
    of those choices are deliberate: this is the button a person presses when
    they are already worried.
    """
    if not re_sha(sha):
        return {"ok": False, "error": "That is not a version nanoGit recognises."}
    known = {entry["sha"] for entry in git.log(folder, limit=500)}
    if sha not in known and not any(item.startswith(sha) for item in known):
        return {"ok": False, "error": "That checkpoint is not in this folder's history."}

    steps = []
    if git.status(folder):
        safety = checkpoint(git, folder, "Checkpoint saved automatically before going back")
        steps.extend(safety.get("steps", []))
        if not safety.get("ok"):
            return {"ok": False, "error": safety.get("error", "Could not save the current state first."), "steps": steps}

    added = git.added_since(folder, sha)
    result = git.restore_files(folder, sha)
    if not result.ok:
        return {"ok": False, "error": result.clean_error(), "steps": steps}

    changed = git.files_changed_by_restore(folder, sha)
    entry = next((item for item in git.log(folder, limit=500) if item["sha"].startswith(sha)), {})
    steps.append("Put %d file%s back to how they were on %s."
                 % (len(changed), "" if len(changed) == 1 else "s", _friendly_when(entry.get("when", ""))))
    if added:
        steps.append("%d file%s kept, because %s added after that checkpoint — nothing was deleted."
                     % (len(added), "" if len(added) == 1 else "s",
                        "it was" if len(added) == 1 else "they were"))
    return {"ok": True, "steps": steps, "status": status(git, folder), "history": history(git, folder)["entries"]}


def re_sha(sha: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{4,40}", sha or ""))


def _first_url(text: str) -> str:
    """The first GitHub address in whatever gh printed, if there is one."""
    match = re.search(r"https://github\.com/[\w.-]+/[\w.-]+", text or "")
    return match.group(0) if match else ""


def _friendly_when(stamp: str) -> str:
    """An ISO timestamp as 'today at 16:04' / '3 days ago'."""
    if not stamp:
        return "an unknown date"
    try:
        when = _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return stamp
    now = _dt.datetime.now(when.tzinfo)
    days = (now.date() - when.date()).days
    clock = when.strftime("%H:%M")
    if days == 0:
        return "today at %s" % clock
    if days == 1:
        return "yesterday at %s" % clock
    if days < 7:
        return "%d days ago, %s" % (days, clock)
    return when.strftime("%d %b %Y, %H:%M")


# --------------------------------------------------------------------------
# Looking inside a checkpoint, and bringing one file back from it
# --------------------------------------------------------------------------
def checkpoint_files(git: Git, folder, sha: str) -> dict:
    """Everything inside one checkpoint — the 'look inside' view."""
    if not re_sha(sha):
        return {"ok": False, "error": "That is not a version nanoGit recognises.", "files": []}
    known = {entry["sha"]: entry for entry in git.log(folder, limit=500)}
    full = next((item for item in known if item.startswith(sha)), "")
    if not full:
        return {"ok": False, "error": "That checkpoint is not in this folder's history.", "files": []}
    entry = known[full]
    changed = {item["path"]: item for item in git.change_list(folder, full)}
    paths = git.files_at(folder, full)
    rows = []
    for path in paths[:FILES_LIST_LIMIT]:
        item = changed.get(path) or {}
        rows.append(
            {
                "path": path,
                "kind": item.get("kind", ""),
                "added": item.get("added"),
                "deleted": item.get("deleted"),
                "gone_now": not (Path(folder) / path).is_file(),
            }
        )
    return {
        "ok": True,
        "sha": full,
        "short": entry["short"],
        "message": entry["message"],
        "when": entry["when"],
        "when_text": _friendly_when(entry["when"]),
        "files": rows,
        "truncated": len(paths) > FILES_LIST_LIMIT,
        "total": len(paths),
        "what": _change_words(list(changed.values())),
    }


def bring_back(git: Git, folder, sha: str, relative: str) -> dict:
    """Put one file back the way a checkpoint had it.

    If something unsaved is sitting in the folder it is checkpointed first, so
    this button, like every other button here, cannot lose work. The file is
    copied out of the history byte for byte — a picture comes back as the same
    picture, not a re-typed one.
    """
    target_rel = _safe_relative(relative)
    if not target_rel:
        return {"ok": False, "error": "That is not a file nanoGit can bring back."}
    if not re_sha(sha):
        return {"ok": False, "error": "That is not a version nanoGit recognises."}
    known = [entry["sha"] for entry in git.log(folder, limit=500) if entry["sha"].startswith(sha)]
    if not known:
        return {"ok": False, "error": "That checkpoint is not in this folder's history."}
    full = known[0]
    found, content = git.file_at(folder, full, target_rel)
    if not found:
        return {"ok": False, "error": "“%s” is not inside that checkpoint." % target_rel}

    target = Path(folder) / target_rel
    if target.is_file():
        try:
            if target.read_bytes() == content:
                return {
                    "ok": True,
                    "steps": ["“%s” is already exactly the version from that checkpoint." % target_rel],
                    "status": status(git, folder),
                }
        except OSError:
            pass

    steps: list[str] = []
    if git.status(folder):
        safety = checkpoint(git, folder, "Checkpoint saved automatically before bringing back %s" % target_rel)
        if not safety.get("ok"):
            return {"ok": False, "error": safety.get("error", "Could not save the current state first."), "steps": steps}
        steps.extend(safety.get("steps", []))

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    except OSError as exc:
        return {"ok": False, "error": "Could not write the file back: %s" % exc, "steps": steps}

    entry = next((item for item in git.log(folder, limit=500) if item["sha"] == full), {})
    steps.append(
        "Brought back “%s” the way it was %s." % (target_rel, _friendly_when(entry.get("when", "")))
    )
    return {"ok": True, "steps": steps, "status": status(git, folder)}


# --------------------------------------------------------------------------
# The gentle undo: take back the last checkpoint, keep the work
# --------------------------------------------------------------------------
def take_back(git: Git, folder) -> dict:
    """Un-save the most recent checkpoint. Nothing is deleted: the work in it
    becomes unsaved changes again, ready to be reshaped and saved properly."""
    if not (git.is_repo(folder) and git.is_own_repo(folder)):
        return {"ok": False, "error": "This folder is not being looked after yet."}
    if git.interrupted_lock(folder):
        return {"ok": False, "error": "A previous save was interrupted. Tidy that up first.", "interrupted": True}
    if git.count_checkpoints(folder) < 2:
        return {
            "ok": False,
            "error": "That is the first checkpoint — the floor of the history. There is nothing "
                     "underneath it to go back to, so it stays.",
        }
    last = (git.log(folder, limit=1) or [{}])[0]
    result = git.reset_soft(folder)
    if not result.ok:
        return {"ok": False, "error": result.clean_error()}
    changes = git.status(folder)
    steps = [
        "Took back the last checkpoint, “%s” — its work is in the folder as unsaved changes "
        "now. Nothing was deleted." % (last.get("message") or "Checkpoint"),
    ]
    if changes:
        steps.append("Change whatever you meant to change, then save a new checkpoint.")
    return {"ok": True, "steps": steps, "status": status(git, folder)}


def tidy_up(git: Git, folder) -> dict:
    """Clear the mark git leaves when a save was stopped halfway.

    When git is interrupted mid-save it leaves a small 'I am still working'
    note behind, and then refuses to do anything until the note is removed.
    Only that note is removed here — never a file of yours.
    """
    if not git.interrupted_lock(folder):
        return {"ok": True, "steps": ["There was nothing to tidy."]}
    if not git.clear_interrupted_lock(folder):
        return {
            "ok": False,
            "error": "The half-finished save could not be cleared. Closing other windows that are "
                     "looking at this folder may help.",
        }
    return {
        "ok": True,
        "steps": ["Cleaned up the half-finished save. Everything else was left exactly as it was."],
        "status": status(git, folder),
    }


# --------------------------------------------------------------------------
# A copy of the history you can hold in your hand
# --------------------------------------------------------------------------
def copy_history(git: Git, folder, destination) -> dict:
    """Write the whole history as one file — for a USB stick or a second computer.

    Uses git's own bundle format, so the copy is not a dead archive: anyone
    with git can open it and get the folder back, checkpoints and all.
    """
    if not destination:
        return {"ok": False, "error": "Pick where the copy should go."}
    if not (git.is_repo(folder) and git.is_own_repo(folder)):
        return {"ok": False, "error": "Keep this folder safe first — there is no history to copy yet."}
    count = git.count_checkpoints(folder)
    if not count:
        return {"ok": False, "error": "Save a checkpoint first — there is no history to copy yet."}
    dest = Path(str(destination).strip().strip('"'))
    if not dest.is_dir():
        return {"ok": False, "error": "There is no folder at %s" % dest}
    root = Path(folder).resolve()
    try:
        if dest.resolve() == root or root in dest.resolve().parents:
            return {
                "ok": False,
                "error": "Choose somewhere outside this folder — a copy of the history does not "
                         "belong inside the thing it is a copy of.",
            }
    except OSError:
        pass
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M")
    name = "%s-history-%s.bundle" % (survey.slugify(root.name) or "folder", stamp)
    target = dest / name
    made = git.bundle(folder, target)
    if not made.ok:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "error": made.clean_error()}
    try:
        size = target.stat().st_size
    except OSError:
        size = 0
    steps = [
        "Wrote %s — the whole history in one file (%s)." % (name, survey.human_size(size)),
    ]
    if git.bundle_verify(folder, target).ok:
        steps.append("Checked it: it opens, and it holds %d checkpoint%s."
                     % (count, "" if count == 1 else "s"))
    steps.append("Keep it on a USB stick or another computer. To open it again later, "
                 "someone with git runs: git clone “%s”" % name)
    return {"ok": True, "steps": steps, "file": str(target), "status": status(git, folder)}


# --------------------------------------------------------------------------
# Keeping up with the online copy
# --------------------------------------------------------------------------
def online_check(git: Git, folder) -> dict:
    """Where the folder stands against its home online. Only ever reads: the
    fetch it runs changes nothing on disk."""
    base = {"ok": True, "remote": "", "reachable": False, "incoming": 0, "outgoing": 0}
    if not (git.is_repo(folder) and git.is_own_repo(folder)):
        return dict(base, explain="This folder is not being looked after yet.")
    remote = git.remote(folder)
    if not remote:
        return dict(base, explain="This folder has not been put online yet.")
    fetched = git.fetch(folder)
    if not fetched.ok:
        return dict(
            base,
            remote=remote,
            outgoing=git.unpushed(folder),
            explain="The online copy could not be reached just now — the internet may be off, "
                    "or GitHub may be having a moment. Nothing was changed.",
        )
    incoming = git.incoming(folder)
    outgoing = git.unpushed(folder)
    if incoming and outgoing:
        explain = ("Both this computer and the online copy have new checkpoints, in different "
                   "directions. Joining those up needs git, or a patient friend who knows it.")
    elif incoming:
        explain = "%d checkpoint%s waiting online, ready to bring down." % (
            incoming, "" if incoming == 1 else "s")
    elif outgoing:
        explain = "This computer is %d checkpoint%s ahead — “Put it online” sends them up." % (
            outgoing, "" if outgoing == 1 else "s")
    else:
        explain = "Everything matches the online copy."
    return dict(base, remote=remote, reachable=True, incoming=incoming, outgoing=outgoing, explain=explain)


def get_latest(git: Git, folder) -> dict:
    """Bring down the checkpoints that are waiting online.

    Three kind refusals before git is ever asked to move anything: not online
    yet, unsaved work in the folder, or both sides moved at once. In each case
    everything is left exactly as it was, with a sentence saying why.
    """
    state = online_check(git, folder)
    if not state.get("remote"):
        return {"ok": False, "error": "This folder has not been put online yet, so there is nothing to get."}
    if not state.get("reachable"):
        return {"ok": False, "error": "The online copy could not be reached. Check the internet and try again."}
    if not state.get("incoming"):
        return {"ok": True, "steps": ["Already up to date — the online copy has nothing new."],
                "status": status(git, folder)}
    if state.get("outgoing"):
        return {
            "ok": False,
            "error": "This computer and the online copy each have checkpoints the other does not. "
                     "Bringing those together needs git, or a patient friend who knows it. "
                     "Everything is left as it is.",
        }
    if git.status(folder):
        return {
            "ok": False,
            "error": "There are unsaved changes here. Save a checkpoint first, so what comes down "
                     "does not land on top of unfinished work.",
        }
    merged = git.merge_ff_only(folder)
    if not merged.ok:
        return {"ok": False, "error": merged.clean_error()}
    incoming = state["incoming"]
    return {
        "ok": True,
        "steps": ["Brought down %d checkpoint%s from online." % (incoming, "" if incoming == 1 else "s"),
                  "This folder now matches its online copy."],
        "status": status(git, folder),
        "history": history(git, folder)["entries"],
    }


# --------------------------------------------------------------------------
# Saving by itself, for people who asked it to
# --------------------------------------------------------------------------
def auto_check_once(git: Git | None = None) -> dict:
    """One quiet look: save a checkpoint for the person, if it is due.

    Only ever touches the folder most recently looked after, only after the
    wait they chose, and only when something actually changed. A silent helper:
    it never nags, and its failures interest nobody.
    """
    settings = store.load_settings()
    try:
        wait = int(settings.get("auto_checkpoint_minutes") or 0)
    except (TypeError, ValueError):
        wait = 0
    if wait <= 0:
        return {"ok": True, "saved": False, "why": "automatic checkpoints are off"}

    folder = settings.get("last_folder") or ""
    if not folder:
        recent = store.recent_folders()
        folder = recent[0]["path"] if recent else ""
    if not folder or not Path(folder).is_dir():
        return {"ok": True, "saved": False, "why": "no folder is being looked after"}

    own = git or open_git()
    if not own:
        return {"ok": True, "saved": False, "why": "git is not on this computer"}
    if not (own.is_repo(folder) and own.is_own_repo(folder)):
        return {"ok": True, "saved": False, "why": "that folder is not tracked"}
    if own.interrupted_lock(folder):
        return {"ok": True, "saved": False, "why": "a previous save was interrupted"}

    last = (own.log(folder, limit=1) or [{}])[0]
    stamp = last.get("when", "")
    if stamp:
        try:
            when = _dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
            minutes_since = (_dt.datetime.now(when.tzinfo) - when).total_seconds() / 60.0
        except ValueError:
            minutes_since = float("inf")
    else:
        minutes_since = float("inf")
    if minutes_since < wait:
        return {"ok": True, "saved": False, "why": "saved recently enough"}

    changes = own.status(folder)
    if not changes:
        return {"ok": True, "saved": False, "why": "nothing changed"}
    saved = checkpoint(own, folder, "Automatic checkpoint — %s" % summarise(changes).rstrip("."))
    return {
        "ok": bool(saved.get("ok")),
        "saved": bool(saved.get("ok")),
        "folder": folder,
        "steps": saved.get("steps", []),
    }


def auto_loop(stop, interval: int = 60) -> None:
    """The background saver: wakes up, checks once, goes back to sleep."""
    while not stop.wait(interval):
        try:
            auto_check_once()
        except Exception:
            pass  # a quiet helper never makes a noise, and never crashes the app


# --------------------------------------------------------------------------
# Putting it online
# --------------------------------------------------------------------------
def readiness(git: Git, folder) -> dict:
    """Everything that has to be true before the publish button does anything."""
    facts = survey.survey(folder)
    account = gitrun.gh_account()
    own = git.is_repo(folder) and git.is_own_repo(folder)
    blocking = [item for item in facts.get("big_files", []) if item["blocking"]]
    out = {
        "ok": True,
        "tracked": own,
        "checkpoints": git.count_checkpoints(folder) if own else 0,
        "remote": git.remote(folder) if own else "",
        "gh": account,
        "secrets": facts.get("secrets") or [],
        "blocking_files": blocking,
        "can_publish": bool(own and account.get("logged_in") and not blocking),
        "name": facts["slug"],
        "title": facts["title"],
        "description": facts.get("description") or "",
    }
    if not own:
        out["explain"] = "Save this folder a first time before putting it online."
    elif blocking:
        out["explain"] = (
            "%s is %s, which is larger than GitHub accepts. Leave it out of the folder, or add it to "
            ".gitignore, and try again." % (blocking[0]["path"], blocking[0]["size_text"])
        )
    elif not account.get("installed"):
        out["explain"] = (
            "Putting a folder online needs the GitHub tool. Get it from cli.github.com, then run "
            "\u201cgh auth login\u201d once. nanoGit can show you the same steps by hand instead."
        )
    elif not account.get("logged_in"):
        out["explain"] = "The GitHub tool is installed but not signed in. Run \u201cgh auth login\u201d once, then come back."
    elif out["remote"]:
        out["explain"] = "This folder already points at %s. Pressing the button sends the new checkpoints there." % out["remote"]
    else:
        out["explain"] = "Ready. One press creates the repository under %s and sends everything up." % account["account"]
    return out


def publish(git: Git, folder, name: str = "", private: bool = True, description: str = "", allow_secrets: bool = False) -> dict:
    """Create the repository online and send the folder up.

    If anything looks private it stops and says so, rather than putting a
    password on the internet and mentioning it afterwards.
    """
    facts = survey.survey(folder)
    blocking = [item for item in facts.get("big_files", []) if item["blocking"]]
    if blocking:
        return {
            "ok": False,
            "error": "%s is %s. GitHub will not accept a folder containing that. Add it to .gitignore first."
                     % (blocking[0]["path"], blocking[0]["size_text"]),
        }
    secrets = facts.get("secrets") or []
    still_there = [item for item in secrets if not _ignored(folder, item["path"])]
    if still_there and not allow_secrets:
        return {
            "ok": False,
            "error": "Nothing was uploaded. %d file%s in this folder look private, and they are not being left out yet."
                     % (len(still_there), "" if len(still_there) == 1 else "s"),
            "secrets": still_there,
            "ask": "Leave them out (recommended) or upload anyway?",
        }

    existing = git.remote(folder)
    slug = survey.slugify(name or facts["slug"])
    if existing:
        push = git.run("push", "-u", "origin", "HEAD", cwd=folder, timeout=gitrun.PUSH_TIMEOUT)
        if push.ok:
            return {"ok": True, "steps": ["Sent the new checkpoints up to %s." % existing], "url": existing}
        return {"ok": False, "error": push.clean_error(), "steps": ["The upload did not finish."]}

    result = gitrun.gh_publish(folder, slug, private, description or facts.get("description") or "")
    if result.ok:
        url = _first_url(result.out + " " + result.err)
        return {
            "ok": True,
            "steps": ["Created the repository \u201c%s\u201d and sent everything up." % slug,
                      "Private" if private else "Public \u2014 anyone with the link can read it."],
            "url": url or "https://github.com/%s/%s" % (gitrun.gh_account().get("account", ""), slug),
        }
    if "already exists" in (result.err + result.out).lower():
        return {
            "ok": False,
            "error": "There is already a repository called \u201c%s\u201d in your account. Type a different name, or "
                     "point this folder at the one that exists." % slug,
        }
    return {
        "ok": False,
        "error": result.clean_error(),
        "manual": gitrun.manual_commands(folder, slug, private),
    }


def _ignored(folder, relative: str) -> bool:
    """True when .gitignore appears to cover this path."""
    path = Path(folder) / ".gitignore"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    name = Path(relative).name
    slashed = relative.replace("\\", "/")
    for line in lines:
        rule = line.strip()
        if not rule or rule.startswith("#"):
            continue
        if rule in (name, slashed):
            return True
        if rule.startswith("*") and name.endswith(rule.lstrip("*")):
            return True
        if rule.endswith("/") and slashed.startswith(rule.rstrip("/") + "/"):
            return True
    return False
