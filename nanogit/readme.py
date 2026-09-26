"""Writing a README for a folder that never had one.

The output of this file is meant to be edited by the person who owns the folder.
So it says what can be seen, admits what it does not know, and signs itself —
a README that pretends to be written by a human is worse than no README.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from . import APP_NAME, __version__
from .survey import human_size

# Left out of every folder nanoGit looks after. The first group is junk that
# operating systems and editors scatter, the second is junk Python leaves.
BASE_IGNORES = [
    "# Junk your computer and your editor leave lying around.",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "*.swp",
    "*.tmp",
    ".idea/",
    ".vscode/",
    "# Junk Python leaves when it runs.",
    "__pycache__/",
    "*.py[cod]",
    ".venv/",
    "venv/",
]


def how_to_run(survey: dict) -> str:
    """The one section a stranger needs — only when it can be stated honestly.

    Every branch here is decided by a file that was actually seen in the folder,
    so the instructions are never a guess dressed up as knowledge.
    """
    names = set(survey.get("markers") or ()) | set(survey.get("root_names") or ())
    kind = (survey.get("kind") or "").lower()
    if "package.json" in names:
        return (
            "You will need Node.js (from [nodejs.org](https://nodejs.org)). Then, in this folder:\n\n"
            "```bash\nnpm install\nnpm start\n```\n"
        )
    if "requirements.txt" in names:
        return (
            "You will need Python 3.9 or newer (from [python.org](https://www.python.org/downloads/)). "
            "Then, in this folder:\n\n"
            "```bash\npip install -r requirements.txt\n```\n"
        )
    if "pyproject.toml" in names:
        return (
            "You will need Python 3.9 or newer. Then, in this folder:\n\n"
            "```bash\npip install -e .\n```\n"
        )
    if "Cargo.toml" in names:
        return "You will need Rust (from [rustup.rs](https://rustup.rs)). Then run `cargo run` in this folder.\n"
    if "go.mod" in names:
        return "You will need Go (from [go.dev](https://go.dev/dl/)). Then run `go run .` in this folder.\n"
    if "index.html" in names:
        return "Double-click `index.html` — it opens in your browser. There is nothing to install.\n"
    if "a website" in kind or "html" in kind:
        return "Open the `.html` file in your browser. There is nothing to install.\n"
    # Honest by design: an unrecognised folder gets an apology, not a guess.
    return "*(nanoGit could not tell how this one runs, so this line is yours to write.)*\n"


def build(survey: dict, name: str, description: str) -> str:
    """The README text."""
    today = _dt.date.today().isoformat()
    title = name or survey.get("title") or "This folder"
    lines = ["# %s" % title, ""]

    if description:
        lines += [description.strip(), ""]
    else:
        lines += [
            "*(One line about what this is. nanoGit left this here so there is somewhere to write it.)*",
            "",
        ]

    lines += ["## What is in here", ""]
    lines.append("- %s files, %s in total" % ("{:,}".format(survey["file_count"]), survey["total_size_text"]))
    if survey.get("kind"):
        lines.append("- Looks like %s (%s)" % (survey["kind"], survey.get("because", "as far as I can tell")))
    breakdown = [item for item in survey.get("breakdown", []) if item["what"] != "other"]
    if breakdown:
        written = ", ".join("%d %s" % (item["count"], item["what"]) for item in breakdown[:4])
        lines.append("- Mostly %s" % written)
    biggest = survey.get("biggest") or []
    if biggest:
        lines.append("- Largest file: `%s` (%s)" % (biggest[0]["path"], biggest[0]["size_text"]))
    lines.append("")

    run = how_to_run(survey)
    # how_to_run always answers with something — real steps or the apology.
    lines += ["## How to use it", "", how_to_run(survey), ""]

    if survey.get("secrets"):
        lines += ["## Things deliberately left out", ""]
        lines.append(
            "These files are on your computer but are **not** in the history, because they look private:"
        )
        lines.append("")
        for item in survey["secrets"]:
            lines.append("- `%s` — %s" % (item["path"], item["what"]))
        lines.append("")
        lines.append("They are listed in `.gitignore`. If one of them turns out to be harmless, delete its line.")
        lines.append("")

    lines += [
        "## Versions",
        "",
        "This folder is tracked, which means every time somebody presses **Save a checkpoint**",
        "in nanoGit, the folder is copied into the history first. Nothing is ever lost, and you can",
        "go back to any checkpoint.",
        "",
        "---",
        "",
        "*This README was written by [%s](https://github.com/Agarwalrishu13/nanogit) %s on %s, from what it could see"
        " in the folder. It is a starting point, not a description — edit it, it is yours.*"
        % (APP_NAME, __version__, today),
        "",
    ]
    return "\n".join(lines)


def write(folder, survey: dict, name: str, description: str, force: bool = False) -> dict:
    """Put the README in the folder, unless one is already there."""
    target = Path(folder) / "README.md"
    if target.exists() and not force:
        return {"written": False, "path": str(target), "why": "There is already a README.md, so it was left alone."}
    try:
        # Written with Unix line endings on purpose: this file is going to GitHub,
        # where everything else is read by people on Linux and macOS.
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(build(survey, name, description))
    except OSError as exc:
        return {"written": False, "path": str(target), "why": "Could not write it (%s)." % exc}
    return {"written": True, "path": str(target), "why": "A README.md was written for you to edit."}
