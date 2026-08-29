"""
A local web interface for the copilot.

Runs on the researcher's own machine, beside their project, for the same
reason the CLI does: the model, the synthetic data and the project files stay
where they already are. Nothing is served to anyone else -- the server binds to
loopback only.

Standard library only. A researcher should not need a node toolchain to see
what their dataset supports.
"""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from sdk import catalogue as catalogue_mod
from sdk import checks as checks_mod
from sdk.profile import Profile

DEFAULT_PORT = 7878


def dataset_payload(profile: Profile) -> Dict[str, Any]:
    """Everything the page needs to describe the dataset."""
    # A projection is what the researcher received: the source record had more
    # columns and at least one identifier, none of which reach this machine.
    fields = []
    for leaf in profile.all_leaves():
        fields.append({
            "path": leaf.path,
            "type": leaf.type,
            "access": leaf.access_level,
            "releasableAs": leaf.releasable_as,
            "cardinality": leaf.cardinality,
            "coverage": leaf.coverage,
            "range": leaf.value_range,
            "categories": leaf.categories[:6],
            "caveats": leaf.caveats,
        })
    return {
        "ready": True,
        "title": profile.title,
        "schemaHash": (profile.schema_hash or "")[:12] or None,
        "archetype": profile.archetype_id,
        "rows": profile.grain.rows,
        "unit": profile.grain.label,
        "hasEntityKey": profile.has_dedupe_key,
        "minCell": profile.min_cell,
        "fields": fields,
        "notes": profile.caveats,
        "granted": len(fields),
        "stripped": [
            "every direct identifier",
            "every column outside the archetype",
        ],
    }


def analyses_payload(profile: Profile) -> Dict[str, Any]:
    out = []
    for match in catalogue_mod.evaluate(profile):
        out.append({
            "key": match.key,
            "title": match.title,
            "status": match.status,
            "summary": match.summary,
            "unit": match.unit,
            "params": match.params,
            "blockers": match.blockers,
            "warnings": match.warnings,
            "unlock": match.unlock,
            "command": match.command,
        })
    return {"analyses": out}


def checks_payload(project_dir: str) -> Dict[str, Any]:
    findings = checks_mod.check_project(project_dir)
    return {
        "summary": checks_mod.summarise(findings),
        "findings": [{
            "level": f.level, "path": f.path, "line": f.line,
            "message": f.message, "fix": f.fix,
        } for f in findings],
    }


def status_payload(profile: Optional[Profile], project_dir: str) -> Dict[str, Any]:
    """Where the researcher is, read off the machine and the project.

    Every step is detected rather than remembered, so doing one in the terminal
    and reloading loses nothing, and a half-finished setup is picked up exactly
    where it stopped.
    """
    import glob

    home = os.path.expanduser("~")
    credentials = os.path.join(home, ".epsilon_sdk", "credentials.ini")

    model = None
    try:
        from sdk.llm import config as ai_config
        cfg = ai_config.load()
        if cfg.configured:
            model = {"provider": cfg.provider, "model": cfg.model,
                     "tier": cfg.tier, "source": cfg.key_source}
    except Exception:
        model = None

    analyses = []
    findings = []
    if profile is not None:
        analyses = sorted(
            os.path.basename(f) for f in
            glob.glob(os.path.join(project_dir, "analyses", "*.py"))
            if not os.path.basename(f).startswith("_"))
        findings = checks_mod.check_project(project_dir)
    blocking = [f for f in findings if f.blocking]

    steps = [
        {"key": "install", "title": "Install the SDK",
         "cmd": "pip install 'epsilon-sdk[copilot]'",
         "desc": "The copilot extra adds the OS keyring the assistant stores "
                 "your model key in.",
         "done": True,
         "note": "Running, so it is installed."},
        {"key": "login", "title": "Authenticate",
         "cmd": "epsilon login",
         "desc": "The token lands in ~/.epsilon_sdk, never in your project.",
         "done": os.path.exists(credentials),
         "note": "Credentials found." if os.path.exists(credentials)
                 else "Run this in a terminal, then reload."},
        {"key": "datasets", "title": "Find a dataset",
         "cmd": "epsilon datasets",
         "desc": "Lists what your access grants, with the archetype each one "
                 "is projected through.",
         "done": profile is not None,
         "note": "Pick one, then initialise it."},
        {"key": "init", "title": "Initialise the project",
         "cmd": "epsilon init <dataset_id>",
         "desc": "Downloads the archetype-scoped projection and the synthetic "
                 "data, generates typed models, and pins the schema hash.",
         "done": profile is not None,
         "note": ("{0} rows measured.".format(format(profile.grain.rows or 0, ","))
                  if profile else "Run this in a terminal, then reload.")},
        {"key": "model", "title": "Point the assistant at a model",
         "cmd": "epsilon ai login",
         "desc": "Bring your own key. Stored in the OS keyring; calls go from "
                 "this machine straight to the endpoint.",
         "done": model is not None,
         "note": ("{0} · {1}".format(model["provider"], model["model"])
                  if model else "Only the assistant needs this. "
                                "Everything else works without it."),
         "optional": True},
    ]

    return {
        "steps": steps,
        "hasProject": profile is not None,
        "model": model,
        "analyses": analyses,
        "blocking": len(blocking),
        "warnings": len(findings) - len(blocking),
        "built": os.path.isdir(os.path.join(project_dir, "build")),
    }


