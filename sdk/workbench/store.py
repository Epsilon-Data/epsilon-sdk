"""Durable research state, independent of the chat presentation framework."""
import json
import copy
import hashlib
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sdk.workbench.errors import Conflict, NotFound


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier():
    return uuid.uuid4().hex


def cell_digest(cell):
    return hashlib.sha256((cell.get("kind", "code") + "\0" + cell["source"]).encode()).hexdigest()


def notebook_cells(cells):
    return [dict(cell, id=cell.get("id") or "cell-" + identifier(), kind=cell.get("kind", "code")) for cell in cells]


def load_notebook(db, project_id, notebook_id):
    """A stored notebook payload, or None, read inside the caller's transaction."""
    row = db.execute("SELECT payload FROM notebooks WHERE project_id=? AND id=?", (project_id, notebook_id)).fetchone()
    return json.loads(row["payload"]) if row else None


def mark_stale(cells, start, reason):
    for cell in cells[start:]:
        if cell.get("output"):
            cell["output"] = dict(cell["output"], stale=True, stale_reason=reason)


def invalidate_changed_cells(before, after):
    """Conservative ordering warning; not a Python dependency graph."""
    old = [(c["id"], cell_digest(c)) for c in notebook_cells(before) if c["kind"] == "code"]
    new = [(c["id"], cell_digest(c)) for c in after if c["kind"] == "code"]
    if not old or old == new:
        return
    for index, cell in enumerate(after):
        if cell["kind"] == "code":
            if not old or old.pop(0) != (cell["id"], cell_digest(cell)):
                mark_stale(after, index, "Code earlier in this notebook changed. Rerun from that cell to refresh these outputs.")
                break


