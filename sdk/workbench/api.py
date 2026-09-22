"""Authenticated same-origin APIs for the owned Epsilon interface."""
import asyncio
import html
import io
import json
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional, Literal

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from sdk import credentials
from sdk.sso import BrowserSignIn, SignInError, CALLBACK_PATH, FLOW_TTL
from sdk.checks import check_source, scan_secrets
from sdk.errors import SDKError, AuthenticationError
from sdk.workbench import analysis, assistant, repairs, starters
from sdk.workbench.display import notebook_view, artifact_view
from sdk.workbench.kernel import Kernels, runtime_status
from sdk.workbench.security import LocalSessions, check_outbound
from sdk.workbench.service import Workbench
from sdk.workbench.store import identifier
from sdk.workbench.errors import PublicError, Conflict, NotFound, public_error
from sdk.workbench.examples import Examples
from sdk.workbench.middleware import LocalBoundary, cookie_name

ASSETS = Path(__file__).resolve().parent.parent / "static" / "workbench"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Bootstrap(Input):
    token: str = Field(min_length=20, max_length=120)


class Login(Input):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1000)


class BrowserLogin(Input):
    return_to: str = Field(default="/projects", max_length=1000)


class ProjectInput(Input):
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=500)
    dataset_id: Optional[str] = Field(default=None, min_length=1, max_length=200)


class ProjectEdit(Input):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class Initialise(Input):
    dataset_id: str = Field(min_length=1, max_length=200)
    dummy_data: bool = False


class Title(Input):
    title: str = Field(default="New analysis", min_length=1, max_length=100)


class SelectedCell(Input):
    cell_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    context_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]
    helper_cell_ids: List[str] = Field(default_factory=list, max_length=8)


class FieldChoice(Input):
    term: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=160)


class Question(Input):
    message: str = Field(min_length=1, max_length=8000)
    field_choice: Optional[FieldChoice] = None
    notebook_id: Optional[str] = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    request_id: Optional[str] = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    selected_cell: Optional[SelectedCell] = None


class ContextPreview(Input):
    helper_cell_ids: List[str] = Field(default_factory=list, max_length=8)


class RetryQuestion(Input):
    selected_cell: Optional[SelectedCell] = None


class ResearchContext(Input):
    goal: str = Field(default="", max_length=2000)
    fields: List[str] = Field(default_factory=list, max_length=30)


class PlanInput(Input):
    analysis: str = Field(min_length=1, max_length=60)
    fields: Dict[str, str] = Field(default_factory=dict, max_length=20)
    thread_id: Optional[str] = None


class AIInput(Input):
    provider: str
    model: str = Field(max_length=150)
    base_url: str = Field(default="", max_length=300)
    api_key: str = Field(default="", max_length=1000)
    persist: bool = False


class ModelChoice(Input):
    model: str = Field(min_length=1, max_length=150)


class ModelPrice(Input):
    model: str = Field(min_length=1, max_length=150)
    input: Optional[float] = Field(default=None, ge=0, le=10000)
    output: Optional[float] = Field(default=None, ge=0, le=10000)


class ForgetField(Input):
    term: str = Field(min_length=1, max_length=80)


class Cell(Input):
    source: str = Field(max_length=50000)
    kind: Literal["code", "markdown"] = "code"
    id: Optional[str] = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class Notebook(Input):
    cells: List[Cell] = Field(min_length=1, max_length=40)
    revision: int = Field(ge=0)
    title: Optional[str] = Field(default=None, max_length=100)


class Archive(Input):
    archived: bool


class Execute(Input):
    cell: int = Field(ge=0, le=39)
    revision: int = Field(ge=0)


class ImportNotebook(Input):
    kind: str
    object_id: str


class CopyExample(Input):
    version: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class ApplyCode(Input):
    mode: Literal["append", "replace"] = "append"