def projects_payload(space) -> Dict[str, Any]:
    """Every project this researcher has registered, recent first."""
    from sdk import projects as registry

    open_id = space.project.id if space.project else None
    out = []
    for project in registry.recent():
        out.append({
            "id": project.id, "name": project.name,
            "description": project.description, "path": project.path,
            "exists": project.exists, "initialised": project.initialised,
            "opened": project.opened, "open": project.id == open_id,
        })
    return {"projects": out, "openId": open_id,
            "openPath": space.project_dir, "registered": space.project is not None}


def cards_payload(space, refresh: bool = False,
                  fast: bool = False) -> Dict[str, Any]:
    """The analyses worth running here, as the page draws them.

    `fast` skips the model: the catalogue answers instantly, and the page
    asks again for model suggestions once it has something on screen. A model
    call must never sit between the researcher and the page.
    """
    if not space.ready:
        return {"cards": [], "ready": False, "suggested": False,
                "canSuggest": False}

    from sdk import llm
    can_suggest = llm.available()
    if fast:
        cards, suggested = space.fallback_cards(), False
    else:
        cards, suggested = space.cards(refresh=refresh), can_suggest
    return {
        "ready": True,
        # Whether a model proposed these or the catalogue alone did. The page
        # says which, so a researcher is never told a machine suggested
        # something it did not.
        "suggested": suggested,
        "canSuggest": can_suggest,
        "cards": [{
            "title": c.title, "question": c.question,
            "why": c.why, "analysis": c.analysis, "fields": c.fields,
            "warnings": c.warnings,
        } for c in cards],
    }


def project_route(space, path, body):
    """The project screens, shared by both servers.

    Returns (payload, status). Every decision about what a project is lives
    here, so the stdlib server and the mounted app cannot drift apart.
    """
    from sdk import projects as registry

    if path == "/api/projects/new":
        try:
            project = registry.add(
                body.get("name", ""), body.get("path", ""),
                body.get("description", ""))
        except registry.ProjectError as exc:
            return {"error": str(exc)}, 400
        space.open(project.id)
        return {"project": project.to_json(),
                "ready": space.ready}, 200

    if path == "/api/projects/open":
        project = space.open(body.get("id", ""))
        if project is None:
            return {"error": "No such project."}, 404
        return {"project": project.to_json(),
                "ready": space.ready}, 200

    if path == "/api/projects/forget":
        if not registry.remove(body.get("id", "")):
            return {"error": "No such project."}, 404
        return {"forgotten": True}, 200

    # A card, or a typed question, becomes a session.
    if path == "/api/handoff":
        seed = space.hand_off(body.get("card"))
    else:
        question = (body.get("question") or "").strip()
        seed = space.ask_seed(question) if question else None
    if seed is None:
        return {"error": "Nothing to open."}, 400
    return {"token": seed.token, "title": seed.title,
            "url": "/chat?seed=" + seed.token}, 200


