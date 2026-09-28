"""Talking to the ``git`` program that is already on the computer.

nanoGit does not reimplement git and does not hide it: it runs the real thing,
with the settings a first-time user needs (no pager, no editor popping open, no
password prompt hanging the window) and turns the results into something the
page can show. Every command it runs is here, in one file, so it is possible to
read exactly what this app does to somebody's folder.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

# Folders are surveyed and reported; nothing is ever deleted by this module.
DEFAULT_TIMEOUT = 60
PUSH_TIMEOUT = 300

# git writes a great deal of advice to stderr on a first run. None of it is an
# error, and showing it to somebody who has never used git is worse than useless.
_NOISE = (
    "hint:",
    "warning: LF will be replaced",
    "warning: CRLF will be replaced",
    "warning: in the working copy",
    "nothing added to commit",
)

_UNSET_IDENTITY = (
    "please tell me who you are",
    "unable to auto-detect email address",
    "empty ident name",
)


class Result:
    """What came back from one git command."""

    def __init__(self, args, code: int, out: str, err: str, timed_out: bool = False):
        self.args = args
        self.code = code
        self.out = out
        self.err = err
        self.timed_out = timed_out

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out

    def lines(self) -> list[str]:
        return [line for line in self.out.splitlines() if line.strip()]

    def says_nothing_to_do(self) -> bool:
        """True for the harmless "there was nothing to save" outcomes."""
        blob = (self.out + " " + self.err).lower()
        return "nothing to commit" in blob or "no changes added to commit" in blob

    def needs_identity(self) -> bool:
        blob = (self.out + " " + self.err).lower()
        return any(marker in blob for marker in _UNSET_IDENTITY)

    def clean_error(self) -> str:
        """The message a person should see: no hints, no blank lines."""
        kept = []
        for line in (self.err or self.out).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(_NOISE):
                continue
            kept.append(stripped)
        return "\n".join(kept[:6]) or "git did not say why."


class GitMissing(Exception):
    """Raised when there is no ``git`` on this computer."""


def find_git() -> str | None:
    """The path to git, or None.

    Windows installers often leave git off PATH for programs that were already
    open, so the usual locations are checked by hand before giving up.
    """
    found = shutil.which("git")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "cmd" / "git.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "cmd" / "git.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe",
        Path("/usr/bin/git"),
        Path("/usr/local/bin/git"),
        Path("/opt/homebrew/bin/git"),
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _env() -> dict:
    """An environment where git cannot stop and ask a question.

    A credential prompt or a pager waiting for a keypress would freeze the app
    with no way for the person using it to tell what happened, so they are off.
    """
    env = dict(os.environ)
    env.update(
        {
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
        }
    )
    return env


class Git:
    """A small, explicit wrapper around the git command line."""

    def __init__(self, exe: str | None = None):
        self.exe = exe or find_git()
        if not self.exe:
            raise GitMissing(
                "git was not found on this computer. nanoGit drives the real git program "
                "rather than pretending to be one."
            )

    # -- running ----------------------------------------------------------
    def run(self, *args: str, cwd=None, timeout: int = DEFAULT_TIMEOUT, stdin: str | None = None) -> Result:
        command = [self.exe, "-c", "core.quotepath=false", "-c", "color.ui=false", *args]
        try:
            done = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                env=_env(),
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return Result(args, 124, "", "That took too long and was stopped.", timed_out=True)
        except OSError as exc:
            return Result(args, 127, "", str(exc))
        return Result(args, done.returncode, done.stdout or "", done.stderr or "")

    def version(self) -> str:
        result = self.run("--version")
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", result.out or result.err)
        return match.group(1) if match else "unknown"

    # -- identity ---------------------------------------------------------
    def identity(self, folder) -> tuple[str, str]:
        """The name and address that will be written on a checkpoint."""
        name = self.run("config", "user.name", cwd=folder).out.strip()
        email = self.run("config", "user.email", cwd=folder).out.strip()
        return name, email

    def set_identity(self, folder, name: str, email: str, global_too: bool = False) -> None:
        scope = "--global" if global_too else "--local"
        if name:
            self.run("config", scope, "user.name", name, cwd=folder)
        if email:
            self.run("config", scope, "user.email", email, cwd=folder)

    # -- the commands nanoGit actually uses -------------------------------
    def is_repo(self, folder) -> bool:
        """True when this folder is tracked (or lives inside something tracked)."""
        result = self.run("rev-parse", "--is-inside-work-tree", cwd=folder)
        return result.ok and result.out.strip() == "true"

    def is_own_repo(self, folder) -> bool:
        """True when *this* folder is the tracked one, not a parent of it."""
        return (Path(folder) / ".git").exists()

    def top_level(self, folder) -> str:
        return self.run("rev-parse", "--show-toplevel", cwd=folder).out.strip()

    def init(self, folder, branch: str = "main") -> Result:
        """Start the history. Modern git takes -b; older git needs the rename."""
        result = self.run("init", "-b", branch, cwd=folder)
        if not result.ok:
            result = self.run("init", cwd=folder)
            if result.ok:
                self.run("symbolic-ref", "HEAD", "refs/heads/" + branch, cwd=folder)
        return result

    def status(self, folder) -> list[dict]:
        """What has changed since the last checkpoint, in plain terms."""
        result = self.run("status", "--porcelain", "--untracked-files=all", cwd=folder)
        if not result.ok:
            return []
        changes = []
        for line in result.lines():
            code, _, rest = line[:2], line[2:3], line[3:]
            path = rest.strip()
            old = ""
            if " -> " in path:  # a rename: "old -> new"
                old, path = path.split(" -> ", 1)
            changes.append({"code": code, "path": path.strip('"'), "old": old.strip('"'), "kind": _kind(code)})
        return changes

    def changed_files(self, folder) -> list[str]:
        return [change["path"] for change in self.status(folder)]

    def commit_all(self, folder, message: str) -> Result:
        """Save a checkpoint: everything in the folder, exactly as it is now."""
        added = self.run("add", "-A", cwd=folder)
        if not added.ok:
            return added
        return self.run("commit", "-m", message, cwd=folder)

    def log(self, folder, limit: int = 50) -> list[dict]:
        """The checkpoints, newest first."""
        fmt = "%H%x1f%h%x1f%an%x1f%aI%x1f%s%x1e"
        result = self.run("log", "--pretty=format:" + fmt, "-n", str(limit), cwd=folder)
        if not result.ok:
            return []
        entries = []
        for chunk in result.out.split("\x1e"):
            chunk = chunk.strip("\n")
            if not chunk:
                continue
            parts = chunk.split("\x1f")
            if len(parts) < 5:
                continue
            entries.append(
                {"sha": parts[0], "short": parts[1], "author": parts[2], "when": parts[3], "message": parts[4]}
            )
        return entries

    def count_checkpoints(self, folder) -> int:
        result = self.run("rev-list", "--count", "HEAD", cwd=folder)
        try:
            return int(result.out.strip())
        except ValueError:
            return 0

    def first_commit(self, folder) -> str:
        result = self.run("rev-list", "--max-parents=0", "HEAD", cwd=folder)
        return result.lines()[-1] if result.lines() else ""

    def restore_files(self, folder, sha: str) -> Result:
        """Put the files back the way they were at a checkpoint.

        Deliberately *not* a reset: files added since that checkpoint are left
        where they are, and the newer versions stay in the history. Nothing a
        person made is thrown away by pressing this.
        """
        if not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha or ""):
            return Result(("checkout",), 128, "", "That is not a version nanoGit recognises.")
        return self.run("checkout", sha, "--", ".", cwd=folder, timeout=180)

    def added_since(self, folder, sha: str) -> list[str]:
        """Files that appeared after a checkpoint — left alone by a restore."""
        result = self.run("diff", "--name-only", "--diff-filter=A", sha, "HEAD", cwd=folder)
        return result.lines() if result.ok else []

    def files_changed_by_restore(self, folder, sha: str) -> list[str]:
        result = self.run("diff", "--name-only", sha, cwd=folder)
        return result.lines() if result.ok else []

    def ignore_file(self, folder, patterns: list[str], create: bool = True) -> bool:
        """Add lines to .gitignore, keeping whatever was already there."""
        path = Path(folder) / ".gitignore"
        existing = ""
        if path.is_file():
            try:
                existing = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return False
        have = {line.strip() for line in existing.splitlines()}
        wanted = [p for p in patterns if p and p not in have]
        if not wanted:
            return False
        if not existing and not create:
            return False
        block = ""
        if existing and not existing.endswith("\n"):
            block += "\n"
        block += "\n".join(wanted) + "\n"
        try:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(block)
        except OSError:
            return False
        return True

    def remote(self, folder) -> str:
        return self.run("remote", "get-url", "origin", cwd=folder).out.strip()

    def unpushed(self, folder) -> int:
        """How many checkpoints have not been sent up yet."""
        if not self.remote(folder):
            return 0
        result = self.run("rev-list", "--count", "@{u}..HEAD", cwd=folder)
        try:
            return int(result.out.strip())
        except ValueError:
            return 0

    def track_remote(self, folder, url: str) -> Result:
        existing = self.remote(folder)
        if existing:
            return self.run("remote", "set-url", "origin", url, cwd=folder)
        return self.run("remote", "add", "origin", url, cwd=folder)

    # -- looking inside checkpoints ---------------------------------------
    def files_at(self, folder, sha: str) -> list[str]:
        """Every file the history knows about at a checkpoint."""
        if not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha or ""):
            return []
        result = self.run("ls-tree", "-r", "--name-only", "-z", sha, cwd=folder)
        if not result.ok:
            return []
        return sorted(part for part in result.out.split("\0") if part)

    def file_at(self, folder, sha: str, path: str) -> tuple:
        """One file's content at a checkpoint, byte for byte (binary-safe).

        Kept out of run() on purpose: text decoding would corrupt a JPEG or a
        spreadsheet, so this one bypasses it and hands back raw bytes.
        """
        command = [self.exe, "-c", "core.quotepath=false", "-c", "color.ui=false",
                   "show", "%s:%s" % (sha, path)]
        try:
            done = subprocess.run(
                command,
                cwd=str(folder) if folder else None,
                env=_env(),
                capture_output=True,
                timeout=DEFAULT_TIMEOUT,
                shell=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False, b""
        if done.returncode != 0:
            return False, done.stderr or b""
        return True, done.stdout

    def change_list(self, folder, sha: str) -> list:
        """What one checkpoint changed: each file, what happened to it, and
        how many lines came and went. The root checkpoint counts too, thanks
        to ``--root`` — its 'changes' are simply everything it added."""
        if not re.fullmatch(r"[0-9a-fA-F]{4,40}", sha or ""):
            return []
        status = self.run("diff-tree", "--root", "--no-commit-id", "--name-status", "-r", "-z", "-M", sha, cwd=folder)
        counts = self.run("diff-tree", "--root", "--no-commit-id", "--numstat", "-r", "-z", "-M", sha, cwd=folder)
        items = {}
        if status.ok:
            # With -z the records are: LETTER\0 path\0 … (renames: R100\0 old\0 new\0)
            tokens = [token for token in status.out.split("\0") if token]
            index = 0
            while index < len(tokens):
                code = tokens[index]
                index += 1
                letter = code[:1].upper()
                if letter in ("R", "C"):
                    if index + 1 >= len(tokens):
                        break
                    old, path = tokens[index], tokens[index + 1]
                    index += 2
                    items[path] = {"path": path, "old": old, "kind": "renamed"}
                else:
                    if index >= len(tokens):
                        break
                    path = tokens[index]
                    index += 1
                    kind = {"A": "new", "D": "gone", "M": "changed", "T": "changed"}.get(letter, "changed")
                    items[path] = {"path": path, "old": "", "kind": kind}
        if counts.ok:
            # With -z the records are: ADDED\tDELETED\tPATH\0 ("-" counts are binary
            # files). A rename's PATH comes back empty, followed by old\0new instead.
            tokens = counts.out.split("\0")
            index = 0
            while index < len(tokens):
                record = tokens[index].strip("\n")
                index += 1
                parts = record.split("\t")
                if len(parts) < 3:
                    continue
                added, deleted, path = parts[0], parts[1], "\t".join(parts[2:])
                if not path:
                    # Rename record: the old and new names occupy the next two tokens.
                    if index + 1 >= len(tokens):
                        continue
                    old, path = tokens[index], tokens[index + 1]
                    index += 2
                    if not path:
                        continue
                item = items.setdefault(path, {"path": path, "old": "", "kind": "changed"})
                item["added"] = int(added) if added.isdigit() else None
                item["deleted"] = int(deleted) if deleted.isdigit() else None
        return sorted(items.values(), key=lambda item: item["path"])

    # -- the gentle undo ---------------------------------------------------
    def reset_soft(self, folder) -> Result:
        """Un-save the last checkpoint. The files themselves stay exactly where
        they are — this only moves the history's bookmark back by one."""
        return self.run("reset", "--soft", "HEAD~1", cwd=folder)

    # -- one file with the whole history in it ------------------------------
    def bundle(self, folder, target) -> Result:
        """Write the whole history as one file, using git's own bundle format."""
        return self.run("bundle", "create", str(target), "--all", cwd=folder, timeout=180)

    def bundle_verify(self, folder, target) -> Result:
        """Open the file back up and check it really holds the history."""
        return self.run("bundle", "verify", str(target), cwd=folder, timeout=120)

    # -- the mark git leaves when a save was stopped halfway ----------------
    def interrupted_lock(self, folder) -> str:
        """The lock file git leaves behind when it was stopped mid-save, or ''."""
        path = Path(folder) / ".git" / "index.lock"
        try:
            return str(path) if path.is_file() else ""
        except OSError:
            return ""

    def clear_interrupted_lock(self, folder) -> bool:
        """Remove that lock. Only the lock itself is touched — never a file."""
        path = Path(folder) / ".git" / "index.lock"
        try:
            path.unlink()
            return True
        except OSError:
            return False

    # -- talking to the online copy ----------------------------------------
    def fetch(self, folder) -> Result:
        """Ask the online copy what it knows, without changing any files."""
        return self.run("fetch", "origin", cwd=folder, timeout=PUSH_TIMEOUT)

    def incoming(self, folder) -> int:
        """How many checkpoints are waiting online to be brought down."""
        result = self.run("rev-list", "--count", "HEAD..@{u}", cwd=folder)
        try:
            return int(result.out.strip())
        except ValueError:
            return 0

    def merge_ff_only(self, folder) -> Result:
        """Bring down what is waiting online — only when it applies cleanly.

        ``--ff-only`` makes git stop rather than invent a merge, which is the
        right refusal for somebody who was never taught what a merge conflict is.
        """
        return self.run("merge", "--ff-only", "@{u}", cwd=folder, timeout=180)


