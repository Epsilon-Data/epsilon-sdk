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


def make_handler(profile: Optional[Profile], project_dir: str, session):
    """Build a request handler bound to one project."""

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
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/dataset":
                self._json(dataset_payload(profile) if profile
                           else {"ready": False})
            elif self.path == "/api/analyses":
                self._json(analyses_payload(profile) if profile
                           else {"analyses": []})
            elif self.path == "/api/checks":
                self._json(checks_payload(project_dir) if profile
                           else {"summary": "", "findings": []})
            elif self.path == "/api/status":
                self._json(status_payload(profile, project_dir))
            elif self.path == "/api/session":
                self._json({"chat": session is not None})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path in ("/api/run", "/api/generate"):
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length))
                except (ValueError, TypeError):
                    self._json({"error": "bad request"}, 400)
                    return
                if self.path == "/api/run":
                    self._json(run_module(project_dir, body.get("module", "")))
                else:
                    self._json(generate(profile, project_dir,
                                        body.get("analysis", "")))
                return
            if self.path != "/api/chat":
                self._json({"error": "not found"}, 404)
                return
            if session is None:
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
                reply = session.ask(message,
                                    on_step=lambda s: steps.append(
                                        {"kind": s.kind, "label": s.label}))
            except Exception as exc:
                self._json({"error": "{0}: {1}".format(type(exc).__name__, exc)}, 500)
                return
            self._json({"reply": reply, "steps": steps})

    return Handler


def serve(profile: Optional[Profile], project_dir: str = ".", session=None,
          port: int = DEFAULT_PORT, open_browser: bool = True):
    """Serve the interface on loopback until interrupted."""
    handler = make_handler(profile, project_dir, session)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = "http://127.0.0.1:{0}/".format(port)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    return server, url