def run_module(project_dir: str, module: str) -> Dict[str, Any]:
    """Run one analysis locally, the way `epsilon run` would."""
    import subprocess
    import sys

    name = os.path.basename(module)
    if not name.endswith(".py") or "/" in module or "\\" in module:
        return {"ok": False, "output": "invalid module name"}
    path = os.path.join(project_dir, "analyses", name)
    if not os.path.exists(path):
        return {"ok": False, "output": "{0} does not exist".format(name)}

    code = (
        "import json, sys\n"
        "sys.path.insert(0, '.')\n"
        "m = __import__('analyses.{0}', fromlist=['main'])\n"
        "print(json.dumps(m.main(), indent=2, default=str))\n"
    ).format(name[:-3])
    try:
        proc = subprocess.run([sys.executable, "-c", code], cwd=project_dir,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=120)
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "timed out after 120s"}
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    return {"ok": proc.returncode == 0,
            "output": (out if proc.returncode == 0 else err + out)[:12000]}


def generate(profile: Profile, project_dir: str, key: str) -> Dict[str, Any]:
    """Generate starter code, the way `epsilon snippet` would."""
    from sdk import snippets as snippets_mod

    spec = catalogue_mod.SPECS_BY_KEY.get(key)
    if spec is None:
        return {"ok": False, "message": "unknown analysis"}
    match = spec.evaluate(profile)
    if not match.feasible:
        return {"ok": False,
                "message": match.blockers[0] if match.blockers else "not available"}
    try:
        path = snippets_mod.write(profile, match, project_dir=project_dir)
    except snippets_mod.SnippetError as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "path": os.path.relpath(path, project_dir),
            "module": os.path.basename(path),
            "warnings": match.warnings}


