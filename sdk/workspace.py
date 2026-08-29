"""
The state behind the interface: which project is open, and what is known
about it.

The server used to be bound to one directory at construction, which was true
when `epsilon start` could only be run from inside a project. A researcher
with several cohorts wants to move between them without restarting, so the
open project became something that changes while the server runs.

Profiling and suggesting both cost something -- a file read and a model call --
so each is done once per project and kept until the project is reopened.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sdk import projects as registry
from sdk import suggestions as suggest_mod
from sdk.profile import Profile, profile_project

# A seed is handed from the card that was clicked to the chat session that
# opens next. Anything older than this was abandoned.
SEED_TTL = 120.0


@dataclass
class Seed:
    """The context a new session starts from."""
    token: str
    project_id: str
    project_dir: str
    title: str
    question: str
    analysis: str = ""
    fields: Dict[str, str] = field(default_factory=dict)
    created: float = 0.0

    @property
    def expired(self) -> bool:
        return (time.time() - self.created) > SEED_TTL

    def brief(self) -> str:
        """The opening message, written as the researcher would ask it."""
        lines = [self.question]
        if self.analysis:
            named = ", ".join("{0}={1}".format(k, v)
                              for k, v in sorted(self.fields.items()))
            lines.append("")
            lines.append("(Start from the '{0}' analysis{1}. Check it is "
                         "available, generate it, run it, and tell me what it "
                         "shows.)".format(
                             self.analysis,
                             " on " + named if named else ""))
        return "\n".join(lines)

    def to_json(self) -> Dict[str, Any]:
        return {"token": self.token, "project_id": self.project_id,
                "project_dir": self.project_dir, "title": self.title,
                "question": self.question, "analysis": self.analysis,
                "fields": self.fields, "created": self.created}

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "Seed":
        return cls(token=raw.get("token", ""),
                   project_id=raw.get("project_id", ""),
                   project_dir=raw.get("project_dir", ""),
                   title=raw.get("title", ""),
                   question=raw.get("question", ""),
                   analysis=raw.get("analysis", ""),
                   fields=raw.get("fields") or {},
                   created=float(raw.get("created") or 0))


def token_from_referrer(referrer: str) -> str:
    """Pull the seed token out of the page URL that opened a session.

    Chainlit talks over a socket, so the page URL reaches the app only as the
    referrer of the handshake, and a browser is free to trim it. Returning ""
    is normal, not an error -- the caller falls back to the newest seed.
    """
    from urllib.parse import parse_qs, urlparse

    if not referrer or "seed=" not in referrer:
        return ""
    try:
        return (parse_qs(urlparse(referrer).query).get("seed") or [""])[0]
    except ValueError:
        return ""


def seed_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".epsilon_sdk", "handoff")


def put_seed(seed: Seed) -> str:
    """Leave a seed for the chat session that is about to open."""
    directory = seed_dir()
    if not os.path.isdir(directory):
        os.makedirs(directory, mode=0o700)
    path = os.path.join(directory, seed.token + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(seed.to_json(), fh)
    _sweep()
    return path


def take_seed(token: str = "") -> Optional[Seed]:
    """Claim a seed, by token if the URL survived, else the newest recent one.

    A browser may drop the referrer that carries the token. Locally there is
    one researcher, so the most recent unclaimed seed is the one they just
    clicked -- but only for as long as a page takes to load.
    """
    _sweep()
    directory = seed_dir()
    if not os.path.isdir(directory):
        return None

    candidates: List[Seed] = []
    for name in os.listdir(directory):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                candidates.append(Seed.from_json(json.load(fh)))
        except (ValueError, OSError):
            continue

    chosen = None
    if token:
        chosen = next((s for s in candidates if s.token == token), None)
    if chosen is None and not token:
        fresh = [s for s in candidates if not s.expired]
        chosen = max(fresh, key=lambda s: s.created) if fresh else None
    if chosen is None:
        return None

    _drop(chosen.token)
    return chosen


def _drop(token: str) -> None:
    try:
        os.remove(os.path.join(seed_dir(), token + ".json"))
    except OSError:
        pass


def _sweep() -> None:
    """Forget seeds nobody claimed."""
    directory = seed_dir()
    if not os.path.isdir(directory):
        return
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if (time.time() - os.path.getmtime(path)) > SEED_TTL:
                os.remove(path)
        except OSError:
            pass


class Workspace:
    """Which project is open, and everything measured about it."""

    def __init__(self, project_dir: str = ".", profile: Optional[Profile] = None,
                 session=None):
        self.project_dir = os.path.abspath(project_dir)
        self.profile = profile
        self.session = session
        self.project = registry.by_path(self.project_dir)
        self._suggestions: Optional[List[suggest_mod.Suggestion]] = None
        self._counter = 0

    # -- the open project ------------------------------------------------

    @property
    def ready(self) -> bool:
        return self.profile is not None

    def open(self, project_id: str) -> Optional[registry.Project]:
        """Switch to another registered project, measuring it afresh."""
        project = registry.get(project_id)
        if project is None:
            return None
        self.project = registry.touch(project_id) or project
        self.project_dir = project.path
        self.profile = None
        self.session = None
        self._suggestions = None
        if project.initialised:
            self.profile = profile_project(project.path)
        return self.project

    def reopen(self) -> None:
        """Re-measure the current project, after `epsilon init` has run."""
        self.profile = None
        self._suggestions = None
        self.session = None
        if os.path.exists(os.path.join(self.project_dir, "generated", "data.csv")):
            self.profile = profile_project(self.project_dir)

    # -- what to suggest -------------------------------------------------

    def cards(self, refresh: bool = False) -> List[suggest_mod.Suggestion]:
        """Analyses worth running here. Measured once, then remembered."""
        if self.profile is None:
            return []
        if self._suggestions is not None and not refresh:
            return self._suggestions

        provider = None
        try:
            from sdk.llm import get_provider
            provider = get_provider()
        except Exception:
            provider = None
        self._suggestions = suggest_mod.propose(self.profile, provider)
        return self._suggestions

    # -- handing a card to a session -------------------------------------

    def hand_off(self, index: int) -> Optional[Seed]:
        """Prepare a session seeded with one card's context."""
        cards = self.cards()
        if index < 0 or index >= len(cards):
            return None
        card = cards[index]
        self._counter += 1
        token = "{0}-{1}-{2}".format(
            (self.project.id if self.project else "project"),
            int(time.time()), self._counter)
        seed = Seed(token=token,
                    project_id=self.project.id if self.project else "",
                    project_dir=self.project_dir,
                    title=card.title, question=card.question,
                    analysis=card.analysis, fields=dict(card.fields),
                    created=time.time())
        put_seed(seed)
        return seed

    def ask_seed(self, question: str) -> Seed:
        """Prepare a session for a free-typed question."""
        self._counter += 1
        token = "{0}-{1}-{2}".format(
            (self.project.id if self.project else "project"),
            int(time.time()), self._counter)
        seed = Seed(token=token,
                    project_id=self.project.id if self.project else "",
                    project_dir=self.project_dir,
                    title=question[:60], question=question,
                    created=time.time())
        put_seed(seed)
        return seed
