"""Looking at a folder and describing it honestly.

Two jobs live here.

The first is *explaining*: given a folder, work out what kind of thing it is,
how big it is, what is in it, and — the part that matters — whether anything in
it should not be put on the internet. All of this is reading, never writing.

The second is *finding*: browsers will not tell a page where a dragged folder
lives on the disk, only what it is called. Since this app runs on the same
computer as the person using it, the folder can be found by name instead, which
is what makes dragging a real folder work.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MAX_FILES = 40000
BIG_WARN_BYTES = 25 * 1024 * 1024
BIG_REFUSE_BYTES = 100 * 1024 * 1024

# Folders that are never interesting and are often enormous.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    ".gradle",
    ".cache",
    "$RECYCLE.BIN",
    "System Volume Information",
}

# Hidden folders are skipped when walking — except these, which is exactly where
# a password tends to be sitting.
HIDDEN_BUT_INTERESTING = {".aws", ".ssh", ".gnupg", ".config"}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".ps1", ".sql",
    ".xml", ".csv", ".env", ".properties", ".gradle", ".tf", ".vue", ".svelte", ".r", ".m",
}

# Files whose *name* alone means "do not put this online".
SECRET_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development", ".env.backup",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "credentials", "credentials.json", "credentials.yml", "credentials.yaml",
    "secrets.json", "secrets.yml", "secrets.yaml", "secrets.txt",
    "passwords.txt", "passwords.csv", "password.txt",
    ".netrc", ".npmrc", ".pypirc", ".htpasswd", ".pgpass",
    "terraform.tfstate", "terraform.tfstate.backup",
    "keystore.jks", "kubeconfig",
}

SECRET_EXTENSIONS = {".pem", ".key", ".pfx", ".p12", ".jks", ".keystore", ".ppk", ".ovpn", ".kdbx"}

# A short, deliberate list. Anything longer starts reporting false alarms, and a
# warning that fires on ordinary files is a warning nobody reads.
SECRET_CONTENT = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key",
     "This is a private key. Anyone who has it can pretend to be you."),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an Amazon access key",
     "This is an Amazon Web Services key. It can spend your money."),
    (re.compile(r"\bsk-[A-Za-z0-9]{24,}\b"), "an API key",
     "This looks like a paid API key. It is billed to whoever owns it."),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"), "a GitHub token",
     "This GitHub token can read and write your account."),
    (re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']"), "a password",
     "A password is written in this file in plain sight."),
    (re.compile(r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']"),
     "an API key", "A key is written in this file in plain sight."),
]

LANGUAGE_BY_EXTENSION = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".jsx": "JavaScript", ".java": "Java", ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".hpp": "C++", ".cs": "C#", ".go": "Go", ".rs": "Rust",
    ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".kt": "Kotlin", ".m": "Objective-C",
    ".r": "R", ".jl": "Julia", ".lua": "Lua", ".sh": "shell scripts", ".ps1": "PowerShell",
    ".bat": "Windows batch files", ".sql": "SQL", ".ino": "Arduino", ".v": "Verilog",
}

DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".odt", ".rtf", ".epub", ".txt", ".md"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".webp", ".raw", ".svg"}
MEDIA_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".flac", ".m4a", ".ogg"}

# Marker files, in the order that gives the most useful answer.
PROJECT_MARKERS = [
    ("package.json", "a JavaScript or Node project", "JavaScript"),
    ("pyproject.toml", "a Python project", "Python"),
    ("requirements.txt", "a Python project", "Python"),
    ("setup.py", "a Python project", "Python"),
    ("Cargo.toml", "a Rust project", "Rust"),
    ("go.mod", "a Go project", "Go"),
    ("pom.xml", "a Java project", "Java"),
    ("build.gradle", "an Android or Java project", "Java"),
    ("composer.json", "a PHP project", "PHP"),
    ("Gemfile", "a Ruby project", "Ruby"),
    ("pubspec.yaml", "a Flutter project", "Dart"),
    ("CMakeLists.txt", "a C or C++ project", "C++"),
    ("Makefile", "a project that is built with make", "make"),
]


def human_size(count: int) -> str:
    """Bytes as a short, readable string."""
    size = float(count)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "bytes":
                return "%d bytes" % int(size)
            return ("%.1f %s" % (size, unit)) if size < 100 else ("%.0f %s" % (size, unit))
        size /= 1024
    return "%.0f TB" % size


def nice_title(folder) -> str:
    """A folder name turned into something you would put at the top of a page."""
    stem = Path(folder).name
    for separator in ("_", "-", "."):
        stem = stem.replace(separator, " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem:
        return "My folder"
    if stem.islower() or stem.isupper():
        stem = stem.title()
    return stem


def slugify(text: str) -> str:
    """A name GitHub will accept."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._")
    return (cleaned or "my-project")[:100]


