"""
The projects a researcher has on this machine.

A project is a name, a description of what the researcher is trying to find
out, and a path to a directory `epsilon init` has prepared. The registry lives
in the researcher's home rather than in any project, so the workspace can open
without being started inside one.

Nothing here leaves the machine, and nothing here is required: a directory
initialised by `epsilon init` still works when opened directly.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sdk.config import CREDENTIALS_DIR

REGISTRY_FILE = "projects.json"
REGISTRY_VERSION = 1


class ProjectError(Exception):
    """A project cannot be registered or opened."""


@dataclass
class Project:
    id: str
    name: str
    path: str
    description: str = ""
    created: str = ""
    opened: str = ""

    @property
    def exists(self) -> bool:
        return os.path.isdir(self.path)

    @property
    def initialised(self) -> bool:
        """Whether `epsilon init` has produced a projection to measure."""
        return os.path.exists(os.path.join(self.path, "generated", "data.csv"))

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "Project":
        return cls(
            id=raw.get("id") or "",
            name=raw.get("name") or "",
            path=raw.get("path") or "",
            description=raw.get("description") or "",
            created=raw.get("created") or "",
            opened=raw.get("opened") or "",
        )


def registry_path() -> str:
    return os.path.join(os.path.expanduser("~"), CREDENTIALS_DIR, REGISTRY_FILE)


def slug(name: str) -> str:
    """A stable, readable id derived from the name."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return base or "project"


def load() -> List[Project]:
    path = registry_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (ValueError, OSError):
        # A corrupt registry must not stop the researcher working; the
        # directories it points at are the real state.
        return []
    if not isinstance(raw, dict):
        return []
    return [Project.from_json(p) for p in (raw.get("projects") or [])
            if isinstance(p, dict)]


def save(projects: List[Project]) -> str:
    directory = os.path.dirname(registry_path())
    if not os.path.isdir(directory):
        os.makedirs(directory, mode=0o700)
    payload = {"version": REGISTRY_VERSION,
               "projects": [p.to_json() for p in projects]}
    path = registry_path()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def get(project_id: str) -> Optional[Project]:
    for project in load():
        if project.id == project_id:
            return project
    return None


def by_path(path: str) -> Optional[Project]:
    target = os.path.abspath(os.path.expanduser(path))
    for project in load():
        if os.path.abspath(project.path) == target:
            return project
    return None


def add(name: str, path: str, description: str = "") -> Project:
    """Register a directory as a project.

    The path must exist. It need not be initialised yet -- a researcher can
    register a folder and run `epsilon init` into it afterwards.
    """
    full = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(full):
        raise ProjectError("{0} is not a directory".format(path))

    existing = by_path(full)
    if existing is not None:
        raise ProjectError(
            "{0} is already registered as '{1}'".format(full, existing.name))

    projects = load()
    taken = set(p.id for p in projects)
    base = slug(name)
    identifier, n = base, 2
    while identifier in taken:
        identifier, n = "{0}-{1}".format(base, n), n + 1

    now = datetime.now().isoformat(timespec="seconds")
    project = Project(id=identifier, name=name.strip() or identifier, path=full,
                      description=description.strip(), created=now, opened=now)
    projects.append(project)
    save(projects)
    return project


def touch(project_id: str) -> Optional[Project]:
    """Record that a project was opened, so the list can lead with recent work."""
    projects = load()
    found = None
    for project in projects:
        if project.id == project_id:
            project.opened = datetime.now().isoformat(timespec="seconds")
            found = project
    if found is not None:
        save(projects)
    return found


def remove(project_id: str) -> bool:
    """Forget a project. The directory and its files are left alone."""
    projects = load()
    kept = [p for p in projects if p.id != project_id]
    if len(kept) == len(projects):
        return False
    save(kept)
    return True


def recent() -> List[Project]:
    """Registered projects, most recently opened first."""
    return sorted(load(), key=lambda p: p.opened or p.created, reverse=True)
