"""Bounded background work with durable outcomes and explicit recovery."""
import copy
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock

from sdk.workbench.errors import PublicError, public_error, NotFound, Conflict
from sdk.errors import SDKError
from sdk.llm.base import LLMError
from sdk.workbench.store import identifier

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class Cancelled(SDKError):
    pass


def owner_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Job:
    def __init__(self, project_id, kind, scope, *, job_id=None, metadata=None, store=None, owner=None):
        self.id, self.project_id, self.kind = job_id or identifier(), project_id, kind
        self.scope = scope
        self.status = "queued"
        self.events = []
        self.result = None
        self.error = None
        self.reason = None
        self.metadata = metadata or {}
        self.attempt = 1
        self.created = time.time()
        self.owner = owner
        self.owner_pid = os.getpid()
        self.store = store
        self.cancel = Event()
        self.cancel_requested = False
        self.lock = RLock()

    @classmethod
    def restore(cls, value, store=None):
        job = cls(value["project_id"], value["kind"], value["scope"], store=store)
        for key in ("id", "status", "events", "result", "error", "reason", "metadata", "attempt", "created", "owner", "owner_pid", "cancel_requested"):
            if key in value:
                setattr(job, key, value[key])
        return job

    def save(self, *, claim=False):
        if self.store:
            value = dict(self.payload(), created=self.created, owner=self.owner, owner_pid=self.owner_pid)
            # Notebook results already have durable source/output/run records.
            # Do not duplicate every cell's large MIME bundles in the job log.
            if self.kind == "notebook" and self.result:
                value["result"] = {"saved": self.result.get("saved", False), "run_id": self.result.get("run", {}).get("id"),
                                   "note": self.result.get("note", ""), "restored": True}
            self.store.save_job(value, claim=claim)

    def emit(self, stage, message):
        self.check_cancelled()
        with self.lock:
            self.events.append({"id": len(self.events) + 1, "stage": stage, "message": message})
            self.events = self.events[-100:]
            self.save()

    def remember(self, key, value):
        """Record progress a retry must reuse. Workers never edit metadata in
        place: the progress stream serialises it from another thread."""
        with self.lock:
            self.metadata = dict(self.metadata, **{key: copy.deepcopy(value)})
            self.save()

    def check_cancelled(self):
        if self.store and not self.cancel.is_set():
            saved = self.store.saved_job(self.project_id, self.id)
            if (saved.get("cancel_requested") or saved["status"] == "interrupted" or
                    saved.get("owner") != self.owner or saved.get("attempt") != self.attempt):
                self.cancel_requested = True
                self.cancel.set()
        if self.cancel.is_set():
            raise Cancelled("The operation was cancelled.")

    def payload(self):
        with self.lock:
            return {"id": self.id, "project_id": self.project_id, "kind": self.kind, "scope": self.scope,
                    "status": self.status, "events": list(self.events), "result": self.result,
                    "error": self.error, "reason": self.reason, "attempt": self.attempt, "metadata": copy.deepcopy(self.metadata),
                    "cancel_requested": self.cancel_requested}


class Jobs:
    def __init__(self, store=None):
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="epsilon-workbench")
        self.jobs = {}
        self.lock = RLock()
        self.store = store
        self.owner = identifier()
        if store:
            for value in store.saved_jobs(active=True):
                self.restore(value)

    def restore(self, value):
        job = Job.restore(value, self.store)
        if job.status not in TERMINAL and not owner_alive(job.owner_pid):
            job.status = "interrupted"
            job.error = "Epsilon stopped before this task finished. Your saved work is available; retry when ready."
            job.save()
        return job

    def submit(self, project_id, kind, scope, operation, *, request_id=None, metadata=None, retry=False):
        with self.lock:
            # Keep recent in-memory outputs for the UI. Older jobs remain in
            # SQLite; notebook output also has its own durable run record.
            finished = sorted((j for j in self.jobs.values() if j.status in TERMINAL), key=lambda j: j.created, reverse=True)
            for old in finished[128:]:
                self.jobs.pop(old.id, None)
            previous = None
            if request_id:
                try:
                    previous = self.get(project_id, request_id)
                except NotFound:
                    pass
            if previous:
                before, after = previous.metadata.get("request", {}), (metadata or {}).get("request", {})
                same = (all(before.get(k) == after.get(k) for k in ("question", "thread_id", "notebook_id")) if retry else before == after)
                if previous.scope != scope or not same:
                    raise Conflict("This request identifier belongs to a different question. Send a new request.")
                if not retry or previous.status not in {"failed", "cancelled", "interrupted"}:
                    return previous
            if any(j.scope == scope and j.status in ("queued", "running") for j in self.jobs.values()):
                raise PublicError("This work is already running. Wait or cancel before starting it again.")
            if sum(j.status in ("queued", "running") for j in self.jobs.values()) >= 8:
                raise PublicError("The workspace is busy. Wait for an active task to finish.")
            job = Job(project_id, kind, scope, job_id=request_id, metadata=metadata, store=self.store, owner=self.owner)
            if previous:
                job.metadata = dict(previous.metadata, request=metadata["request"])
                job.attempt = previous.attempt + 1
                job.created = previous.created
            job.save(claim=True)
            self.jobs[job.id] = job

        def run():
            result, status, error, reason = None, "completed", None, None
            try:
                job.check_cancelled()
                with job.lock:
                    job.check_cancelled()
                    job.status = "running"
                    job.save()
                result = operation(job)
            except Cancelled as exc:
                status, error = "cancelled", str(exc)
            except LLMError as exc:
                status, error, reason = "failed", exc.public_message, exc.reason
            except (SDKError, ValueError, KeyError, OSError) as exc:
                status = "cancelled" if job.cancel.is_set() else "failed"
                error = public_error(exc)
            except Exception:
                status, error = "failed", "The operation failed. Retry or check your project configuration."
            finally:
                with job.lock:
                    if job.status != "interrupted":
                        job.result, job.status, job.error, job.reason = result, status, error, reason
                    job.save()

        self.executor.submit(run)
        return job

    def get(self, project_id, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if job is not None and job.project_id == project_id and (not self.store or job.status not in TERMINAL):
            return job
        if self.store:
            saved = self.store.saved_job(project_id, job_id)
            if job and saved.get("owner") == job.owner and saved.get("attempt") == job.attempt:
                return job
            return self.restore(saved)
        raise NotFound("Task not found in this project.")

    def cancel(self, project_id, job_id):
        job = self.get(project_id, job_id)
        requested = self.store.cancel_job(project_id, job_id) if self.store else job.status not in TERMINAL
        if requested:
            job.cancel_requested = True
            job.cancel.set()
        return requested

    def for_thread(self, project_id, thread_id):
        values = self.store.saved_jobs(project_id, scope=project_id + ":thread:" + thread_id) if self.store else [j.payload() for j in self.jobs.values()]
        return [self.restore(v).payload() for v in values if v["project_id"] == project_id and v["kind"] == "chat" and v["metadata"].get("request", {}).get("thread_id") == thread_id]

    def active(self, project_id):
        if self.store:
            jobs = [self.restore(v) for v in self.store.saved_jobs(project_id, active=True)]
            return [j.payload() for j in jobs if j.status not in TERMINAL]
        return [j.payload() for j in self.jobs.values() if j.project_id == project_id and j.status not in TERMINAL]

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                if job.owner == self.owner and job.status not in TERMINAL:
                    with job.lock:
                        job.cancel.set()
                        job.status = "interrupted"
                        job.error = "Epsilon stopped before this task finished. Your saved work is available; retry when ready."
                        job.save()
        self.executor.shutdown(wait=False)