def make_handler(space):
    """Build a request handler over a workspace.

    Every route reads the workspace at request time rather than closing over a
    project, so opening another cohort does not need a restart.
    """

    class Handler(BaseHTTPRequestHandler):
        # Silence the default stderr access log; the CLI prints its own line.
        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # The page is served to one local browser; nothing else may call in.
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: Dict[str, Any], code: int = 200) -> None:
            self._send(code, json.dumps(payload).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):
            path, _, query = self.path.partition("?")
            # The front door is the list of projects: you choose what you are
            # working on before anything describes it.
            if (path in ("/", "/index.html", "/projects")
                    or path.startswith("/projects/")):
                from sdk.projects_page import PAGE as PROJECTS_PAGE
                self._send(200, PROJECTS_PAGE.encode("utf-8"),
                           "text/html; charset=utf-8")
            elif path in ("/workspace", "/workspace/"):
                # The workspace describes one project, so the URL says which:
                # /workspace?p=<id>. Without the parameter it shows whatever
                # is already open, and with nothing open it has nothing to
                # describe.
                wanted = ""
                for part in query.split("&"):
                    if part.startswith("p="):
                        wanted = part[2:]
                if wanted and (space.project is None
                               or space.project.id != wanted):
                    space.open(wanted)
                if not wanted and space.project is not None:
                    self.send_response(302)
                    self.send_header("Location",
                                     "/workspace?p=" + space.project.id)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if not space.ready:
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/dataset":
                self._json(dataset_payload(space.profile) if space.ready
                           else {"ready": False})
            elif path == "/api/analyses":
                self._json(analyses_payload(space.profile) if space.ready
                           else {"analyses": []})
            elif path == "/api/checks":
                self._json(checks_payload(space.project_dir) if space.ready
                           else {"summary": "", "findings": []})
            elif path == "/api/status":
                self._json(status_payload(space.profile, space.project_dir))
            elif path == "/api/session":
                self._json({"chat": space.session is not None})
            elif path == "/api/projects":
                self._json(projects_payload(space))
            elif path == "/api/cards":
                # Suggesting costs a model call, so it is asked for, not
                # implied by loading the page.
                self._json(cards_payload(space, refresh="refresh=1" in query,
                                         fast="fast=1" in query))
            elif path == "/chat" or path.startswith("/chat/"):
                # This server runs when the chat extra is not installed, so
                # say that, rather than handing a researcher raw JSON.
                page = (
                    "<!doctype html><meta charset='utf-8'>"
                    "<title>Epsilon chat</title>"
                    "<body style=\"font-family:system-ui;background:#f4f2ee;"
                    "color:#1c1b19;display:grid;place-items:center;"
                    "height:100vh;margin:0\"><div style=\"max-width:34rem;"
                    "padding:2rem\"><h1 style=\"font-size:1.3rem\">The chat "
                    "is not installed here</h1><p>Sessions need the chat "
                    "extra:</p><pre style=\"background:#efece6;padding:0.8rem "
                    "1rem;border-radius:8px\">pip install 'epsilon-sdk"
                    "[copilot,chat]'</pre><p>Then run <code>epsilon start"
                    "</code> again. <a href=\"/\">Back to projects</a>.</p>"
                    "</div></body>")
                self._send(200, page.encode("utf-8"),
                           "text/html; charset=utf-8")
            else:
                self._json({"error": "not found"}, 404)

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length))
            except (ValueError, TypeError):
                return None

        def do_POST(self):
            if self.path in ("/api/run", "/api/generate"):
                body = self._body()
                if body is None:
                    self._json({"error": "bad request"}, 400)
                    return
                if self.path == "/api/run":
                    self._json(run_module(space.project_dir,
                                          body.get("module", "")))
                else:
                    self._json(generate(space.profile, space.project_dir,
                                        body.get("analysis", "")))
                return

            if self.path in ("/api/projects/new", "/api/projects/open",
                             "/api/projects/forget", "/api/ask", "/api/handoff"):
                body = self._body()
                if body is None:
                    self._json({"error": "bad request"}, 400)
                    return
                self._json(*project_route(space, self.path, body))
                return

            if self.path != "/api/chat":
                self._json({"error": "not found"}, 404)
                return
            if space.session is None:
                self._json({"error": "No model is configured. Run "
                                     "'epsilon ai login', or use the panels "
                                     "above -- they need no model."}, 400)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                message = json.loads(self.rfile.read(length))["message"]
            except (ValueError, KeyError, TypeError):
                self._json({"error": "bad request"}, 400)
                return

            steps = []
            try:
                reply = space.session.ask(message,
                                    on_step=lambda s: steps.append(
                                        {"kind": s.kind, "label": s.label}))
            except Exception as exc:
                self._json({"error": "{0}: {1}".format(type(exc).__name__, exc)}, 500)
                return
            charts = (list(space.session.box.charts)
                      if space.session.box else [])
            self._json({"reply": reply, "steps": steps, "charts": charts})

    return Handler


def serve(profile: Optional[Profile], project_dir: str = ".", session=None,
          port: int = DEFAULT_PORT, open_browser: bool = True, space=None):
    """Serve the interface on loopback until interrupted."""
    from sdk.workspace import Workspace
    if space is None:
        space = Workspace(project_dir, profile, session)
    handler = make_handler(space)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = "http://127.0.0.1:{0}/".format(port)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    return server, url