class Repair(Input):
    confirmed: Literal[True]
    context_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def build(launch_dir, state_dir=None, record=True, bench=None):
    bench = bench or Workbench(launch_dir, state_dir=state_dir, record=record)
    examples = Examples(bench)
    sessions = LocalSessions()
    browser_signin = BrowserSignIn(bench.credentials_path, bench.client_factory, sessions)
    kernels = Kernels(bench.state_dir)
    bench.notebook_runtime = kernels.status

    @asynccontextmanager
    async def lifespan(app):
        yield
        bench.jobs.close()
        await run_in_threadpool(kernels.close)

    app = FastAPI(title="Epsilon research workspace", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.workbench = bench
    app.state.local_sessions = sessions
    app.state.browser_signin = browser_signin
    app.state.kernels = kernels

    app.add_middleware(LocalBoundary, sessions=sessions)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default error includes input values (including passwords).
        return JSONResponse({"error": "Check the required form fields and their lengths."}, status_code=422)

    @app.exception_handler(SDKError)
    @app.exception_handler(KeyError)
    @app.exception_handler(ValueError)
    @app.exception_handler(OSError)
    async def operation_error(request, exc):
        if isinstance(exc, AuthenticationError):
            return JSONResponse({"error": "Your Epsilon session has ended. Sign in again to continue.",
                                 "code": "epsilon_sign_in_required"}, status_code=401)
        return JSONResponse({"error": public_error(exc)}, status_code=getattr(exc, "status_code", 500))

    @app.get("/api/health")
    def health():
        return {"application": "epsilon-workbench", "version": 1}

    @app.post("/api/bootstrap")
    def bootstrap(body: Bootstrap, request: Request):
        token, csrf = sessions.bootstrap(body.token)
        response = JSONResponse({"unlocked": True, "csrf": csrf})
        response.set_cookie(cookie_name(request), token, httponly=True, samesite="strict", max_age=604800, path="/")
        return response

    @app.post("/api/launch")
    def fresh_launch(body: Bootstrap):
        # The CLI reads this capability from an owner-only local file. It is
        # never included in browser assets, session responses or launch URLs.
        return {"token": sessions.fresh_launch(body.token)}

    @app.get("/api/session")
    def session(request: Request):
        if request.state.session is None:
            expired = sessions.get(request.cookies.get(cookie_name(request)), expired=True)
            return {"unlocked": False, "recoverable": True, "csrf": expired["csrf"]} if expired else {"unlocked": False}
        return {"unlocked": True, "csrf": request.state.session["csrf"],
                "account": credentials.status(bench.credentials_path), "ai": bench.ai_status(),
                "launch_dir": bench.launch_dir}

    @app.post("/api/session/renew")
    def renew_session(body: Input, request: Request):
        token = request.cookies.get(cookie_name(request))
        session = sessions.renew(token, request.headers.get("x-epsilon-csrf", ""))
        response = JSONResponse({"unlocked": True, "csrf": session["csrf"]})
        response.set_cookie(cookie_name(request), token, httponly=True, samesite="strict", max_age=604800, path="/")
        return response

    @app.post("/api/auth/login")
    def login(body: Login):
        try:
            credentials.sign_in(body.username, body.password, bench.credentials_path, bench.client_factory)
        except AuthenticationError:
            raise HTTPException(401, "Sign-in failed. Check your Epsilon username and password, and your connection to the configured server.")
        return credentials.status(bench.credentials_path)

    @app.post("/api/auth/start")
    def start_browser_signin(body: BrowserLogin, request: Request):
        try:
            flow = browser_signin.start(request.cookies.get(cookie_name(request)),
                                        str(request.base_url).rstrip("/"), body.return_to)
        except SignInError as exc:
            raise PublicError(exc.public_message) from None
        response = JSONResponse({"url": flow["url"]})
        # A narrowly scoped Lax cookie binds the top-level identity-provider
        # callback to this browser. The workspace capability remains Strict.
        response.set_cookie(cookie_name(request) + "_signin", flow["binding"],
                            httponly=True, samesite="lax", max_age=FLOW_TTL, path=CALLBACK_PATH)
        return response

    @app.get(CALLBACK_PATH)
    def browser_signin_callback(request: Request):
        try:
            query = request.query_params
            if any(len(query.getlist(key)) != 1 for key in query) or len(str(query)) > 8192:
                raise SignInError()
            destination = browser_signin.complete(dict(query), request.cookies.get(cookie_name(request) + "_signin"),
                                                   str(request.base_url).rstrip("/"))
        except SignInError as exc:
            destination = "/signin?auth_error=" + exc.kind
        # Commit a loopback document before loading the app: an HTTP redirect
        # chain from the IdP stays cross-site and does not regain Strict cookies.
        # No inline script and no auth parameters enter the destination URL.
        escaped = html.escape(destination, quote=True)
        response = HTMLResponse(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Returning to Epsilon</title>'
            '<script type="module" src="/assets/auth-return.js"></script></head>'
            '<body data-destination="' + escaped + '"><p>Returning to your workspace…</p>'
            '<a href="' + escaped + '">Continue to Epsilon</a></body></html>')
        response.delete_cookie(cookie_name(request) + "_signin", path=CALLBACK_PATH, httponly=True, samesite="lax")
        return response

    @app.post("/api/auth/logout")
    def logout(request: Request):
        browser_signin.cancel(request.cookies.get(cookie_name(request)))
        credentials.sign_out(bench.credentials_path)
        return {"authenticated": False}

    @app.get("/api/projects")
    def project_list():
        return {"projects": bench.project_list()}

    @app.post("/api/projects")
    def create_project(body: ProjectInput):
        return bench.create_project(body.name, body.path, body.description, body.dataset_id)

    @app.get("/api/projects/{pid}")
    def project_detail(pid: str):
        return bench.detail(pid)

    @app.patch("/api/projects/{pid}")
    def edit_project(pid: str, body: ProjectEdit):
        return bench.update_project(pid, body.name, body.description)

    @app.get("/api/datasets")
    def datasets():
        return {"datasets": bench.datasets()}

    @app.get("/api/datasets/{dataset_id}")
    def describe_dataset(dataset_id: str):
        return bench.dataset_details(dataset_id)

    @app.post("/api/projects/{pid}/initialise")
    def initialise(pid: str, body: Initialise):
        return bench.initialise(pid, body.dataset_id, body.dummy_data).payload()

    @app.get("/api/projects/{pid}/cards")
    def cards(pid: str):
        return {"cards": starters.cards(bench.profile(pid)), "can_tailor": bench.ai_status()["configured"]}

    @app.post("/api/projects/{pid}/starters")
    def starter(pid: str, body: PlanInput):
        return notebook_view(starters.notebook(bench.project(pid)["path"], bench.profile(pid), body.analysis, body.fields))

    @app.get("/api/projects/{pid}/examples")
    def example_list(pid: str):
        return {"examples": examples.catalogue(pid)}

    @app.get("/api/projects/{pid}/examples/{eid}")
    def example_detail(pid: str, eid: str):
        return examples.detail(pid, eid)

    @app.post("/api/projects/{pid}/examples/{eid}/copy")
    def copy_example(pid: str, eid: str, body: CopyExample):
        return notebook_view(examples.clone(pid, eid, body.version, body.request_id))

    @app.post("/api/projects/{pid}/suggestions")
    def tailored_cards(pid: str):
        return assistant.suggest(bench, pid).payload()

    @app.post("/api/projects/{pid}/plans")
    def plan(pid: str, body: PlanInput):
        return bench.plan(pid, body.thread_id, body.analysis, body.fields)

    @app.post("/api/projects/{pid}/plans/{plan_id}/run")
    def run(pid: str, plan_id: str):
        return bench.run(pid, plan_id).payload()

    @app.get("/api/projects/{pid}/threads")
    def threads(pid: str):
        bench.project(pid)
        return {"threads": bench.store.threads(pid)}

    @app.get("/api/projects/{pid}/work")
    def recent_work(pid: str, archived: bool = False):
        bench.project(pid)
        return {"work": bench.store.recent_work(pid, archived=archived)}

    @app.post("/api/projects/{pid}/threads/{tid}/archive")
    def archive_thread(pid: str, tid: str, body: Archive):
        bench.project(pid)
        bench.store.thread(pid, tid)
        bench.store.archive(pid, tid, body.archived)
        return {"archived": body.archived}

    @app.post("/api/projects/{pid}/notebooks/{nid}/archive")
    def archive_notebook(pid: str, nid: str, body: Archive):
        bench.project(pid)
        if not bench.store.notebook(pid, nid)["revision"]:
            raise NotFound("Notebook not found in this project.")
        bench.store.archive(pid, "notebook:" + nid, body.archived)
        return {"archived": body.archived}

    @app.post("/api/projects/{pid}/threads")
    def new_thread(pid: str, body: Title):
        bench.project(pid)
        return bench.store.create_thread(pid, body.title)

    @app.get("/api/projects/{pid}/threads/{tid}")
    def thread(pid: str, tid: str):
        bench.project(pid)
        result = bench.store.thread(pid, tid)
        result["artifacts"] = [artifact_view(item) for item in result["artifacts"]]
        result["drafts"] = bench.store.objects(pid, "draft", tid)
        result["requests"] = bench.jobs.for_thread(pid, tid)
        spent = bench.store.usage(pid, tid, by_request=True)
        for item in result["messages"]:
            # A retried request shows everything its attempts spent together.
            item["usage"] = spent.get(item["request_id"]) if item["role"] == "assistant" else None
        result["usage"] = bench.store.usage(pid, tid)
        return result

    @app.patch("/api/projects/{pid}/threads/{tid}")
    def rename_thread(pid: str, tid: str, body: Title):
        bench.project(pid)
        bench.store.rename_thread(pid, tid, body.title)
        return {"saved": True}

    @app.post("/api/projects/{pid}/threads/{tid}/messages")
    def message(pid: str, tid: str, body: Question):
        selected = None
        if body.selected_cell:
            if not body.notebook_id:
                raise PublicError("Select a notebook before sharing a cell.")
            selected = repairs.selected(bench, pid, body.notebook_id, body.selected_cell.cell_id,
                                        body.selected_cell.context_digest,
                                        helper_cell_ids=body.selected_cell.helper_cell_ids)
        if body.field_choice:
            # The researcher picked a suggested column; remember their word for it.
            assistant.learn_field(bench, pid, body.field_choice.term, body.field_choice.path)
        return assistant.chat(bench, pid, tid, body.message.strip(), body.notebook_id,
                              selection=selected, request_id=body.request_id).payload()

    @app.get("/api/projects/{pid}/vocabulary")
    def vocabulary(pid: str):
        return {"vocabulary": assistant.vocabulary(bench, pid, bench.fields(pid))}

    @app.post("/api/projects/{pid}/vocabulary/forget")
    def forget_field(pid: str, body: ForgetField):
        bench.project(pid)
        return {"vocabulary": assistant.forget_field(bench, pid, body.term)}

    @app.get("/api/usage")
    def usage():
        return {"total": bench.store.usage(),
                "projects": [{"id": p["id"], "name": p["name"], "usage": bench.store.usage(p["id"])}
                             for p in bench.project_list()]}

    @app.post("/api/projects/{pid}/threads/{tid}/requests/{rid}/retry")
    def retry_message(pid: str, tid: str, rid: str, body: RetryQuestion):
        bench.project(pid)
        bench.store.thread(pid, tid)
        previous = bench.jobs.get(pid, rid)
        request = previous.metadata.get("request", {})
        if request.get("thread_id") != tid:
            raise NotFound("Request not found in this conversation.")
        selected = None
        if body.selected_cell:
            selected = repairs.selected(bench, pid, request["notebook_id"], body.selected_cell.cell_id,
                                        body.selected_cell.context_digest,
                                        helper_cell_ids=body.selected_cell.helper_cell_ids,
                                        purpose=(request.get("selection") or {}).get("purpose", "question"))
        return assistant.retry_chat(bench, pid, tid, rid, selection=selected).payload()

    @app.post("/api/projects/{pid}/notebooks/{nid}/cells/{cid}/context-preview")
    def cell_context(pid: str, nid: str, cid: str, body: ContextPreview):
        return repairs.preview(bench, pid, nid, cid, purpose="question",
                               helper_cell_ids=body.helper_cell_ids)

    @app.get("/api/projects/{pid}/research-context")
    def research_context(pid: str):
        bench.project(pid)
        return bench.store.setting("research:" + pid, {"goal": "", "fields": []})

    @app.put("/api/projects/{pid}/research-context")
    def save_research_context(pid: str, body: ResearchContext):
        available = {f["path"] for f in bench.fields(pid)}
        if any(field not in available for field in body.fields):
            raise PublicError("Choose fields from this dataset.")
        value = {"goal": body.goal.strip(), "fields": list(dict.fromkeys(body.fields))}
        check_outbound(json.dumps(value), bench.known_secrets())
        bench.store.set_setting("research:" + pid, value)
        return value

    @app.post("/api/projects/{pid}/threads/{tid}/notebook")
    def thread_notebook(pid: str, tid: str):
        bench.project(pid)
        nid = bench.store.thread_notebook(pid, tid)
        return notebook_view(bench.store.notebook(pid, nid))

    @app.post("/api/projects/{pid}/notebooks/{nid}/conversation")
    def notebook_conversation(pid: str, nid: str):
        bench.project(pid)
        return {"thread_id": bench.store.notebook_thread(pid, nid)}

    @app.post("/api/projects/{pid}/notebooks/{nid}/changes/{cid}/undo")
    def undo_cell(pid: str, nid: str, cid: str):
        bench.project(pid)
        return notebook_view(bench.store.undo_ai_cell(pid, nid, cid))

    @app.post("/api/projects/{pid}/notebooks/{nid}/cells/{cid}/repair-preview")
    def repair_preview(pid: str, nid: str, cid: str, body: Input):
        return repairs.preview(bench, pid, nid, cid)

    @app.post("/api/projects/{pid}/notebooks/{nid}/cells/{cid}/repair")
    def repair_cell(pid: str, nid: str, cid: str, body: Repair):
        return repairs.submit(bench, pid, nid, cid, body.context_digest).payload()

    @app.post("/api/projects/{pid}/drafts/{did}/apply")
    def apply_code(pid: str, did: str, body: ApplyCode):
        bench.project(pid)
        draft = bench.store.get(pid, "draft", did)
        tid = draft["thread_id"]
        nid = draft.get("notebook_id") or bench.store.thread_notebook(pid, tid)
        kind = draft.get("kind", "code")
        try:
            assistant.validate_cell_source(bench, draft["code"], draft["title"], kind)
        except (SyntaxError, TypeError, ValueError):
            raise PublicError("This code suggestion is not valid for a notebook cell.")
        target = draft.get("target_cell_id") if body.mode == "replace" else None
        if body.mode == "replace" and (not target or not draft.get("expected_digest")):
            raise PublicError("This suggestion has no existing cell to update. Add it as a new cell.")
        expected = {target: draft["expected_digest"]} if target else None
        change = bench.store.write_ai_cell(pid, nid, tid, draft["code"], draft["title"], kind, target, expected, draft_id=did)
        if not change.get("already_applied"):
            bench.audit(pid, "notebook.code_applied", {"notebook_id": nid, "draft_id": did, "change_id": change["change_id"], "status": change["status"]})
        return {"notebook": notebook_view(bench.store.notebook(pid, nid)), "change": change,
                "draft": bench.store.get(pid, "draft", did)}

    @app.post("/api/projects/{pid}/history/import")
    def import_history(pid: str):
        return bench.import_history(pid)

    @app.get("/api/projects/{pid}/artifacts")
    def artifacts(pid: str):
        bench.project(pid)
        return {"artifacts": [artifact_view(item) for item in bench.store.objects(pid, "artifact")]}

    @app.get("/api/projects/{pid}/artifacts/{aid}")
    def artifact(pid: str, aid: str):
        bench.project(pid)
        return artifact_view(bench.store.get(pid, "artifact", aid))

    @app.get("/api/projects/{pid}/jobs/{jid}")
    def job_status(pid: str, jid: str):
        bench.project(pid)
        return bench.jobs.get(pid, jid).payload()

    @app.get("/api/projects/{pid}/jobs")
    def active_jobs(pid: str):
        bench.project(pid)
        return {"jobs": bench.jobs.active(pid)}

    @app.post("/api/projects/{pid}/jobs/{jid}/cancel")
    def cancel_job(pid: str, jid: str):
        bench.project(pid)
        return {"requested": bench.jobs.cancel(pid, jid)}

    @app.get("/api/projects/{pid}/jobs/{jid}/events")
    async def job_events(pid: str, jid: str, request: Request):
        # Registry and job reads touch SQLite, which can wait on a lock. Keep
        # them off the event loop so one slow read cannot stall every request.
        def current():
            return bench.jobs.get(pid, jid).payload()
        await run_in_threadpool(bench.project, pid)
        await run_in_threadpool(current)  # Unknown project or task: 404 before streaming.

        async def events():
            last = ""
            while not await request.is_disconnected():
                payload = await run_in_threadpool(current)
                encoded = json.dumps(payload)
                if encoded != last:
                    yield "data: " + encoded + "\n\n"
                    last = encoded
                if payload["status"] in ("completed", "failed", "cancelled", "interrupted"):
                    break
                await asyncio.sleep(.25)
        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/api/settings/ai")
    def ai_status():
        return bench.ai_status()

    @app.post("/api/settings/ai")
    def configure_ai(body: AIInput):
        return bench.configure_ai(body.provider, body.model, body.base_url, body.api_key, body.persist)

    @app.get("/api/settings/ai/models")
    def ai_models(refresh: bool = False):
        return bench.ai_models(refresh=refresh)

    @app.post("/api/settings/ai/model")
    def choose_model(body: ModelChoice):
        return bench.set_model(body.model)

    @app.post("/api/settings/ai/price")
    def model_price(body: ModelPrice):
        return bench.set_price(body.model, body.input, body.output)

    @app.post("/api/settings/ai/cli")
    def cli_ai():
        return bench.use_cli_ai()

    @app.post("/api/settings/ai/test")
    def test_ai_connection(body: Input):
        return bench.test_ai_connection()

    @app.get("/api/runtime")
    def runtime():
        return runtime_status(wait=False)

    @app.get("/api/projects/{pid}/notebooks/{nid}/runtime")
    def notebook_runtime(pid: str, nid: str):
        bench.project(pid)
        return kernels.status(pid, nid)

    @app.get("/api/projects/{pid}/notebooks")
    def notebooks(pid: str):
        bench.project(pid)
        hidden = bench.store.archived(pid)
        return {"notebooks": [{"id": book["id"], "revision": book["revision"],
                               "title": book["thread_title"] or book.get("title") or "Research notebook"}
                              for book in bench.store.notebooks(pid)
                              if "notebook:" + book["id"] not in hidden and book["thread_id"] not in hidden]}

    @app.get("/api/projects/{pid}/notebooks/{nid}")
    def notebook(pid: str, nid: str):
        bench.project(pid)
        return notebook_view(bench.store.notebook(pid, nid))

    @app.put("/api/projects/{pid}/notebooks/{nid}")
    def save_notebook(pid: str, nid: str, body: Notebook):
        bench.project(pid)
        previous = bench.store.notebook(pid, nid)
        by_id = {cell["id"]: cell for cell in previous["cells"]}
        cells = []
        for cell in body.cells:
            # A cell without an id is new. Matching it by position would hand
            # it the id, output and AI provenance of whichever cell was there.
            old = by_id.get(cell.id, {}) if cell.id else {}
            unchanged = old.get("source") == cell.source and old.get("kind", "code") == cell.kind
            value = {"id": cell.id or "cell-" + identifier(),
                     "kind": cell.kind, "source": cell.source, "output": old.get("output") if unchanged else None}
            if old.get("ai"):
                value["ai"] = old["ai"]
            cells.append(value)
        return notebook_view(bench.store.save_notebook(pid, nid, cells, body.revision, title=body.title))

    @app.post("/api/projects/{pid}/notebooks/import")
    def notebook_import(pid: str, body: ImportNotebook):
        bench.project(pid)
        if body.kind not in ("artifact", "plan", "draft"):
            raise PublicError("Choose a saved analysis or code draft.")
        item = bench.store.get(pid, body.kind, body.object_id)
        nid = item["id"]
        current = bench.store.notebook(pid, nid)
        if current["revision"] == 0:
            current = bench.store.save_notebook(pid, nid, [{"kind": item.get("kind", "code"), "source": item["code"], "output": None}], 0)
        return notebook_view(current)

    @app.post("/api/projects/{pid}/notebooks/{nid}/execute")
    def execute(pid: str, nid: str, body: Execute):
        project = bench.project(pid)
        saved = bench.store.notebook(pid, nid)
        if saved["revision"] != body.revision or body.cell >= len(saved["cells"]):
            raise Conflict("Save the current notebook revision before executing it.")
        source = saved["cells"][body.cell]["source"]
        if saved["cells"][body.cell].get("kind") == "markdown":
            raise PublicError("Markdown cells are rendered when saved; run a Python cell to execute code.")
        runtime = runtime_status()
        if not runtime["available"]:
            raise PublicError(runtime["reason"])
        def work(job):
            job.emit("kernel", "Starting the isolated project notebook session…")
            kernel = kernels.get(pid, nid, project["path"])
            if load_digest(project["path"]) != kernel.input_digest:
                raise PublicError("The projection changed. Restart the kernel to load its new version.")
            job.emit("execute", "Executing saved source in the isolated notebook…")
            output = kernel.execute(source, job.cancel)
            result = bench.store.attach_execution(pid, nid, saved, body.cell, output)
            if result["notebook"]:
                result["notebook"] = notebook_view(result["notebook"])
            bench.audit(pid, "notebook.executed", {"notebook_id": nid, "image_id": kernel.image_id})
            return result
        return bench.jobs.submit(pid, "notebook", pid + ":notebook:" + nid, work).payload()

    @app.post("/api/projects/{pid}/notebooks/{nid}/stop")
    def stop_kernel(pid: str, nid: str):
        bench.project(pid)
        kernels.stop(pid, nid)
        bench.store.restart_notebook(pid, nid)
        return {"stopped": True, "source_preserved": True}

    @app.get("/api/projects/{pid}/notebooks/{nid}/runs")
    def notebook_runs(pid: str, nid: str, offset: int = Query(default=0, ge=0)):
        bench.project(pid)
        values = bench.store.runs(pid, nid, offset)
        for run in values:
            run["output"] = notebook_view({"cells": [{"source": run["source"], "output": run["output"]}]})["cells"][0]["output"]
        return {"runs": values, "next_offset": offset + 20 if len(values) == 20 else None}

    @app.get("/api/projects/{pid}/notebooks/{nid}/prepare-build")
    def prepare_build(pid: str, nid: str):
        """Return a review-only Python source candidate; never writes project files."""
        project = bench.project(pid)
        notebook = bench.store.notebook(pid, nid)
        code_cells = [(index + 1, cell) for index, cell in enumerate(notebook["cells"])
                      if cell.get("kind", "code") == "code" and cell.get("source", "").strip()]
        if not code_cells:
            raise PublicError("Add at least one Python cell before preparing a build review.")
        source_parts = []
        findings = []
        for number, cell in code_cells:
            source = cell["source"]
            source_parts.append(f"# Epsilon notebook cell {number}\n{source.rstrip()}\n")
            for line_number, line in enumerate(source.splitlines(), 1):
                if line.lstrip().startswith(("!", "%")):
                    findings.append({"level": "error", "blocking": True, "line": line_number,
                                     "message": "Notebook magics and shell commands are not supported by epsilon build."})
            findings.extend({"level": item.level, "blocking": item.blocking, "line": item.line,
                             "message": item.message} for item in check_source("notebook.py", source))
            findings.extend({"level": item.level, "blocking": item.blocking, "line": item.line,
                             "message": item.message} for item in scan_secrets("notebook.py", source))
        runtime = kernels.status(pid, nid)
        profile = bench.profile(pid)
        requirements = [p["name"] + ("==" + p["version"] if p.get("version") else "")
                        for p in runtime.get("packages", []) if p.get("name")]
        return {
            "notebook_id": nid,
            "revision": notebook["revision"],
            "script": "\n".join(source_parts),
            "findings": findings,
            "can_prepare": not any(item["blocking"] for item in findings),
            "provenance": {"dataset_id": profile.dataset_id, "archetype_id": profile.archetype_id,
                            "dataset_version": profile.dataset_version, "schema_hash": profile.schema_hash,
                            "input_digest": analysis.input_digest(project["path"]),
                            "runtime_image": runtime.get("image_id"), "python": runtime.get("python")},
            "requirements": requirements,
            "notice": "Review source and dependencies before using epsilon build. This action does not overwrite files, execute source or request TRE approval.",
        }

    @app.get("/api/projects/{pid}/notebooks/{nid}/export")
    def export_notebook(pid: str, nid: str):
        bench.project(pid)
        saved = bench.store.notebook(pid, nid)
        payload = {"nbformat": 4, "nbformat_minor": 5,
                   "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
                   "cells": [{"id": "cell-" + str(i), "cell_type": cell.get("kind", "code"), "metadata": {}, "source": cell["source"].splitlines(True),
                              **({"execution_count": None, "outputs": []} if cell.get("kind", "code") == "code" else {})} for i, cell in enumerate(saved["cells"])]}
        return Response(json.dumps(payload, indent=2), media_type="application/x-ipynb+json",
                        headers={"Content-Disposition": 'attachment; filename="epsilon-analysis.ipynb"'})

    @app.post("/api/projects/{pid}/artifacts/{aid}/checks")
    def check_artifact(pid: str, aid: str):
        bench.project(pid)
        item = bench.store.get(pid, "artifact", aid)
        findings = check_source("analysis.py", item["code"]) + scan_secrets("analysis.py", item["code"])
        return {"findings": [{"level": f.level, "message": f.message, "line": f.line, "blocking": f.blocking} for f in findings],
                "scope": "Selected synthetic preview source only", "tre_approval": "Not requested"}

    @app.get("/api/projects/{pid}/artifacts/{aid}/export")
    def export_analysis(pid: str, aid: str):
        bench.project(pid)
        item = bench.store.get(pid, "artifact", aid)
        # A review package is deliberately distinct from epsilon build's
        # deployment manifest; it makes no claim of coordinator acceptance.
        manifest = {"format": "epsilon-analysis-review-v1", "title": item["title"],
                    "dataset_id": item["dataset_id"], "archetype_id": item["archetype_id"],
                    "dataset_version": item["dataset_version"], "schema_hash": item["schema_hash"],
                    "input_digest": item["input_digest"], "code_digest": item["code_digest"],
                    "engine_version": item["engine_version"], "synthetic_preview": True,
                    "tre_approval": "Not requested", "files": ["analysis.py", "manifest.json", "README.txt"]}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("analysis.py", item["code"])
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("README.txt", "Epsilon analysis review package.\nRun the source from the matching synthetic project directory.\nThis is not a TRE submission. Adapt and validate the method with the TRE's approved SDK/build workflow.\nNo dataset rows, notebook outputs, credentials or chat transcripts are included.\n")
        bench.audit(pid, "review.exported", {"artifact_id": aid})
        return Response(stream.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="epsilon-analysis-review.zip"'})

    @app.get("/assets/{name}")
    def assets(name: str):
        if name not in ("app.js", "assistant-controls.js", "auth-return.js", "datasets.js", "notebook.js", "workspace.js", "pages.js", "examples.js", "repairs.js", "interactions.js", "jobs.js", "usage.js", "core.js", "styles.css"):
            raise HTTPException(404)
        return FileResponse(ASSETS / name)

    @app.get("/")
    @app.get("/projects")
    @app.get("/projects/{pid}")
    @app.get("/projects/{pid}/{view}")
    @app.get("/projects/{pid}/{view}/{item_id}")
    @app.get("/settings")
    @app.get("/signin")
    def page():
        return FileResponse(ASSETS / "index.html", media_type="text/html")

    return app


def load_digest(project_dir):
    return analysis.input_digest(project_dir)
