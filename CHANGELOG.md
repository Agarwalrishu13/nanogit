# Changelog

All notable changes to nanoGit, in plain words. Dates are when the version was
finished, and every entry keeps the project's three rules: nothing is deleted,
nothing is force-pushed, and anything confusing is explained in a sentence.

## 1.0.0 — 2026-09-28

The "undo is safe" release. Checkpoint, go back and publish were already there;
this version adds the other half of the things people actually reach for, plus
a lighter, calmer page.

### New buttons

- **Look inside a checkpoint.** Every checkpoint now shows what it holds and,
  underneath, what it changed in words and line counts:
  *"3 files: 1 new, 2 changed · +45 −12"*. The first checkpoint counts too.
- **Bring back a file.** Deleted a file, or broke it since the last save? Any
  file in any checkpoint can be copied back out — byte for byte, so pictures
  come back as the same picture. Files the folder no longer has float to the
  top of the list, marked *gone now*. Unsaved work is checkpointed first, so
  this button cannot lose anything either.
- **Take back the last checkpoint** (`reset --soft` in git's words). The
  newest checkpoint is un-saved and its work stays on disk as unsaved changes.
  The first checkpoint is the floor and always stays.
- **Copy the history to a file.** The whole history as one `.bundle`, for a
  USB stick or a second computer — checked to open before it is reported done,
  with the one command to open it printed in words. Refuses to write the copy
  inside the folder it is copying. No account needed anywhere.
- **Get the latest version.** One press brings down checkpoints waiting on the
  online copy (`fetch` + `merge --ff-only`). Three kind refusals protect the
  innocent: not online yet, unsaved work in the folder, or both sides moved at
  once — each explains, and changes nothing.
- **Save by itself.** In Settings: a checkpoint once an hour or once a day
  while the app is open — only when something changed, only for the folder
  most recently looked after, never for an untracked one. Off unless asked.
- **Tidy it up.** When a save is interrupted mid-way, git leaves a lock behind
  and refuses everything until it is removed. The keep-safe page now notices
  and offers to remove exactly that — nothing else.
- **A gentle nudge.** The keep-safe page says when the last checkpoint was,
  and after a week with unsaved changes it suggests — kindly — that a
  checkpoint would be kind to your future self.

### Safer underneath

- Publishing to GitHub now checks for files over the 100 MB limit **before**
  anything is uploaded, and says exactly which file to leave out.
- Taking a checkpoint back, bringing a file back, and going back all refuse to
  run against a half-finished save, and point at the tidy-up button.
- "Bring it back" refuses paths that try to escape the folder (`../`), the
  same way "go back" refuses made-up versions.
- The first-save steps read the same whether or not a git identity was
  configured — a machine with none got a shorter story before.

### The page

- Re-lit: light paper-like surfaces in place of the dark cockpit, one blue
  accent, larger type, bigger click targets, visible focus rings. Same words,
  easier on tired eyes.
- History rows grew a second line saying what each checkpoint changed.
- `Ctrl+S` / `Cmd+S` on the keep-safe page saves a checkpoint, for the hands
  that reach for it by habit.

### The numbers

- 278 tests (was 218), all running against real git in real folders —
  including one that deletes a JPEG's bytes and proves they come back
  identical, and one that drives a whole "two computers" conversation through
  a bare repository standing in for GitHub.

## 0.1.0 — first public version

Folder survey in plain words, keep-this-folder-safe, checkpoints, going back,
things to leave out, private-by-default publishing with `gh`, the drag a
folder in flow, the seven words instead of git's, and the honest README.