def build_page() -> str:
    """Assemble the workspace page from the design's markup and our runtime."""
    from sdk import ui_page

    return (
        "<!doctype html>\n<html lang=\"en\"><head>\n"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        "<title>Epsilon workspace</title>\n"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">\n"
        "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>\n"
        "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?"
        "family=IBM+Plex+Sans:wght@400;500;600&"
        "family=IBM+Plex+Mono:wght@400;500;600&display=swap\">\n"
        "<style>" + ui_page.STYLE + "</style>\n"
        "</head><body><div id=\"root\"></div>\n<script>\n"
        "const MARKUP = " + _js_string(_livewire(ui_page.MARKUP)) + ";\n"
        # renderVals is authored as a method; make it a function expression
        # so it can be attached to the runtime's prototype unchanged.
        "const RENDER_VALS_FN = " + _strip_fixtures(
            ui_page.RENDER_VALS.replace("renderVals()", "function()", 1)) + ";\n"
        + ui_page.RUNTIME +
        "\n</script></body></html>\n"
    )


# The design ships sample content as fall-backs inside its own derivation.
# The runtime overrides all of it, but a bug there would surface invented
# column names and row counts as though they were measured. Emptying them at
# build time makes that impossible rather than unlikely.
_FIXTURES = [
    ("const stripped = ['patient_id', 'mrn', 'admission_id', 'site_id', "
     "'notes.text', 'clinician_id'];", "const stripped = [];"),
    ("['patient.gender', 'admissions.type', '+ 8 more']", "[]"),
]


def _strip_fixtures(js: str) -> str:
    for old, new in _FIXTURES:
        js = js.replace(old, new)
    # Any remaining single-quoted string naming the mockup's dataset, its row
    # count or its archetype is sample copy; empty it rather than let it show.
    import re as _re
    js = _re.sub(r"'[^']*(?:nordic-icu-2019|icu_encounter_v3|41,208)[^']*'",
                 "''", js)
    return js


# The canvas is a mockup: its chat box is a styled div showing placeholder
# text, because a design does not need to accept typing. These substitutions
# make the decorative parts real while leaving every surrounding style intact.
_LIVE = [
    # The design assumed one flowing paragraph; a model returns lists and
    # short lines, which collapse without this.
    ('<div style="font-size: 14.5px; line-height: 1.68; color: #26241f; '
     'text-wrap: pretty;">{{ b.text }}</div>',
     '<div style="font-size: 14.5px; line-height: 1.68; color: #26241f; '
     'text-wrap: pretty; white-space: pre-wrap;">{{ b.text }}</div>'),
    # The design's table is fixed at five columns; a real result has as many
    # as the analysis produced.
    ('<div style="display: grid; grid-template-columns: 1.3fr repeat(4, '
     'minmax(0, 1fr)); gap: 0;">',
     '<div style="display: grid; grid-template-columns: {{ b.grid }}; gap: 0;">'),
    # The chart block is authored for one fixed example; make it carry the
    # series of the message it belongs to.
    ('<sc-for list="{{ chartGroups }}" as="g" hint-placeholder-count="4">',
     '<sc-for list="{{ b.groups }}" as="g" hint-placeholder-count="4">'),
    ("Admissions by type and gender", "{{ b.title }}"),
    ("analyses/_charts.py &rarr; SVG", "{{ b.caption }}"),
    ("Projection you received &mdash; 10 columns",
     "Projection you received &mdash; {{ grantedCount }} columns"),
    ('<div style="flex: 1; font-size: 13.5px; color: #a8a39a;">{{ inputHint }}</div>',
     '<input id="ask" placeholder="{{ inputHint }}" autocomplete="off" '
     'style="flex: 1; font-family: inherit; font-size: 13.5px; border: 0; '
     'outline: none; background: transparent; color: #33302b;">'),
]


def _livewire(markup: str) -> str:
    for old, new in _LIVE:
        if old not in markup:
            raise RuntimeError(
                "the design changed and this substitution no longer applies: "
                + old[:60])
        markup = markup.replace(old, new)
    return markup


def _js_string(text: str) -> str:
    """Embed arbitrary markup as a JS string literal."""
    import json
    return json.dumps(text)


PAGE = build_page()