# --------------------------------------------------------------------------
# Walking a folder
# --------------------------------------------------------------------------
def _walk(folder, limit: int = MAX_FILES):
    """Yield (relative path, size) for every file, skipping the usual swamps."""
    seen = 0
    for root, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and (not d.startswith(".") or d in HIDDEN_BUT_INTERESTING)
        ]
        for name in files:
            if name in SKIP_DIRS or name.startswith(".DS_Store"):
                continue
            full = os.path.join(root, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            seen += 1
            if seen > limit:
                return
            yield os.path.relpath(full, folder), size


def _read_head(path, limit: int = 4096) -> str:
    try:
        with open(path, "rb") as handle:
            raw = handle.read(limit)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def describe_kind(folder, extensions: dict, names: set) -> dict:
    """What kind of thing is this folder? Answered without opening anything."""
    for marker, description, language in PROJECT_MARKERS:
        if marker in names:
            return {"kind": description, "language": language, "because": marker}
    if any(n.endswith((".sln", ".csproj")) for n in names):
        return {"kind": "a .NET project", "language": "C#", "because": "a .sln or .csproj file"}
    if "index.html" in names:
        return {"kind": "a website", "language": "HTML", "because": "an index.html file"}
    if any(n.lower().endswith(".ipynb") for n in names):
        return {"kind": "a set of notebooks", "language": "Python", "because": "a .ipynb notebook"}

    if extensions:
        language, count = max(extensions.items(), key=lambda pair: pair[1])
        share = count / max(1, sum(extensions.values()))
        # "mostly Python" describes code. A pile of documents or pictures is
        # not "mostly documents" to a person — it is a folder of documents,
        # which is the branch below.
        if share >= 0.5 and language not in ("other", "documents", "pictures", "audio/video"):
            return {
                "kind": "mostly %s" % language,
                "language": language,
                "because": "%d%% of the files are %s" % (round(share * 100), language),
            }
        # ``extensions`` is keyed by bucket name ("documents", "Python", …),
        # so the subset checks below compare bucket names — not file types.
        only = set(extensions)
        if only <= {"documents"}:
            return {"kind": "a folder of documents", "language": "", "because": "the file types inside"}
        if only <= {"pictures"}:
            return {"kind": "a folder of pictures", "language": "", "because": "the file types inside"}
        if only <= {"audio/video"}:
            return {"kind": "a folder of audio and video", "language": "", "because": "the file types inside"}
    return {"kind": "a folder of files", "language": "", "because": "what is inside it"}


def find_secrets(folder, paths: list[str]) -> list[dict]:
    """Files that should not be put on the internet, and why.

    Two passes: names that are always a bad idea, then a short content scan of
    small text files. The scan is capped so that a huge folder cannot make this
    slow, and it only ever reads the first 256 KB of a file.
    """
    found: dict[str, dict] = {}
    for relative in paths:
        name = Path(relative).name
        lowered = name.lower()
        suffix = Path(relative).suffix.lower()
        if lowered in SECRET_NAMES or suffix in SECRET_EXTENSIONS:
            found[relative] = {
                "path": relative,
                "what": "a file that usually holds a password or a key",
                "why": "\u201c%s\u201d is a file programs use to keep secrets. It should stay on your computer." % name,
            }
            continue
        if lowered.startswith("secret") or lowered.startswith("password"):
            found[relative] = {
                "path": relative,
                "what": "a file named like a secret",
                "why": "The name of this file suggests it holds something private.",
            }

    sniffed = 0
    budget = 8 * 1024 * 1024
    for relative in paths:
        if relative in found or sniffed > 400 or budget <= 0:
            continue
        suffix = Path(relative).suffix.lower()
        if suffix not in TEXT_EXTENSIONS:
            continue
        full = Path(folder) / relative
        try:
            if full.stat().st_size > 256 * 1024:
                continue
        except OSError:
            continue
        head = _read_head(full, 65536)
        budget -= len(head)
        sniffed += 1
        for pattern, what, why in SECRET_CONTENT:
            if pattern.search(head):
                found[relative] = {"path": relative, "what": what, "why": why}
                break
    return sorted(found.values(), key=lambda item: item["path"])


def suggest_ignores(secrets: list[dict], big: list[dict]) -> list[str]:
    """Lines for .gitignore, so the dangerous things are left out by default."""
    patterns = []
    for item in secrets:
        relative = item["path"]
        name = Path(relative).name
        if name.startswith(".env"):
            patterns.append(".env*")
        elif Path(relative).suffix.lower() in SECRET_EXTENSIONS:
            patterns.append("*" + Path(relative).suffix.lower())
        elif name in SECRET_NAMES:
            patterns.append(name)
        else:
            patterns.append(relative.replace("\\", "/"))
    for item in big:
        patterns.append(item["path"].replace("\\", "/"))
    return sorted(dict.fromkeys(patterns))


def survey(folder) -> dict:
    """Everything the page needs to describe a folder, in one call."""
    target = Path(folder)
    if not target.is_dir():
        return {"ok": False, "error": "There is no folder at %s" % folder}

    names: set[str] = set()
    root_names: list[str] = []
    extensions: dict[str, int] = {}
    paths: list[str] = []
    total = 0
    for relative, size in _walk(target):
        paths.append(relative)
        total += size
        name = Path(relative).name
        names.add(name)
        if os.sep not in relative and "/" not in relative:
            root_names.append(relative)
        suffix = Path(relative).suffix.lower()
        language = LANGUAGE_BY_EXTENSION.get(suffix)
        if language is None:
            if suffix in DOCUMENT_EXTENSIONS:
                language = "documents"
            elif suffix in IMAGE_EXTENSIONS:
                language = "pictures"
            elif suffix in MEDIA_EXTENSIONS:
                language = "audio/video"
            else:
                language = "other"
        extensions[language] = extensions.get(language, 0) + 1

    big = []
    for relative, size in _walk(target):
        if size >= BIG_WARN_BYTES:
            big.append({"path": relative, "size": size, "size_text": human_size(size), "blocking": size >= BIG_REFUSE_BYTES})
    big.sort(key=lambda item: -item["size"])

    secrets = find_secrets(target, paths)
    kind = describe_kind(target, extensions, names)

    top = sorted(extensions.items(), key=lambda pair: -pair[1])[:5]
    readme = ""
    for candidate in ("README.md", "readme.md", "README.txt", "README"):
        if candidate in names:
            readme = _read_head(target / candidate, 4096)
            break

    own_repo = (target / ".git").is_dir()
    inside_repo = _inside_other_repo(target)

    return {
        "ok": True,
        "path": str(target),
        "name": target.name,
        "title": nice_title(target),
        "slug": slugify(target.name),
        "description": _first_line(readme) or "",
        "file_count": len(paths),
        "total_size": total,
        "total_size_text": human_size(total),
        "truncated": len(paths) >= MAX_FILES,
        "kind": kind["kind"],
        "language": kind["language"],
        "because": kind["because"],
        "markers": sorted(
            [marker for marker, _, _ in PROJECT_MARKERS if marker in names]
            + [name for name in names if name.endswith((".sln", ".csproj"))]
        ),
        "root_names": sorted(root_names)[:200],
        "breakdown": [{"what": what, "count": count} for what, count in top],
        "biggest": big[:8],
        "big_files": big,
        "secrets": secrets,
        "suggested_ignores": suggest_ignores(secrets, big),
        "has_readme": bool(readme),
        "has_license": any(n.lower().startswith("license") for n in names),
        "is_repo": own_repo,
        "inside_other_repo": inside_repo,
        "can_write": os.access(target, os.W_OK),
    }


def _inside_other_repo(folder) -> str:
    """The folder above this one that is tracked, if there is one."""
    current = Path(folder).resolve()
    for parent in list(current.parents)[:12]:
        if (parent / ".git").exists():
            return str(parent)
    return ""


def _first_line(readme: str) -> str:
    """The first useful sentence of a README, for a starting description."""
    for line in readme.splitlines():
        text = line.strip().lstrip("#").strip()
        if text and not text.startswith(("![", "[!", "<", "---", "===")):
            return text[:180]
    return ""


# --------------------------------------------------------------------------
# Finding a folder by name (what makes dragging a folder work)
# --------------------------------------------------------------------------
def search_roots() -> list[Path]:
    """The places a dragged folder is most likely to have come from."""
    home = Path.home()
    roots = [home]
    for name in ("Desktop", "Documents", "Downloads", "OneDrive", "Dropbox", "Projects", "source", "repos"):
        candidate = home / name
        if candidate.is_dir():
            roots.append(candidate)
            for inner in ("Desktop", "Documents", "Projects"):
                nested = candidate / inner
                if nested.is_dir():
                    roots.append(nested)
    return roots


_LOCAL_JUNK = {"$RECYCLE.BIN", "System Volume Information", "__pycache__"}


def locate_by_name(name: str, roots=None, max_depth: int = 3, limit: int = 3000) -> list[str]:
    """Every folder called `name` in the likely places, best guess first.

    A browser hands over a dragged folder's name and nothing else. Because the
    server is running on the same computer, the name is enough to find it.

    Build-output names ("build", "target", "venv"…) are not descended into
    unless they are exactly what was asked for — somebody's real folder can be
    called "target", and then it must be findable.
    """
    wanted = (name or "").strip().strip("/\\")
    if not wanted or wanted in (".", ".."):
        return []
    wanted_lower = wanted.lower()
    found: list[str] = []
    visited = 0
    for root in (roots if roots is not None else search_roots()):
        root = Path(root)
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            current, depth = stack.pop()
            visited += 1
            if visited > limit:
                break
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if entry.name.startswith(".") or entry.name in _LOCAL_JUNK:
                    continue
                if entry.name.lower() == wanted_lower:
                    found.append(entry.path)
                    continue
                if entry.name in SKIP_DIRS:
                    continue  # a build swamp, but not what was asked for
                if depth + 1 < max_depth:
                    stack.append((Path(entry.path), depth + 1))
        if found:
            break
    # An exact spelling match is a better guess than a case-insensitive one.
    found.sort(key=lambda path: (Path(path).name != wanted, len(Path(path).parts)))
    return found[:8]


# --------------------------------------------------------------------------
# The in-page folder picker
# --------------------------------------------------------------------------
def drives() -> list[str]:
    """The places to start from, on this operating system."""
    if sys.platform == "win32":
        letters = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
            candidate = "%s:\\" % letter
            if os.path.exists(candidate):
                letters.append(candidate)
        return letters or [str(Path.home())]
    roots = ["/"]
    home = str(Path.home())
    if home != "/":
        roots.insert(0, home)
    for extra in ("/Volumes", "/mnt", "/media"):
        if os.path.isdir(extra):
            roots.append(extra)
    return roots


def browse(path: str = "") -> dict:
    """The folders inside `path`, for the built-in picker."""
    if not path:
        return {
            "ok": True,
            "path": "",
            "parent": "",
            "places": drives(),
            "folders": [],
            "is_repo": False,
        }
    target = Path(path)
    if not target.is_dir():
        return {"ok": False, "error": "There is no folder at %s" % path}
    folders = []
    try:
        for entry in sorted(os.scandir(target), key=lambda e: e.name.lower()):
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name in SKIP_DIRS or entry.name.startswith((".", "$")):
                continue
            try:
                marked = "tracked" if (Path(entry.path) / ".git").is_dir() else ""
            except OSError:
                marked = ""
            folders.append({"name": entry.name, "path": entry.path, "mark": marked})
    except OSError as exc:
        return {"ok": False, "error": "Cannot read that folder (%s)" % exc}
    parent = str(target.parent) if target.parent != target else ""
    return {
        "ok": True,
        "path": str(target),
        "parent": parent,
        "places": drives(),
        "folders": folders[:400],
        "is_repo": (target / ".git").is_dir(),
    }
