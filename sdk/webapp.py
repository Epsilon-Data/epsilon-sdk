"""
The workspace and the chat, on one port.

Named `webapp` rather than `app`: the package already exports `app`, the CLI's
Typer entry point, and `from sdk import app` would reach that instead of this.

The workspace is plain standard-library HTTP and needs nothing installed. The
chat is Chainlit, which brings FastAPI with it. When the chat extra is present
both are served from a single origin, so a card can open a session by
navigating to /chat and the token in the URL survives the trip.

Without the extra there is no app to build; `epsilon start` serves the
workspace alone, and says so.
"""
import json
import os
from typing import Any, Dict, Optional

from sdk import ui as ui_mod
from sdk.workspace import Workspace

CHAT_PATH = "/chat"


def available() -> bool:
    """Whether the chat extra is installed."""
    try:
        import chainlit  # noqa: F401
        import fastapi  # noqa: F401
    except Exception:
        return False
    return True


def build(space: Workspace):
    """A FastAPI app serving the workspace, with the chat mounted at /chat."""
    from fastapi import FastAPI, Request
    from fastapi.responses import (HTMLResponse, JSONResponse,
                                   RedirectResponse)

    app = FastAPI(title="Epsilon workspace", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    @app.get("/index.html", response_class=HTMLResponse)
    @app.get("/projects", response_class=HTMLResponse)
    async def projects_page():
        """The front door: what you are working on."""
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        return HTMLResponse(PROJECTS_PAGE)

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    async def project_detail(project_id: str):
        """The same page; it reads its project from the URL."""
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        return HTMLResponse(PROJECTS_PAGE)

    @app.get("/workspace", response_class=HTMLResponse)
    async def workspace_page(p: str = ""):
        # Only the project list is global; the workspace is always some
        # project's workspace, and the URL says whose.
        if p and (space.project is None or space.project.id != p):
            space.open(p)
        if not p and space.project is not None:
            return RedirectResponse("/workspace?p=" + space.project.id)
        if not space.ready:
            return RedirectResponse("/")
        return HTMLResponse(ui_mod.PAGE)

    @app.get("/api/dataset")
    async def dataset():
        return (ui_mod.dataset_payload(space.profile) if space.ready
                else {"ready": False})

    @app.get("/api/analyses")
    async def analyses():
        return (ui_mod.analyses_payload(space.profile) if space.ready
                else {"analyses": []})

    @app.get("/api/checks")
    async def checks():
        return (ui_mod.checks_payload(space.project_dir) if space.ready
                else {"summary": "", "findings": []})

    @app.get("/api/status")
    async def status():
        return ui_mod.status_payload(space.profile, space.project_dir)

    @app.get("/api/session")
    async def session():
        return {"chat": space.chat() is not None, "chainlit": True}

    @app.get("/assistant")
    async def assistant():
        """The workspace's Assistant screen: the Chainlit chat, told which
        project it is about."""
        if space.project is not None:
            return RedirectResponse("/chat?p=" + space.project.id)
        return RedirectResponse("/chat")

    @app.get("/api/projects")
    async def projects():
        return ui_mod.projects_payload(space)

    @app.get("/api/cards")
    async def cards(refresh: int = 0, fast: int = 0):
        return ui_mod.cards_payload(space, refresh=bool(refresh),
                                    fast=bool(fast))

    @app.post("/api/run")
    async def run(request: Request):
        body = await _body(request)
        return ui_mod.run_module(space.project_dir, body.get("module", ""))

    @app.post("/api/generate")
    async def generate(request: Request):
        body = await _body(request)
        return ui_mod.generate(space.profile, space.project_dir,
                               body.get("analysis", ""))

    @app.post("/api/chat")
    async def chat(request: Request):
        """The workspace page's assistant -- same contract as the stdlib
        server: {reply, steps, charts}, or {error} with a reason."""
        import asyncio

        body = await _body(request)
        message = (body.get("message") or "").strip()
        if not message:
            return JSONResponse({"error": "bad request"}, status_code=400)
        session = space.chat()
        if session is None:
            return JSONResponse(
                {"error": "No model is configured. Run 'epsilon ai login', "
                          "or use the panels above -- they need no model."},
                status_code=400)

        steps = []

        def work():
            return session.ask(message, on_step=lambda s: steps.append(
                {"kind": s.kind, "label": s.label}))

        try:
            reply = await asyncio.get_running_loop().run_in_executor(None, work)
        except Exception as exc:
            return JSONResponse(
                {"error": "{0}: {1}".format(type(exc).__name__, exc)},
                status_code=500)
        charts = list(session.box.charts) if session.box else []
        return {"reply": reply, "steps": steps, "charts": charts}

    @app.post("/api/projects/new")
    @app.post("/api/projects/open")
    @app.post("/api/projects/forget")
    @app.post("/api/handoff")
    @app.post("/api/ask")
    async def project_routes(request: Request):
        body = await _body(request)
        payload, code = ui_mod.project_route(space, request.url.path, body)
        return JSONResponse(payload, status_code=code)

    async def _body(request: Request) -> Dict[str, Any]:
        try:
            return await request.json()
        except Exception:
            return {}

    return app


def _materialise_elements() -> None:
    """Put the chat's custom elements where Chainlit will look for them.

    Chainlit resolves `public/elements/<Name>.jsx` from the directory the
    server runs in -- the researcher's project -- while the elements ship
    inside this package. Copy them over at start-up, so a chart renders
    instead of "File not found".
    """
    import shutil

    source = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "elements")
    if not os.path.isdir(source):
        return
    root = os.environ.get("CHAINLIT_APP_ROOT", os.getcwd())
    target = os.path.join(root, "public", "elements")
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(source):
        if not name.endswith(".jsx"):
            continue
        src_path = os.path.join(source, name)
        dst_path = os.path.join(target, name)
        try:
            with open(src_path, "rb") as fh:
                wanted = fh.read()
            current = b""
            if os.path.exists(dst_path):
                with open(dst_path, "rb") as fh:
                    current = fh.read()
            if current != wanted:
                shutil.copyfile(src_path, dst_path)
        except OSError:
            # A read-only project directory loses the chart, not the chat.
            pass


def mount(app, project_dir: str):
    """Attach the Chainlit chat at /chat."""
    from chainlit.utils import mount_chainlit

    _materialise_elements()
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "chat_app.py")
    # The chat measures whichever project the workspace has open unless a card
    # seeds it with another.
    os.environ.setdefault("EPSILON_PROJECT_DIR", project_dir)
    mount_chainlit(app=app, target=target, path=CHAT_PATH)
    return app


def serve(space: Workspace, port: int, open_browser: bool = True):
    """Run the whole workspace on one port. Blocks until interrupted."""
    import socket
    import threading
    import webbrowser

    import uvicorn

    # uvicorn logs a bind failure and returns instead of raising, which
    # leaves the caller thinking a server is up. Claim the port first so a
    # clash surfaces as the OSError the CLI already knows how to explain.
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()

    app = mount(build(space), space.project_dir)
    url = "http://127.0.0.1:{0}/".format(port)
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    config = uvicorn.Config(app, host="127.0.0.1", port=port,
                            log_level="warning")
    return uvicorn.Server(config), url
