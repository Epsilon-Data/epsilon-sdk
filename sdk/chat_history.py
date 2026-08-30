"""
Session history for the chat, per project.

Chainlit shows its thread sidebar only when it has a database to keep threads
in and a user to keep them for. Locally there is one researcher, so the
"user" is the project: every thread is filed under the project it was about,
and the sidebar in one project's assistant lists only that project's
sessions.

Everything lives in ~/.epsilon_sdk -- one SQLite file for every project's
threads (scoped by identity), and the signing secret Chainlit needs once
authentication exists at all. The per-project audit transcript in
.epsilon/chat/*.jsonl is unchanged; this is the browsable copy, not the
record.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from typing import Any, Dict, List, Tuple

COOKIE = "epsilon_project"
LOCAL_USER = "local"

# How much of an old conversation is put back in front of the model on
# resume. The full transcript stays on disk; the model needs recent context,
# not the whole history bill.
RESUME_MESSAGES = 20
RESUME_CHARS = 2000


def _sdk_dir() -> str:
    path = os.path.join(os.path.expanduser("~"), ".epsilon_sdk")
    if not os.path.isdir(path):
        os.makedirs(path, mode=0o700)
    return path


def db_path() -> str:
    return os.path.join(_sdk_dir(), "chat.db")


def conninfo() -> str:
    return "sqlite+aiosqlite:///" + db_path()


def ensure_secret() -> str:
    """The signing secret Chainlit's auth needs. Created once, kept private."""
    if os.environ.get("CHAINLIT_AUTH_SECRET"):
        return os.environ["CHAINLIT_AUTH_SECRET"]
    path = os.path.join(_sdk_dir(), "chainlit_secret")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            secret = fh.read().strip()
    else:
        secret = secrets.token_urlsafe(48)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(secret)
    os.environ["CHAINLIT_AUTH_SECRET"] = secret
    return secret


# The tables Chainlit's SQLAlchemy layer reads and writes, as it expects
# them: camelCase, quoted, one column per key it may insert.
_SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS users (
        "id" TEXT PRIMARY KEY,
        "identifier" TEXT NOT NULL UNIQUE,
        "metadata" TEXT NOT NULL,
        "createdAt" TEXT
    )''',
    '''CREATE TABLE IF NOT EXISTS threads (
        "id" TEXT PRIMARY KEY,
        "createdAt" TEXT,
        "name" TEXT,
        "userId" TEXT,
        "userIdentifier" TEXT,
        "tags" TEXT,
        "metadata" TEXT
    )''',
    '''CREATE TABLE IF NOT EXISTS steps (
        "id" TEXT PRIMARY KEY,
        "name" TEXT,
        "type" TEXT,
        "threadId" TEXT,
        "parentId" TEXT,
        "streaming" BOOLEAN,
        "waitForAnswer" BOOLEAN,
        "isError" BOOLEAN,
        "metadata" TEXT,
        "tags" TEXT,
        "input" TEXT,
        "output" TEXT,
        "createdAt" TEXT,
        "command" TEXT,
        "start" TEXT,
        "end" TEXT,
        "generation" TEXT,
        "showInput" TEXT,
        "language" TEXT,
        "indent" INT,
        "defaultOpen" BOOLEAN,
        "autoCollapse" BOOLEAN,
        "icon" TEXT,
        "modes" TEXT,
        "feedback" TEXT
    )''',
    '''CREATE TABLE IF NOT EXISTS elements (
        "id" TEXT PRIMARY KEY,
        "threadId" TEXT,
        "type" TEXT,
        "url" TEXT,
        "chainlitKey" TEXT,
        "name" TEXT,
        "display" TEXT,
        "objectKey" TEXT,
        "size" TEXT,
        "page" INT,
        "language" TEXT,
        "forId" TEXT,
        "mime" TEXT,
        "path" TEXT,
        "props" TEXT,
        "autoPlay" BOOLEAN,
        "playerConfig" TEXT
    )''',
    '''CREATE TABLE IF NOT EXISTS feedbacks (
        "id" TEXT PRIMARY KEY,
        "forId" TEXT,
        "threadId" TEXT,
        "value" INT,
        "comment" TEXT
    )''',
]


def ensure_schema(path: str = "") -> str:
    """Create the thread tables if they are not there. Idempotent."""
    path = path or db_path()
    connection = sqlite3.connect(path)
    try:
        for statement in _SCHEMA:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()
    return path


# -- identity: the project is the user ----------------------------------

def identity_for(project_id: str) -> str:
    return "project:" + project_id if project_id else LOCAL_USER


def project_from_identity(identifier: str) -> str:
    if (identifier or "").startswith("project:"):
        return identifier.split(":", 1)[1]
    return ""


def project_from_cookie(cookie_header: str) -> str:
    """The project id the pages leave in a cookie, if any."""
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE and value:
            return value
    return ""


# -- resume: recent context, not the whole bill --------------------------

def resume_context(thread: Dict[str, Any],
                   limit: int = RESUME_MESSAGES,
                   chars: int = RESUME_CHARS) -> List[Tuple[str, str]]:
    """The (role, text) pairs worth putting back in front of the model.

    Only what was actually said -- tool chatter is re-derivable and rots
    fastest. Capped, because the transcript on disk is the record; the model
    only needs enough to go on.
    """
    out: List[Tuple[str, str]] = []
    for step in (thread or {}).get("steps") or []:
        kind = step.get("type")
        text = (step.get("output") or "").strip()
        if not text:
            continue
        if kind == "user_message":
            out.append(("user", text[:chars]))
        elif kind == "assistant_message":
            out.append(("assistant", text[:chars]))
    return out[-limit:]