PAGE = r'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Epsilon workspace</title>
<style>
:root{
  --bg:#f5f7f6;--surface:#fff;--surface-2:#edf1ef;
  --ink:#141d1b;--ink-2:#4c5c58;--ink-3:#7c8c87;
  --rule:#dbe2df;--accent:#0d6b60;--accent-soft:#e1efeb;
  --warn:#8e5b0c;--warn-soft:#f6ecd9;--stop:#a03728;--stop-soft:#f7e5e1;
  --ok:#2c6b3b;--ok-soft:#e2efe4;
  --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
}
@media(prefers-color-scheme:dark){:root{
  --bg:#0e1413;--surface:#161e1c;--surface-2:#1c2523;
  --ink:#e7eeeb;--ink-2:#9daea9;--ink-3:#75857f;
  --rule:#26302e;--accent:#5ac3b2;--accent-soft:#153029;
  --warn:#d9a45c;--warn-soft:#2c2417;--stop:#e58c7c;--stop-soft:#301c19;
  --ok:#83c392;--ok-soft:#18291c;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55}
.wrap{max-width:900px;margin:0 auto;padding:0 20px 70px}
header{padding:30px 0 14px;display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
h1{margin:0;font-size:20px;letter-spacing:-.01em}
.sub{font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-top:5px}
nav{display:flex;gap:2px;background:var(--surface-2);border-radius:6px;padding:3px;
  margin:6px 0 18px}
nav button{flex:1;font:inherit;font-size:13px;font-weight:600;padding:7px 12px;border:0;
  border-radius:4px;background:none;color:var(--ink-3);cursor:pointer}
nav button.on{background:var(--surface);color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.06)}
nav button:disabled{opacity:.4;cursor:default}

.card{background:var(--surface);border:1px solid var(--rule);border-radius:6px;
  padding:14px 16px;margin-top:10px}
.card.now{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
h2{font-size:13px;font-family:var(--mono);letter-spacing:.12em;text-transform:uppercase;
  color:var(--ink-3);font-weight:500;margin:26px 0 6px}
h3{margin:0;font-size:15px;font-weight:600}
p{margin:0}
.msg{font-size:12.5px;color:var(--ink-3);margin-top:6px}
.msg.bad{color:var(--stop)}

.steprow{display:flex;align-items:center;gap:11px}
.num{width:22px;height:22px;border-radius:50%;flex:none;display:grid;place-items:center;
  font-family:var(--mono);font-size:11px;font-weight:700;background:var(--surface-2);color:var(--ink-3)}
.card.done .num{background:var(--ok-soft);color:var(--ok)}
.card.now .num{background:var(--accent);color:var(--bg)}
.tail{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--ink-3)}
.card.done .tail{color:var(--ok)}

.cmd{display:flex;align-items:center;gap:8px;margin-top:10px;background:var(--surface-2);
  border-radius:5px;padding:8px 10px}
.cmd code{flex:1;font-family:var(--mono);font-size:12.5px;color:var(--ink);
  overflow-x:auto;white-space:nowrap}
.copy{font:inherit;font-family:var(--mono);font-size:11px;padding:4px 9px;border:1px solid var(--rule);
  border-radius:4px;background:var(--surface);color:var(--ink-2);cursor:pointer;flex:none}
.copy:hover{border-color:var(--accent);color:var(--accent)}
.copy.did{background:var(--ok-soft);color:var(--ok);border-color:var(--ok-soft)}

.grain{background:var(--surface-2);border-left:3px solid var(--accent);border-radius:5px;
  padding:12px 14px}
.grain b{display:block;font-size:15px}
.grain .n{font-family:var(--mono);font-size:12px;color:var(--ink-2)}
.grain .no{color:var(--warn);font-family:var(--mono);font-size:12px;display:block;margin-top:5px}

.split{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
.side{border-radius:5px;padding:12px 14px}
.side.gone{background:var(--stop-soft);border:1px dashed var(--stop)}
.side.have{background:var(--ok-soft);border:1px solid var(--rule)}
.side h4{margin:0 0 7px;font-size:12.5px;font-family:var(--mono);letter-spacing:.06em;
  text-transform:uppercase}
.side.gone h4{color:var(--stop)}
.side.have h4{color:var(--ok)}
.side ul{margin:0;padding-left:16px;font-size:12.5px;color:var(--ink-2)}
.side .cols{font-family:var(--mono);font-size:11.5px;color:var(--ink-2);line-height:1.7}

table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
th{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-3);font-weight:500;text-align:left;padding:7px 10px;background:var(--surface-2)}
td{padding:7px 10px;border-top:1px solid var(--rule);color:var(--ink-2)}
td.p{font-family:var(--mono);font-size:12px;color:var(--ink)}
td .cav{color:var(--warn);font-size:11.5px;display:block;margin-top:2px}

.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{font-family:var(--mono);font-size:11px;padding:4px 9px;border-radius:4px}
.chip.y{background:var(--ok-soft);color:var(--ok)}
.chip.n{background:var(--stop-soft);color:var(--stop)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:9px;margin-top:10px}
.acard{border:1px solid var(--rule);border-radius:5px;padding:11px 13px;background:var(--bg)}
.acard.no{border-style:dashed;opacity:.9}
.acard h3{font-size:13.5px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.acard p{font-size:12px;color:var(--ink-3);line-height:1.45;margin-top:4px}
.acard p.why{color:var(--stop)}
.acard .unlock{font-size:11.5px;color:var(--ink-3);margin-top:6px;display:block}
button.go{font:inherit;font-size:13px;font-weight:600;padding:7px 13px;border:1px solid var(--accent);
  border-radius:5px;background:var(--accent);color:var(--bg);cursor:pointer}
button.plain{font:inherit;font-size:13px;font-weight:600;padding:7px 13px;border:1px solid var(--rule);
  border-radius:5px;background:var(--surface);color:var(--ink);cursor:pointer}
.acard button{margin-top:9px;width:100%}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}
select{font:inherit;font-size:13px;padding:7px 10px;border:1px solid var(--rule);
  border-radius:5px;background:var(--bg);color:var(--ink)}
pre{background:var(--surface-2);border-radius:5px;padding:11px 13px;overflow-x:auto;
  font-family:var(--mono);font-size:11.5px;color:var(--ink-2);margin:10px 0 0;
  max-height:300px;white-space:pre-wrap;position:relative}
.diag{font-family:var(--mono);font-size:12px;margin-top:10px}
.diag div{padding:3px 0}
.diag .b{color:var(--stop)} .diag .w{color:var(--warn)} .diag .g{color:var(--ok)}

#log{max-height:44vh;overflow-y:auto}
.turn{padding:9px 0;border-top:1px solid var(--rule)}
.turn:first-child{border-top:0}
.who{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-3);margin-bottom:4px}
.turn .t{white-space:pre-wrap;font-size:13.5px;color:var(--ink-2)}
.steps{font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-bottom:5px}
form{display:flex;gap:8px;margin-top:10px}
input{flex:1;font:inherit;font-size:13.5px;padding:8px 11px;border:1px solid var(--rule);
  border-radius:5px;background:var(--bg);color:var(--ink)}
input:focus{outline:2px solid var(--accent);outline-offset:-1px}
.try{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.try button{font:inherit;font-size:12px;padding:5px 10px;border:1px solid var(--rule);
  border-radius:20px;background:var(--surface);color:var(--ink-2);cursor:pointer}
.try button:hover{border-color:var(--accent);color:var(--accent)}
.lock{text-align:center;padding:26px 16px;color:var(--ink-3)}
.lock b{display:block;color:var(--ink);font-size:15px;margin-bottom:6px}
@media(max-width:640px){.split{grid-template-columns:1fr}}
</style></head><body>
<div class="wrap">
  <header>
    <div><h1 id="title">Epsilon workspace</h1><div class="sub" id="sub"></div></div>
  </header>
  <nav>
    <button id="n0" class="on" onclick="go(0)">Set up</button>
    <button id="n1" onclick="go(1)">Dataset</button>
    <button id="n2" onclick="go(2)">Assistant</button>
  </nav>
  <div id="view"></div>
</div>

<script>
const $ = s => document.querySelector(s);
const esc = t => String(t == null ? "" : t)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const j = async (p, body) => (await fetch(p, body ? {
  method:"POST", headers:{"Content-Type":"application/json"},
  body: JSON.stringify(body)} : undefined)).json();

let D = {ready:false}, A = [], S = {steps:[]}, TAB = 0;

window.copy = (btn, text) => {
  navigator.clipboard.writeText(text).then(() => {
    const was = btn.textContent;
    btn.textContent = "copied"; btn.classList.add("did");
    setTimeout(() => { btn.textContent = was; btn.classList.remove("did"); }, 1200);
  });
};

const cmdBox = text =>
  '<div class="cmd"><code>' + esc(text) + '</code>' +
  '<button class="copy" onclick="copy(this, ' + JSON.stringify(text)
    .replace(/"/g, "&quot;") + ')">copy</button></div>';

function setup(){
  let firstOpen = false;
  return S.steps.map((s, i) => {
    const isNow = !s.done && !firstOpen && (firstOpen = true);
    return '<div class="card ' + (s.done ? "done" : isNow ? "now" : "") + '">' +
      '<div class="steprow"><span class="num">' + (s.done ? "✓" : i + 1) + '</span>' +
      '<h3>' + esc(s.title) + '</h3><span class="tail">' +
      (s.done ? "done" : s.optional ? "optional" : "") + '</span></div>' +
      '<p class="msg">' + esc(s.desc) + '</p>' +
      cmdBox(s.cmd) +
      '<p class="msg">' + esc(s.note) + '</p></div>';
  }).join("") +
  (D.ready ? '<div class="card"><p class="msg">Project is ready. ' +
    '<b>Dataset</b> shows what you have; <b>Assistant</b> answers questions about it.</p>' +
    '<div class="row"><button class="go" onclick="go(1)">See the dataset →</button></div></div>' : "");
}

function dataset(){
  if (!D.ready)
    return '<div class="card"><p class="msg">No project yet. Finish set-up first.</p></div>';
  const fields = D.fields.map(f => {
    let v = f.type;
    if (f.range) v = f.type + " " + f.range[0] + "–" + f.range[1];
    else if (f.categories.length) v = f.categories.join(", ") +
      (f.cardinality > f.categories.length ? ", …" : "");
    else if (f.cardinality) v = f.type + " (" + f.cardinality.toLocaleString() + ")";
    const chip = f.access === "DETAILED" ? "detailed"
      : ((f.releasableAs || []).join(" · ") || "aggregate");
    return '<tr><td class="p">' + esc(f.path) + '</td><td>' + esc(v) +
      (f.caveats.length ? '<span class="cav">! ' + esc(f.caveats[0]) + '</span>' : '') +
      '</td><td>' + esc(chip) + '</td><td>' +
      (f.coverage == null ? "—" : Math.round(f.coverage * 100) + "%") + '</td></tr>';
  }).join("");

  return '<div class="card"><div class="grain"><b>One row is a ' + esc(D.unit) + '</b>' +
    '<span class="n">' + (D.rows != null ? D.rows.toLocaleString() + " rows" : "") + '</span>' +
    (D.hasEntityKey ? "" : '<span class="no">No key groups rows back to a person or case — ' +
      'per-entity figures are not computable</span>') + '</div></div>' +

    '<h2>What you actually have</h2>' +
    '<div class="split">' +
      '<div class="side gone"><h4>Never reached this machine</h4><ul>' +
        D.stripped.map(x => '<li>' + esc(x) + '</li>').join("") +
      '</ul></div>' +
      '<div class="side have"><h4>Projection you received — ' + D.granted + ' columns</h4>' +
        '<div class="cols">' + D.fields.map(f => esc(f.path)).join("<br>") + '</div></div>' +
    '</div>' +
    '<p class="msg">The source record is projected down to the columns your archetype ' +
    'grants. Everything below was counted from that projection by <code>epsilon init</code> ' +
    '— nothing was authored by hand, so nothing can drift out of sync with the data.</p>' +

    '<h2>Granted columns, as measured</h2>' +
    '<div class="card"><table><thead><tr><th>Column</th><th>Measured</th>' +
    '<th>Access</th><th>Coverage</th></tr></thead><tbody>' + fields + '</tbody></table></div>' +
    (D.notes.length ? '<p class="msg">' + esc(D.notes[0]) + '</p>' : "") +

    '<h2>Feasibility — decided in code</h2>' +
    '<div class="chips">' + A.map(m =>
      '<span class="chip ' + (m.status === "FEASIBLE" ? "y" : "n") + '">' +
      (m.status === "FEASIBLE" ? "yes" : "no") + "  " + esc(m.key) + '</span>').join("") +
    '</div>' +
    '<p class="msg">Answered by <code>epsilon explain</code> from ordinary Python ' +
    'predicates. The assistant reaches the same predicates through a tool — it cannot ' +
    'overrule one.</p>' +

    '<h2>What you can build</h2>' + cards() +
    '<h2>Run and check</h2>' + runCheck();
}

function cards(){
  const card = m => '<div class="acard' + (m.status === "FEASIBLE" ? '' : ' no') + '">' +
    '<h3>' + esc(m.title) + '</h3>' +
    (m.status === "FEASIBLE"
      ? '<p>' + esc(m.summary) + '</p>' +
        '<button class="go" onclick="gen(\'' + m.key + '\')">Generate code</button>'
      : '<p class="why">' + esc(m.blockers[0] || "") + '</p>' +
        (m.unlock ? '<span class="unlock">' + esc(m.unlock) + '</span>' : '')) + '</div>';
  return '<div class="cards">' +
    A.filter(m => m.status === "FEASIBLE").map(card).join("") +
    A.filter(m => m.status !== "FEASIBLE").map(card).join("") +
    '</div><div id="genmsg"></div>';
}

function runCheck(){
  const run = S.analyses.length
    ? '<div class="row"><select id="mod">' +
      S.analyses.map(m => '<option>' + esc(m) + '</option>').join("") +
      '</select><button class="go" onclick="runIt()">Run on synthetic data</button>' +
      '<button class="plain" onclick="recheck()">Check</button></div>' +
      '<p class="msg">Runs locally against generated/data.csv. These are not results.</p>'
    : '<p class="msg">Generate an analysis above, then run it here.</p>';
  const state = S.blocking
    ? '<div class="diag"><div class="b">' + S.blocking + ' blocking issue' +
      (S.blocking === 1 ? '' : 's') + ' — this would not pass the gate</div></div>'
    : '<div class="diag"><div class="g">✓ checks passing</div></div>';
  return '<div class="card">' + run + state + '<div id="out"></div></div>';
}

const TRY = ["What can I compute with this dataset?",
             "Why can't I compute prevalence?",
             "Cross-tab the two categorical columns and run it"];

function assistant(){
  if (!D.ready)
    return '<div class="card"><div class="lock"><b>No project yet</b>' +
      'The assistant only answers about a dataset already initialised here. ' +
      'Finish set-up first.</div></div>';
  if (!S.model)
    return '<div class="card"><div class="lock"><b>Assistant needs a model</b>' +
      'Run <code>epsilon ai login</code> and reload. Your key stays in this ' +
      'machine\'s keyring and calls go straight to the endpoint — Epsilon never ' +
      'sees a prompt.</div>' + cmdBox("epsilon ai login") + '</div>';
  return '<div class="card"><p class="msg">' + esc(S.model.provider) + ' · ' +
    esc(S.model.model) + ' · key via ' + esc(S.model.source) +
    '<br>Transcript saved to .epsilon/chat/' +
    (D.schemaHash ? ', pinned to schema ' + esc(D.schemaHash) : '') + '</p>' +
    '<div id="log"></div>' +
    '<form id="f"><input id="q" autocomplete="off" ' +
    'placeholder="Ask anything about this dataset…"><button class="go">Ask</button></form>' +
    '<div class="try">' + TRY.map(t =>
      '<button onclick="ask2(' + JSON.stringify(t).replace(/"/g,"&quot;") +
      ')">' + esc(t) + '</button>').join("") + '</div></div>';
}

function render(){
  ["n0","n1","n2"].forEach((id, i) => {
    const b = $("#" + id);
    b.className = i === TAB ? "on" : "";
    b.disabled = i > 0 && !D.ready;
  });
  $("#view").innerHTML = [setup, dataset, assistant][TAB]();
  const f = $("#f");
  if (f) f.addEventListener("submit", e => { e.preventDefault(); ask2($("#q").value); });
}

window.go = t => { TAB = t; render(); };

async function refresh(){
  S = await j("/api/status");
  D = await j("/api/dataset");
  A = D.ready ? (await j("/api/analyses")).analyses : [];
  $("#title").textContent = D.ready ? D.title : "Epsilon workspace";
  $("#sub").textContent = D.ready
    ? [D.archetype && "archetype " + D.archetype,
       D.rows != null && D.rows.toLocaleString() + " rows",
       "suppression n < " + D.minCell].filter(Boolean).join("  ·  ")
    : "127.0.0.1 · loopback · nothing leaves this machine";
  render();
}

window.gen = async key => {
  const r = await j("/api/generate", {analysis:key});
  $("#genmsg").innerHTML = r.ok
    ? '<p class="msg">Wrote <code>' + esc(r.path) + '</code></p>'
    : '<p class="msg bad">' + esc(r.message) + '</p>';
  if (r.ok) { await refresh(); }
};

window.runIt = async () => {
  const m = $("#mod").value;
  $("#out").innerHTML = '<p class="msg">Running…</p>';
  const r = await j("/api/run", {module:m});
  $("#out").innerHTML = '<pre>' + esc(r.output) + '</pre>' +
    '<div class="row"><button class="copy" onclick="copy(this, ' +
    JSON.stringify(r.output).replace(/"/g,"&quot;") + ')">copy output</button></div>' +
    '<p class="msg">Synthetic data — these are not results.</p>';
};

window.recheck = async () => {
  const r = await j("/api/checks");
  $("#out").innerHTML = r.findings.length
    ? '<div class="diag">' + r.findings.map(f =>
        '<div class="' + (f.level === "BLOCK" ? "b" : "w") + '">' + f.level + "  " +
        esc(f.path) + (f.line ? ":" + f.line : "") + "  " + esc(f.message) +
        (f.fix ? '<br>&nbsp;&nbsp;&nbsp;→ ' + esc(f.fix) : "") + '</div>').join("") + '</div>'
    : '<div class="diag"><div class="g">✓ All checks passed</div></div>';
  await refresh();
};

window.ask2 = async text => {
  const q = (text || "").trim();
  if (!q) return;
  if (TAB !== 2) { TAB = 2; render(); }
  if ($("#q")) $("#q").value = "";
  add("you", esc(q));
  const pending = add("copilot", "…");
  const r = await j("/api/chat", {message:q});
  pending.innerHTML = '<div class="who">assistant</div>' +
    (r.steps && r.steps.length
      ? '<div class="steps">' + r.steps.map(s => "· " + esc(s.label)).join("<br>") + '</div>'
      : '') + '<div class="t">' + esc(r.reply || r.error) + '</div>' +
    '<div class="row"><button class="copy" onclick="copy(this, ' +
    JSON.stringify(r.reply || "").replace(/"/g,"&quot;") + ')">copy</button></div>';
  S = await j("/api/status");
};

function add(who, html){
  const el = document.createElement("div");
  el.className = "turn";
  el.innerHTML = '<div class="who">' + who + '</div><div class="t">' + html + '</div>';
  $("#log").appendChild(el);
  $("#log").scrollTop = $("#log").scrollHeight;
  return el;
}

refresh();
</script></body></html>
'''