def read_setting(path, key, default=None):
    """Read one workspace setting without creating, migrating or locking the database.

    The CLI uses this to report what a running or future workspace will use.
    """
    path = Path(path)
    if not path.is_file():
        return default
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        finally:
            db.close()
    except sqlite3.Error:
        return default
    return json.loads(row[0]) if row else default


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS threads (
                  id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                  title TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS thread_projects ON threads(project_id, updated);
                CREATE TABLE IF NOT EXISTS messages (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
                  role TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL,
                  FOREIGN KEY(thread_id) REFERENCES threads(id));
                CREATE TABLE IF NOT EXISTS objects (
                  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, thread_id TEXT,
                  kind TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS object_projects ON objects(project_id,kind);
                CREATE TABLE IF NOT EXISTS notebooks (
                  project_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(project_id,id));
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, scope TEXT NOT NULL,
                  payload TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS job_projects ON jobs(project_id,updated);
                CREATE TABLE IF NOT EXISTS archived_work (
                  project_id TEXT NOT NULL, id TEXT NOT NULL,
                  PRIMARY KEY(project_id,id));
                CREATE TABLE IF NOT EXISTS notebook_runs (
                  project_id TEXT NOT NULL, notebook_id TEXT NOT NULL,
                  run_id TEXT PRIMARY KEY, created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS notebook_run_order ON notebook_runs(project_id,notebook_id,created);
                CREATE TABLE IF NOT EXISTS notebook_threads (
                  project_id TEXT NOT NULL, notebook_id TEXT NOT NULL,
                  thread_id TEXT NOT NULL, created TEXT NOT NULL,
                  PRIMARY KEY(project_id,notebook_id));
                CREATE TABLE IF NOT EXISTS example_copies (
                  project_id TEXT NOT NULL, request_id TEXT NOT NULL,
                  example_id TEXT NOT NULL, version TEXT NOT NULL, notebook_id TEXT NOT NULL,
                  PRIMARY KEY(project_id,request_id));
                CREATE TABLE IF NOT EXISTS usage (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, thread_id TEXT,
                  request_id TEXT, kind TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                  input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                  cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
                  calls INTEGER NOT NULL, cost REAL, created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS usage_projects ON usage(project_id,thread_id);
            """)
            if "shareable" not in {r["name"] for r in db.execute("PRAGMA table_info(messages)")}:
                db.execute("ALTER TABLE messages ADD COLUMN shareable INTEGER NOT NULL DEFAULT 1")
            if "request_id" not in {r["name"] for r in db.execute("PRAGMA table_info(messages)")}:
                db.execute("ALTER TABLE messages ADD COLUMN request_id TEXT")
            if "meta" not in {r["name"] for r in db.execute("PRAGMA table_info(messages)")}:
                db.execute("ALTER TABLE messages ADD COLUMN meta TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS message_requests ON messages(thread_id,request_id,role)")
            if "status" not in {r["name"] for r in db.execute("PRAGMA table_info(jobs)")}:
                db.execute("ALTER TABLE jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'interrupted'")
                for row in db.execute("SELECT id,payload FROM jobs").fetchall():
                    db.execute("UPDATE jobs SET status=? WHERE id=?", (json.loads(row["payload"])["status"], row["id"]))
            db.execute("CREATE INDEX IF NOT EXISTS job_states ON jobs(status,scope)")
            for row in db.execute("SELECT project_id,id,payload FROM notebooks").fetchall():
                book = json.loads(row["payload"])
                if any(not cell.get("id") for cell in book["cells"]):
                    book["cells"] = notebook_cells(book["cells"])
                    db.execute("UPDATE notebooks SET payload=? WHERE project_id=? AND id=?", (json.dumps(book), row["project_id"], row["id"]))
            for row in db.execute("SELECT o.* FROM objects o LEFT JOIN notebook_runs r ON r.run_id=o.id WHERE o.kind='notebook_run' AND r.run_id IS NULL").fetchall():
                run = json.loads(row["payload"])
                db.execute("INSERT INTO notebook_runs VALUES (?,?,?,?)", (row["project_id"], run["notebook_id"], row["id"], row["created"]))
        os.chmod(str(self.path), 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_thread(self, project_id, title="New analysis"):
        thread = {"id": identifier(), "project_id": project_id,
                  "title": title[:100], "created": now(), "updated": now()}
        with self.connect() as db:
            db.execute("INSERT INTO threads VALUES (:id,:project_id,:title,:created,:updated)", thread)
        return thread

    def threads(self, project_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM threads WHERE project_id=? ORDER BY updated DESC", (project_id,))]

    def archived(self, project_id):
        with self.connect() as db:
            return {r["id"] for r in db.execute("SELECT id FROM archived_work WHERE project_id=?", (project_id,))}

    def archive(self, project_id, work_id, archived):
        with self.connect() as db:
            if archived:
                db.execute("INSERT OR IGNORE INTO archived_work VALUES (?,?)", (project_id, work_id))
            else:
                db.execute("DELETE FROM archived_work WHERE project_id=? AND id=?", (project_id, work_id))

    def recent_work(self, project_id, archived=False):
        """Navigation metadata for conversations, results and saved notebooks.

        Group related work together. Never return sources, messages or outputs
        in this index, including notebook output that has not been reviewed.
        """
        with self.connect() as db:
            threads = {r["id"]: dict(r) for r in db.execute(
                "SELECT t.*,COUNT(m.seq) AS message_count FROM threads t LEFT JOIN messages m ON m.thread_id=t.id "
                "WHERE t.project_id=? GROUP BY t.id", (project_id,))}
            books = list(db.execute(
                "SELECT n.id,n.payload,COALESCE(l.thread_id,o.thread_id) AS thread_id "
                "FROM notebooks n LEFT JOIN notebook_threads l ON l.project_id=n.project_id AND l.notebook_id=n.id "
                "LEFT JOIN objects o ON o.project_id=n.project_id AND o.id=n.id AND o.kind IN ('plan','artifact','draft') "
                "WHERE n.project_id=?", (project_id,)))
            results = list(db.execute("SELECT id,thread_id,payload,created FROM objects WHERE project_id=? AND kind='artifact' ORDER BY created", (project_id,)))
        items = {}

        def entry(tid, key, title, updated):
            if key not in items:
                thread = threads.get(tid, {})
                items[key] = {"id": key, "thread_id": tid, "notebook_id": None, "artifact_id": None,
                              "title": thread.get("title", title), "updated": updated,
                              "kind": "conversation", "result_count": 0}
            return items[key]

        for tid, thread in threads.items():
            if thread["message_count"]:
                entry(tid, tid, thread["title"], thread["updated"])
        for row in results:
            value = json.loads(row["payload"])
            tid = row["thread_id"] if row["thread_id"] in threads else None
            item = entry(tid, tid or "result:" + row["id"], value["title"], row["created"])
            item.update(kind="result", artifact_id=row["id"], result_count=item["result_count"] + 1,
                        updated=max(item["updated"], row["created"]))
        for row in sorted(books, key=lambda r: json.loads(r["payload"]).get("updated", "")):
            value = json.loads(row["payload"])
            tid = row["thread_id"] if row["thread_id"] in threads else None
            timestamp = value.get("updated") or threads.get(tid, {}).get("updated", "")
            item = entry(tid, tid or "notebook:" + row["id"], value.get("title", "Research notebook"), timestamp)
            item.update(kind="notebook", notebook_id=row["id"], updated=max(item["updated"], timestamp))
        hidden = self.archived(project_id)
        return sorted((dict(item, archived=archived) for item in items.values() if
                       (item["id"] in hidden or "notebook:" + (item["notebook_id"] or "") in hidden) == archived),
                      key=lambda item: (item["updated"], item["id"]), reverse=True)

    def thread(self, project_id, thread_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM threads WHERE project_id=? AND id=?", (project_id, thread_id)).fetchone()
            if row is None:
                raise NotFound("Conversation not found in this project.")
            thread = dict(row)
            thread["messages"] = [dict(r, meta=json.loads(r["meta"]) if r["meta"] else None)
                                  for r in db.execute("SELECT * FROM messages WHERE thread_id=? ORDER BY seq", (thread_id,))]
        thread["plans"] = self.objects(project_id, "plan", thread_id)
        thread["artifacts"] = self.objects(project_id, "artifact", thread_id)
        return thread

    def rename_thread(self, project_id, thread_id, title):
        self.thread(project_id, thread_id)
        with self.connect() as db:
            db.execute("UPDATE threads SET title=?,updated=? WHERE id=? AND project_id=?", (title[:100], now(), thread_id, project_id))

    def message(self, project_id, thread_id, role, text, shareable=True, draft_ids=None, request_id=None, meta=None):
        self.thread(project_id, thread_id)
        if role not in ("user", "assistant"):
            raise Conflict("Invalid message role.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO messages(thread_id,role,text,created,shareable,request_id,meta) VALUES (?,?,?,?,?,?,?)",
                       (thread_id, role, text, now(), int(shareable), request_id, json.dumps(meta) if meta else None))
            seq = (db.execute("SELECT seq FROM messages WHERE thread_id=? AND request_id=? AND role=?", (thread_id, request_id, role)).fetchone()["seq"]
                   if request_id else db.execute("SELECT last_insert_rowid()").fetchone()[0])
            for draft_id in draft_ids or []:
                row = db.execute("SELECT payload FROM objects WHERE project_id=? AND thread_id=? AND id=? AND kind='draft'", (project_id, thread_id, draft_id)).fetchone()
                if row is None:
                    raise NotFound("Code suggestion not found in this conversation.")
                draft = json.loads(row["payload"])
                draft["message_id"] = seq
                db.execute("UPDATE objects SET payload=? WHERE project_id=? AND id=?", (json.dumps(draft), project_id, draft_id))
            db.execute("UPDATE threads SET updated=? WHERE id=?", (now(), thread_id))
        return seq

    def saved_jobs(self, project_id=None, *, scope=None, active=False):
        conditions, args = [], []
        if project_id:
            conditions.append("project_id=?")
            args.append(project_id)
        if scope:
            conditions.append("scope=?")
            args.append(scope)
        if active:
            conditions.append("status IN ('queued','running')")
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM jobs" + (" WHERE " + " AND ".join(conditions) if conditions else "") + " ORDER BY updated DESC", args).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def saved_job(self, project_id, job_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM jobs WHERE project_id=? AND id=?", (project_id, job_id)).fetchone()
        if row is None:
            raise NotFound("Task not found in this project.")
        return json.loads(row["payload"])

    def save_job(self, payload, *, claim=False):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (payload["id"],)).fetchone()
            previous = json.loads(row["payload"]) if row else None
            if claim:
                if previous and (previous["project_id"] != payload["project_id"] or previous["scope"] != payload["scope"]):
                    raise Conflict("This request identifier belongs to another task.")
                if previous and (previous["status"] not in ("failed", "cancelled", "interrupted") or
                                 payload.get("attempt", 1) != previous.get("attempt", 1) + 1):
                    raise Conflict("This request has already been accepted. Reconnect to see its current outcome.")
                active = [dict(r) for r in db.execute("SELECT scope FROM jobs WHERE status IN ('queued','running')")]
                if any(j["scope"] == payload["scope"] for j in active):
                    raise Conflict("This work is already running. Wait or cancel before starting it again.")
                if len(active) >= 8:
                    raise Conflict("The workspace is busy. Wait for an active task to finish.")
            elif previous:
                # A stopped worker can finish after another server has retried
                # the request. It must never overwrite the newer attempt.
                if any(previous.get(k) != payload.get(k) for k in ("owner", "attempt", "project_id", "scope")):
                    return False
                if previous.get("cancel_requested"):
                    payload = dict(payload, cancel_requested=True)
            db.execute("INSERT INTO jobs(id,project_id,scope,payload,updated,status) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated,status=excluded.status",
                       (payload["id"], payload["project_id"], payload["scope"], json.dumps(payload), now(), payload["status"]))
        return True

    def cancel_job(self, project_id, job_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM jobs WHERE project_id=? AND id=?", (project_id, job_id)).fetchone()
            if row is None:
                raise NotFound("Task not found in this project.")
            payload = json.loads(row["payload"])
            if payload["status"] not in ("queued", "running"):
                return False
            payload["cancel_requested"] = True
            db.execute("UPDATE jobs SET payload=?,updated=? WHERE project_id=? AND id=?",
                       (json.dumps(payload), now(), project_id, job_id))
        return True

    def put(self, project_id, kind, payload, thread_id=None):
        if thread_id:
            self.thread(project_id, thread_id)
        value = dict(payload, id=identifier(), project_id=project_id, thread_id=thread_id, created=now())
        with self.connect() as db:
            db.execute("INSERT INTO objects VALUES (?,?,?,?,?,?)", (value["id"], project_id, thread_id, kind, json.dumps(value), value["created"]))
        return value

    def get(self, project_id, kind, object_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM objects WHERE id=? AND project_id=? AND kind=?", (object_id, project_id, kind)).fetchone()
        if row is None:
            raise NotFound("This item does not belong to the selected project.")
        return json.loads(row["payload"])

    def objects(self, project_id, kind, thread_id=None):
        query = "SELECT payload FROM objects WHERE project_id=? AND kind=?"
        args = [project_id, kind]
        if thread_id is not None:
            query += " AND thread_id=?"
            args.append(thread_id)
        query += " ORDER BY created DESC"
        with self.connect() as db:
            return [json.loads(r["payload"]) for r in db.execute(query, args)]

    def notebook(self, project_id, notebook_id="main"):
        with self.connect() as db:
            value = load_notebook(db, project_id, notebook_id)
        value = value or {"id": notebook_id, "cells": [{"id": "initial-cell", "source": "# Develop your analysis on the synthetic projection.\n", "output": None}], "revision": 0}
        value["cells"] = notebook_cells(value["cells"])
        return value

    def notebooks(self, project_id):
        """Every saved notebook with its conversation title, newest first."""
        with self.connect() as db:
            rows = db.execute("SELECT n.id,n.payload,t.title,t.id AS thread_id FROM notebooks n "
                              "LEFT JOIN notebook_threads l ON l.project_id=n.project_id AND l.notebook_id=n.id "
                              "LEFT JOIN threads t ON t.id=l.thread_id AND t.project_id=n.project_id "
                              "WHERE n.project_id=? ORDER BY n.rowid DESC", (project_id,)).fetchall()
        return [dict(json.loads(r["payload"]), id=r["id"], thread_id=r["thread_id"], thread_title=r["title"]) for r in rows]

    def save_notebook(self, project_id, notebook_id, cells, revision, title=None):
        with self.connect() as db:
            # Serialize read-check-write across processes as well as threads.
            db.execute("BEGIN IMMEDIATE")
            previous = load_notebook(db, project_id, notebook_id) or {"revision": 0}
            if previous["revision"] != revision:
                raise Conflict("The notebook changed in another tab. Reload before saving.")
            cells = notebook_cells(cells)
            invalidate_changed_cells(previous.get("cells", []), cells)
            if len({c["id"] for c in cells}) != len(cells):
                raise Conflict("Cell IDs must be unique in a notebook.")
            payload = {"id": notebook_id, "cells": cells, "revision": revision + 1, "updated": now()}
            if previous.get("example"):
                payload["example"] = previous["example"]
            if title or previous.get("title"):
                payload["title"] = title or previous["title"]
            db.execute("INSERT OR REPLACE INTO notebooks VALUES (?,?,?)", (project_id, notebook_id, json.dumps(payload)))
        return payload

    def copy_example(self, project_id, example, request_id):
        """An explicit copy creates one independent notebook and conversation.

        A retry returns the same notebook, including any subsequent manual edits.
        No outputs, fake user messages or preview artifacts are copied.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM example_copies WHERE project_id=? AND request_id=?",
                               (project_id, request_id)).fetchone()
            if prior:
                if prior["example_id"] != example["id"] or prior["version"] != example["version"]:
                    raise Conflict("This copy request was already used for another example. Reload and try again.")
                return load_notebook(db, project_id, prior["notebook_id"])
            nid, tid, timestamp = identifier(), identifier(), now()
            cells = [{"id": "cell-" + identifier(), "kind": c["kind"], "source": c["source"], "output": None}
                     for c in example["cells"]]
            payload = {"id": nid, "revision": 1, "updated": timestamp, "title": example["title"], "cells": cells,
                       "example": {"id": example["id"], "title": example["title"], "version": example["version"],
                                   "provenance": example["provenance"]}}
            db.execute("INSERT INTO notebooks VALUES (?,?,?)", (project_id, nid, json.dumps(payload)))
            db.execute("INSERT INTO threads VALUES (?,?,?,?,?)", (tid, project_id, example["title"][:100], timestamp, timestamp))
            db.execute("INSERT INTO notebook_threads VALUES (?,?,?,?)", (project_id, nid, tid, timestamp))
            db.execute("INSERT INTO example_copies VALUES (?,?,?,?,?)",
                       (project_id, request_id, example["id"], example["version"], nid))
        return payload

    def attach_execution(self, project_id, notebook_id, saved, cell_index, output):
        """Keep every completed run and attach it by cell identity, atomically."""
        from sdk.workbench.display import apply_updates
        executed = saved["cells"][cell_index]
        run = {"id": identifier(), "notebook_id": notebook_id, "cell_id": executed["id"],
               "source": executed["source"], "output": dict(output, code_digest=hashlib.sha256(executed["source"].encode()).hexdigest()),
               "created": now(), "attached": False}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = load_notebook(db, project_id, notebook_id)
            index = next((i for i, c in enumerate(current["cells"]) if c.get("id") == executed["id"] and cell_digest(c) == cell_digest(executed)), None) if current else None
            if index is not None:
                before = [(c["id"], cell_digest(c)) for c in saved["cells"][:cell_index] if c.get("kind", "code") == "code"]
                after = [(c["id"], cell_digest(c)) for c in current["cells"][:index] if c.get("kind", "code") == "code"]
                if before != after:
                    run["output"].update(stale=True, stale_reason="Earlier code changed during this run. Rerun from that cell.")
                current["cells"][index]["output"] = copy.deepcopy(run["output"])
                apply_updates(current, output)
                mark_stale(current["cells"], index + 1, "An earlier cell was run again. Rerun this cell to refresh its output.")
                current.update(revision=current["revision"] + 1, updated=now())
                db.execute("UPDATE notebooks SET payload=? WHERE project_id=? AND id=?", (json.dumps(current), project_id, notebook_id))
                run["attached"] = True
            db.execute("INSERT INTO objects VALUES (?,?,?,?,?,?)", (run["id"], project_id, None, "notebook_run", json.dumps(run), run["created"]))
            db.execute("INSERT INTO notebook_runs VALUES (?,?,?,?)", (project_id, notebook_id, run["id"], run["created"]))
        return {"notebook": current, "run": run, "saved": run["attached"],
                "note": "The executed cell changed. Its output is preserved in Notebook run history." if not run["attached"] else ""}

    def runs(self, project_id, notebook_id, offset=0):
        with self.connect() as db:
            return [json.loads(r["payload"]) for r in db.execute(
                "SELECT o.payload FROM notebook_runs r JOIN objects o ON o.id=r.run_id "
                "WHERE r.project_id=? AND r.notebook_id=? ORDER BY r.created DESC LIMIT 20 OFFSET ?",
                (project_id, notebook_id, offset))]

    def restart_notebook(self, project_id, notebook_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            book = load_notebook(db, project_id, notebook_id)
            if book:
                mark_stale(book["cells"], 0, "The notebook was restarted. Run the cells again to rebuild variables and refresh outputs.")
                book.update(revision=book["revision"] + 1, updated=now())
                db.execute("UPDATE notebooks SET payload=? WHERE project_id=? AND id=?", (json.dumps(book), project_id, notebook_id))

    def notebook_thread(self, project_id, notebook_id):
        """Bind a notebook to a conversation, including existing imported code."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT thread_id FROM notebook_threads WHERE project_id=? AND notebook_id=?", (project_id, notebook_id)).fetchone()
            if row:
                return row["thread_id"]
            original = db.execute("SELECT thread_id FROM objects WHERE project_id=? AND id=? AND kind IN ('plan','artifact','draft')", (project_id, notebook_id)).fetchone()
            tid = original["thread_id"] if original else None
            if not tid:
                tid, timestamp = identifier(), now()
                title = (load_notebook(db, project_id, notebook_id) or {}).get("title")
                db.execute("INSERT INTO threads VALUES (?,?,?,?,?)", (tid, project_id, title or "Notebook conversation", timestamp, timestamp))
            db.execute("INSERT INTO notebook_threads VALUES (?,?,?,?)", (project_id, notebook_id, tid, now()))
            return tid

    def thread_notebook(self, project_id, thread_id, notebook_id=None):
        self.thread(project_id, thread_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if notebook_id is not None:
                row = db.execute("SELECT thread_id FROM notebook_threads WHERE project_id=? AND notebook_id=?", (project_id, notebook_id)).fetchone()
                if row and row["thread_id"] != thread_id:
                    raise Conflict("This notebook belongs to another conversation.")
            else:
                row = db.execute("SELECT notebook_id FROM notebook_threads WHERE project_id=? AND thread_id=? ORDER BY created DESC LIMIT 1", (project_id, thread_id)).fetchone()
                notebook_id = row["notebook_id"] if row else thread_id
            db.execute("INSERT OR IGNORE INTO notebook_threads VALUES (?,?,?,?)", (project_id, notebook_id, thread_id, now()))
        return notebook_id

    def write_ai_cell(self, project_id, notebook_id, thread_id, source, title, kind="code", cell_id=None, expected=None, draft_id=None):
        """Atomic edit of a known AI cell, or append if it changed meanwhile."""
        nid = self.thread_notebook(project_id, thread_id, notebook_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            draft = None
            if draft_id:
                row = db.execute("SELECT payload FROM objects WHERE project_id=? AND thread_id=? AND id=? AND kind='draft'", (project_id, thread_id, draft_id)).fetchone()
                if row is None:
                    raise NotFound("Code suggestion not found in this conversation.")
                draft = json.loads(row["payload"])
                if draft.get("notebook_id", nid) != nid or draft["code"] != source or draft.get("kind", "code") != kind:
                    raise Conflict("This suggestion belongs to another notebook or source revision.")
                if draft.get("applied"):
                    return dict(draft["applied"], already_applied=True)
            book = load_notebook(db, project_id, nid) or {"id": nid, "revision": 0, "cells": []}
            cells = notebook_cells(book["cells"])
            index = next((i for i,c in enumerate(cells) if c["id"] == cell_id), None)
            before, status = None, "added"
            if cell_id and (not expected or cell_id not in expected):
                raise Conflict("Only a cell supplied in the assistant context can be revised.")
            if index is not None and cell_digest(cells[index]) == expected[cell_id]:
                before, status = copy.deepcopy(cells[index]), "updated"
            else:
                if cell_id:
                    status = "added_after_edit"
                if len(cells) >= 40:
                    raise Conflict("This notebook has reached its 40-cell limit.")
                index, cell_id = len(cells), "cell-" + identifier()
            change_id = identifier()
            cell = {"id": cell_id, "kind": kind, "source": source, "output": None,
                    "ai": {"change_id": change_id, "title": title, "thread_id": thread_id,
                           "shareable": draft.get("shareable", True) if draft else True}}
            cell["ai"]["digest"] = cell_digest(cell)
            if before is None:
                cells.append(cell)
            else:
                cells[index] = cell
            invalidate_changed_cells(book["cells"], cells)
            change = {"id": change_id, "notebook_id": nid, "cell_id": cell_id, "before": before,
                      "after_digest": cell_digest(cell), "source": source, "kind": kind,
                      "title": title, "created": now(), "draft_id": draft_id}
            db.execute("INSERT INTO objects VALUES (?,?,?,?,?,?)", (change_id, project_id, thread_id, "notebook_change", json.dumps(change), change["created"]))
            book.update(cells=cells, revision=book["revision"] + 1, updated=now())
            db.execute("INSERT OR REPLACE INTO notebooks VALUES (?,?,?)", (project_id, nid, json.dumps(book)))
            result = {"cell_id": cell_id, "change_id": change_id, "status": status, "revision": book["revision"]}
            if draft is not None:
                draft.update(applied=result, cell_id=cell_id, notebook_id=nid)
                db.execute("UPDATE objects SET payload=? WHERE project_id=? AND id=?", (json.dumps(draft), project_id, draft_id))
        return result

    def undo_ai_cell(self, project_id, notebook_id, change_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM objects WHERE project_id=? AND id=? AND kind='notebook_change'", (project_id, change_id)).fetchone()
            if row is None:
                raise NotFound("Notebook change not found in this project.")
            change = json.loads(row["payload"])
            if change["notebook_id"] != notebook_id:
                raise Conflict("This change belongs to another notebook.")
            book = load_notebook(db, project_id, notebook_id) or {"cells": []}
            previous = copy.deepcopy(book["cells"])
            index = next((i for i,c in enumerate(book["cells"]) if c.get("id") == change["cell_id"]), None)
            if index is None or book["cells"][index].get("ai", {}).get("change_id") != change_id or cell_digest(book["cells"][index]) != change["after_digest"]:
                raise Conflict("This cell has changed. Its current code was kept.")
            if change["before"] is None:
                book["cells"].pop(index)
            else:
                book["cells"][index] = change["before"]
            if not book["cells"]:
                book["cells"] = [{"id": "cell-" + identifier(), "kind": "code", "source": "", "output": None}]
            invalidate_changed_cells(previous, book["cells"])
            book.update(revision=book["revision"] + 1, updated=now())
            db.execute("INSERT OR REPLACE INTO notebooks VALUES (?,?,?)", (project_id, notebook_id, json.dumps(book)))
            if change.get("draft_id"):
                row = db.execute("SELECT payload FROM objects WHERE project_id=? AND id=? AND kind='draft'", (project_id, change["draft_id"])).fetchone()
                if row:
                    draft = json.loads(row["payload"])
                    if draft.get("applied", {}).get("change_id") == change_id:
                        draft.pop("applied", None)
                        draft.pop("cell_id", None)
                        db.execute("UPDATE objects SET payload=? WHERE project_id=? AND id=?", (json.dumps(draft), project_id, change["draft_id"]))
        return book

    def record_usage(self, project_id, thread_id, request_id, kind, provider, model, usage, calls, cost):
        """One row per attempt: a failed or retried request still spent tokens."""
        with self.connect() as db:
            db.execute("INSERT INTO usage(project_id,thread_id,request_id,kind,provider,model,input_tokens,output_tokens,"
                       "cache_read_tokens,cache_write_tokens,calls,cost,created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (project_id, thread_id, request_id, kind, provider, model, usage.input_tokens, usage.output_tokens,
                        usage.cache_read_tokens, usage.cache_write_tokens, calls, cost, now()))

    def usage(self, project_id=None, thread_id=None, by_request=False):
        """Totals for a conversation, a project or this computer, by model.

        With by_request, returns {request_id: totals} for one conversation.
        """
        conditions, args = [], []
        if project_id is not None:
            conditions.append("project_id=?")
            args.append(project_id)
        if thread_id is not None:
            conditions.append("thread_id=?")
            args.append(thread_id)
        if by_request:
            conditions.append("request_id IS NOT NULL")
        query = ("SELECT request_id,provider,model,COUNT(*) AS requests,SUM(calls) AS calls,SUM(input_tokens) AS input_tokens,"
                 "SUM(output_tokens) AS output_tokens,SUM(cache_read_tokens) AS cache_read_tokens,"
                 "SUM(cache_write_tokens) AS cache_write_tokens,SUM(cost) AS cost,SUM(cost IS NULL) AS unpriced FROM usage" +
                 (" WHERE " + " AND ".join(conditions) if conditions else "") +
                 " GROUP BY " + ("request_id," if by_request else "") + "provider,model ORDER BY MIN(id)")
        with self.connect() as db:
            rows = [dict(r) for r in db.execute(query, args)]

        def totals(group):
            counters = ("requests", "calls", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "unpriced")
            result = {key: sum(r[key] or 0 for r in group) for key in counters}
            result["total_tokens"] = sum(result[k] for k in counters[2:6])
            priced = [r["cost"] for r in group if r["cost"] is not None]
            result["cost"] = round(sum(priced), 6) if priced else None
            result["models"] = [{"provider": r["provider"], "model": r["model"], "requests": r["requests"],
                                 "total_tokens": sum(r[k] or 0 for k in counters[2:6]),
                                 "cost": round(r["cost"], 6) if r["cost"] is not None else None} for r in group]
            return result

        if not by_request:
            return totals(rows)
        grouped = {}
        for row in rows:
            grouped.setdefault(row["request_id"], []).append(row)
        return {request_id: totals(group) for request_id, group in grouped.items()}

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))
