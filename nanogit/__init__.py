"""nanoGit — your folder, kept safe and put online, without learning git.

The whole application is this package plus a folder of static files. It has no
dependencies at all: the web server, the folder survey, the README writer and
the git plumbing are all the Python standard library and the ``git`` program
that is already on the computer.
"""

APP_NAME = "nanoGit"
__version__ = "1.0.0"
TAGLINE = "your folder, kept safe — and online — without learning git"

# Where the app looks for a folder somebody dragged in when the browser can
# only tell us its name and not where it lives.
__all__ = ["APP_NAME", "__version__", "TAGLINE"]
