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
from __future__ import annotations

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

    @app.get("/workspace", response_class=HTMLResponse)
    async def workspace_page():
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
        return {"chat": True}

    @app.get("/api/projects")
    async def projects():
        return ui_mod.projects_payload(space)

    @app.get("/api/cards")
    async def cards(refresh: int = 0):
        return ui_mod.cards_payload(space, refresh=bool(refresh))

    @app.post("/api/run")
    async def run(request: Request):
        body = await _body(request)
        return ui_mod.run_module(space.project_dir, body.get("module", ""))

    @app.post("/api/generate")
    async def generate(request: Request):
        body = await _body(request)
        return ui_mod.generate(space.profile, space.project_dir,
                               body.get("analysis", ""))

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


def mount(app, project_dir: str):
    """Attach the Chainlit chat at /chat."""
    from chainlit.utils import mount_chainlit

    target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "chat_app.py")
    # The chat measures whichever project the workspace has open unless a card
    # seeds it with another.
    os.environ.setdefault("EPSILON_PROJECT_DIR", project_dir)
    mount_chainlit(app=app, target=target, path=CHAT_PATH)
    return app


def serve(space: Workspace, port: int, open_browser: bool = True):
    """Run the whole workspace on one port. Blocks until interrupted."""
    import threading
    import webbrowser

    import uvicorn

    app = mount(build(space), space.project_dir)
    url = "http://127.0.0.1:{0}/".format(port)
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    config = uvicorn.Config(app, host="127.0.0.1", port=port,
                            log_level="warning")
    return uvicorn.Server(config), url
