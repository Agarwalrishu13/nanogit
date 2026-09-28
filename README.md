<div align="center">

# nanoGit

**Your folder, kept safe — and put online — without learning git.**

git is the best tool there is for never losing work. It is also famously
unreadable. nanoGit keeps the useful half and translates the rest: it looks at
any folder you point at, says what is inside in plain words, and gives you
buttons with ordinary names — **Save a checkpoint**, **Go back to this
version**, **Put it online**.

[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.9+-58a6ff.svg)]()
[![dependencies](https://img.shields.io/badge/required%20deps-0-f0883e.svg)]()
[![tests](https://img.shields.io/badge/tests-284%20passing-3ddc97.svg)]()

</div>

---

> **Part of [the nano family](https://github.com/Agarwalrishu13/nano)** — eleven offline-first apps for people who do not code. This is the map of the whole project.


## What's new in 1.0

- **See what will be saved, before saving.** The checkpoint card shows the real
  changed lines of each text file — additions in green, removals in red —
  before you press the button. Looking changes nothing.
- **Bring back a file.** Deleted it, or broke it since the last save? Open any
  checkpoint, pick the file marked *gone now*, and it comes back byte for byte.
- **Take back the last checkpoint.** The newest checkpoint is un-saved, the
  work stays on disk. The first checkpoint is the floor, always.
- **Copy the history to a file.** The whole history as one `.bundle` — for a
  USB stick or a second computer, verified to open, no account needed.
- **Get the latest version.** One press brings down what arrived online from
  another computer, with three kind refusals when it would not be clean.
- **Save by itself.** Optional hourly or daily checkpoints, only when something
  changed. Plus a gentle nudge when a checkpoint is overdue.
- **Tidy it up.** One click clears the mark git leaves when a save is stopped
  halfway — and only that mark.
- The page is lighter and calmer throughout. Full story in [CHANGELOG.md](CHANGELOG.md).

## What this is, in one paragraph

Everything nanoGit does, it says in sentences a person can read: *"Saved a
checkpoint with 3 files in it"*, *"The folder is empty, so the first checkpoint
just holds the README and the .gitignore"*, *"This file looks private, so it
stays on your computer"*. Underneath it runs real git — the git that is
probably already on your computer — but nobody has to learn that, and nothing
is ever deleted, force-pushed or thrown away. When it does not know something,
it says so instead of guessing: a folder it cannot identify gets a README whose
"How to use it" section reads *"nanoGit could not tell how this one runs, so
this line is yours to write."*

---

## Use it

1. Install Python if you do not have it — [python.org/downloads](https://www.python.org/downloads/).
2. Download this repo and unzip it.
3. **Windows:** double-click `run.bat`. **macOS / Linux:** `./run.sh`.
4. Your browser opens at `http://127.0.0.1:8778`.

<details>
<summary>Prefer the command line? (you do not need to)</summary>

```bash
python start.py                        # start and open the browser
python -m nanogit doctor               # say what this computer has, and stop
python -m nanogit --port 9000 --no-browser
```

</details>

---

## What you can do with it

| button | what it really does | what could go wrong |
|---|---|---|
| **Point me at a folder** | A native folder window, an in-page browser, or drag a folder in — nanoGit finds it by name. | Nothing. Nothing is read yet beyond counting files. |
| **Keep this folder safe** | Writes a README and a .gitignore in plain words, starts the history, saves a first checkpoint. | If the folder lives inside another tracked folder, it refuses and explains why. |
| **Save a checkpoint** | Everything in the folder, exactly as it is now, under the words you type. Your words are kept as you typed them. | Saving with nothing new is harmless — it says so. |
| **Save by itself** | Optional: a checkpoint once an hour or once a day, while the app is open — only if something changed. | It never starts tracking a folder you have not asked about. |
| **Look inside** | Shows every file a checkpoint holds, and what that checkpoint changed, in words: *"3 files: 1 new, 2 changed · +45 −12"*. | Nothing. It only reads. |
| **Bring it back** | Copies one file out of a checkpoint — deleted, broken, replaced by accident — byte for byte. | Unsaved work is checkpointed first, so even this cannot lose anything. |
| **Take back the last checkpoint** | Un-saves the newest checkpoint. The work in it stays on disk as unsaved changes. | The first checkpoint is the floor; it always stays. |
| **Go back to this version** | The folder becomes that checkpoint again. Nothing is lost: newer versions stay in the history. | Nothing is deleted, ever. |
| **Copy the history to a file** | The whole history as one `.bundle` file — for a USB stick or a second computer. Opens with ordinary git. | It refuses to put the copy inside the folder it is copying. |
| **Things to leave out** | Files that look private (keys, `.env`, databases) stay on your computer, with an explanation for each. | They are listed *before* anything goes online, not after. |
| **Put it online** | Makes a **private** GitHub repository and sends the folder up, using the `gh` tool if you have it. Big files over GitHub's limit are caught *before* upload, not after. | Without `gh` it says exactly where to get it, and keeping the folder safe still works. |
| **Get the latest version** | Brings down checkpoints waiting online — after three kind refusals: not online yet, unsaved work in the folder, or both sides moved at once. | In each refusal everything is left exactly as it was, with a sentence saying why. |
| **Tidy it up** | When a save is interrupted mid-way, git refuses to work until its "still working" note is removed. This button removes just the note. | No file of yours is touched — only git's own note. |

### The words it uses instead of git's

| nanoGit says | git calls it |
|---|---|
| Keep this folder safe | init |
| Save a checkpoint | add + commit |
| Checkpoint | commit |
| History | repository |
| Go back to this version | checkout |
| Bring it back | show *sha*:*path* |
| Take back the last checkpoint | reset --soft |
| Get the latest version | fetch + merge --ff-only |
| Copy the history to a file | bundle |
| Put it online | push |
| Things to leave out | .gitignore |

---

## Things it does that you would not expect from a toy

- **It tells you what a folder is before touching it.** *"a folder of
  documents"*, *"a website"*, *"a Python project"* — plus the biggest files and
  the things that look private.
- **It writes the README for you.** Size, contents, how to run it — and it
  never overwrites a README that is already there.
- **It is hermetic on purpose.** A checkpoint is signed with a name you gave,
  not with whatever happens to be in some global config.
- **A folder named `target` or `build` is still findable.** Build-output names
  are skipped when *looking*, never when they are exactly what you asked for.
- **Publishing is private by default**, and it stops to tell you what looks
  private before anything is uploaded — never after.
- **A deleted file is a solvable problem.** *Look inside* a checkpoint, pick
  the file marked *gone now*, press *Bring it back*. It comes back byte for
  byte — and your current work is checkpointed first, because this app does
  not know how to lose things.
- **The history fits in your pocket.** *Copy the history to a file* writes the
  whole thing as one `.bundle`. No account, no internet — and if you ever need
  it back, ordinary git clones it.

---

## What it does not do, honestly

- **It never deletes anything.** There is no code path that removes your files,
  and no force-push, no hard reset, no rewrite of history.
- **It does not replace git.** Programmers can open the same folder with git
  and everything nanoGit saved is a normal repository.
- **"Put it online" needs the `gh` tool** (free, from
  [cli.github.com](https://cli.github.com)). Without it, everything else works
  and the button says what to install.
- **It runs on your computer only.** Nothing is uploaded except when you press
  *Put it online*, to the GitHub account you chose.

---

## Where your settings live

```
~/.nanogit/
  settings.json     the name checkpoints are signed with, and what you asked to remember
```

The folders themselves are never moved or copied. Delete that folder and
nanoGit forgets everything; the histories it made keep working with ordinary git.

---

## The rest of the family

| app | what it is for |
|---|---|
| 🧭 [nanoHome](https://github.com/Agarwalrishu13/nanohome) | one front door for every nano app on this computer |
| 🧠 [nanoLaama](https://github.com/Agarwalrishu13/nanolaama) | talk to an AI on your own computer, offline |
| 📚 [nanoDoc](https://github.com/Agarwalrishu13/nanodoc) | drop in a document, ask it anything |
| 📊 [nanoLearn](https://github.com/Agarwalrishu13/nanolearn) | drop a spreadsheet, get an answer machine |
| 🔊 [nanoSay](https://github.com/Agarwalrishu13/nanosay) | have anything read out loud |
| 🧲 [nanoPick](https://github.com/Agarwalrishu13/nanopick) | find your files by saying what you remember |
| 🎵 [nanoTune](https://github.com/Agarwalrishu13/nanotune) | your music, one page, no account |
| 🧰 [nanoWrap](https://github.com/Agarwalrishu13/nanowrap) | the best-known programs, with ready-made buttons |
| ⌨️ [nanoShell](https://github.com/Agarwalrishu13/nanoshell) | any program at all, with words instead of flags |
| 🗂 [**nanoGit**](https://github.com/Agarwalrishu13/nanogit) | your folder, kept safe without learning git — *this repo* |
| 🖥 [nanoDesk](https://github.com/Agarwalrishu13/nanodesk) | every nano-style app you have, one click away |
| 🃏 [nonoForge](https://github.com/Agarwalrishu13/nonoforge) | pick a card, press one button, you have an app |

And underneath them, for people who want to see the gears: [nanollama.c](https://github.com/Agarwalrishu13/nanollama.c) (the C engine), [nanobrain](https://github.com/Agarwalrishu13/nanobrain) (training from scratch), [nanoforge](https://github.com/Agarwalrishu13/nanoforge) (the model studio) and [nanorl](https://github.com/Agarwalrishu13/nanorl) (alignment).

The map of the whole project — what each app is for, and how they fit together — lives in [the nano family](https://github.com/Agarwalrishu13/nano).
MIT license. Made for people who do not write code, by someone who does.
