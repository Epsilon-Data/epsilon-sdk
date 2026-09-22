"""
Naming and recognising Epsilon project folders.

The project registry itself lives in the workbench (sdk/workbench/service.py),
which is its only writer and serialises changes with a file lock.
"""
import os
import re


def slug(name: str) -> str:
    """A stable, readable id derived from the name."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return base or "project"


def looks_like_project(path: str) -> bool:
    """Whether a directory is an Epsilon project rather than any folder.

    `epsilon init` leaves both of these behind. Requiring one of them keeps
    the list to real work: starting the workspace in a home directory or a
    scratch folder should not quietly add an entry to it.
    """
    full = os.path.abspath(os.path.expanduser(path or "."))
    return (os.path.exists(os.path.join(full, "generated", "data.csv"))
            or os.path.exists(os.path.join(full, "project.yml")))
