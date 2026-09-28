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
    }
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
        if saved.ok:
            if facts["file_count"] == 0:
                steps.append("The folder was empty, so the first checkpoint just holds the README and the .gitignore.")
            else:
                steps.append("Saved a checkpoint with %d file%s in it."
                             % (len(changes), "" if len(changes) == 1 else "s"))
        elif saved.says_nothing_to_do():
            steps.append("There was nothing new to save yet.")
        elif saved.needs_identity():
            fallback_name, fallback_address = default_identity()
            git.set_identity(folder, fallback_name, fallback_address)
            retry = git.commit_all(folder, message)
            if retry.ok:
                steps.append("Saved a checkpoint signed \u201c%s\u201d." % fallback_name)
            else:
                steps.append("The first save did not go through: %s" % retry.clean_error())
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


def history(git: Git, folder, limit: int = 60) -> dict:
    """The checkpoints, newest first, each with the sentence to show for it."""
    if not (git.is_repo(folder) and git.is_own_repo(folder)):
        return {"ok": True, "entries": [], "note": "This folder is not tracked yet."}
    entries = git.log(folder, limit=limit)
    for index, entry in enumerate(entries):
        entry["when_text"] = _friendly_when(entry["when"])
        entry["was_first"] = index == len(entries) - 1
    return {"ok": True, "entries": entries, "note": ""}


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