def _kind(code: str) -> str:
    """Turn git's two-letter status into a word the page can print."""
    if code.strip() == "??":
        return "new"
    if "D" in code:
        return "gone"
    if "R" in code:
        return "renamed"
    if "A" in code:
        return "new"
    if "M" in code:
        return "changed"
    return "changed"


def gh() -> str | None:
    """The path to the GitHub command line tool, if it is installed."""
    found = shutil.which("gh")
    if found:
        return found
    for candidate in [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GitHub CLI" / "gh.exe",
        Path("/usr/local/bin/gh"),
        Path("/opt/homebrew/bin/gh"),
    ]:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def gh_account() -> dict:
    """Who the GitHub tool is logged in as — or why it cannot tell us."""
    exe = gh()
    if not exe:
        return {"installed": False, "logged_in": False, "account": "", "note": "not installed"}
    try:
        done = subprocess.run(
            [exe, "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=_env_no_prompt(),
            shell=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"installed": True, "logged_in": False, "account": "", "note": str(exc)}
    if done.returncode == 0 and done.stdout.strip():
        return {"installed": True, "logged_in": True, "account": done.stdout.strip(), "note": "ready"}
    return {
        "installed": True,
        "logged_in": False,
        "account": "",
        "note": "installed but not signed in",
    }


def _env_no_prompt() -> dict:
    env = _env()
    env["GH_PROMPT_DISABLED"] = "1"
    env["GH_NO_UPDATE_NOTIFIER"] = "1"
    return env


def gh_publish(folder, name: str, private: bool, description: str = "") -> Result:
    """Create the repository online and send the folder up in one go."""
    exe = gh()
    if not exe:
        return Result(("gh",), 127, "", "The GitHub tool (gh) is not installed on this computer.")
    args = [
        exe,
        "repo",
        "create",
        name,
        "--source",
        str(folder),
        "--push",
        "--private" if private else "--public",
    ]
    if description:
        args += ["--description", description]
    try:
        done = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PUSH_TIMEOUT,
            env=_env_no_prompt(),
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return Result(("gh", "repo", "create"), 124, "", "Uploading took too long and was stopped.", timed_out=True)
    except OSError as exc:
        return Result(("gh", "repo", "create"), 127, "", str(exc))
    return Result(("gh", "repo", "create"), done.returncode, done.stdout or "", done.stderr or "")


def manual_commands(folder, name: str, private: bool) -> str:
    """The exact lines to paste, for anybody who would rather do it by hand."""
    location = str(folder)
    lines = [
        'cd "%s"' % location,
        "git remote add origin https://github.com/<your-name>/%s.git" % name,
        "git branch -M main",
        "git push -u origin main",
    ]
    if private:
        lines.insert(0, "# on github.com, create a *private* repository called " + name)
    else:
        lines.insert(0, "# on github.com, create a repository called " + name)
    return "\n".join(lines)
