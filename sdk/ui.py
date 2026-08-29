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

DEFAULT_PORT = 8787


def dataset_payload(profile: Profile) -> Dict[str, Any]:
    """Everything the page needs to describe the dataset."""
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
        "title": profile.title,
        "archetype": profile.archetype_id,
        "rows": profile.grain.rows,
        "unit": profile.grain.label,
        "hasEntityKey": profile.has_dedupe_key,
        "minCell": profile.min_cell,
        "fields": fields,
        "notes": profile.caveats,
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


def status_payload(profile: Profile, project_dir: str) -> Dict[str, Any]:
    """Where the researcher is in the workflow, read off the project.

    The steps mirror the README so the browser and the terminal tell the same
    story; each one is detected rather than remembered, so closing the page or
    doing a step in the terminal loses nothing.
    """
    import glob

    credentials = os.path.join(
        os.path.expanduser("~"), ".epsilon_sdk", "credentials.ini")
    analyses = sorted(
        os.path.basename(p) for p in
        glob.glob(os.path.join(project_dir, "analyses", "*.py"))
        if not os.path.basename(p).startswith("_"))
    findings = checks_mod.check_project(project_dir)
    blocking = [f for f in findings if f.blocking]

    return {
        "signedIn": os.path.exists(credentials),
        "hasProject": os.path.exists(os.path.join(project_dir, "project.yml")),
        "analyses": analyses,
        "checksRun": bool(findings) or True,
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


def make_handler(profile: Profile, project_dir: str, session):
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
                self._json(dataset_payload(profile))
            elif self.path == "/api/analyses":
                self._json(analyses_payload(profile))
            elif self.path == "/api/checks":
                self._json(checks_payload(project_dir))
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


def serve(profile: Profile, project_dir: str = ".", session=None,
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
<title>Epsilon copilot</title>
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
.wrap{max-width:860px;margin:0 auto;padding:0 20px 60px}
header{padding:34px 0 18px}
h1{margin:0;font-size:21px;letter-spacing:-.01em}
.sub{font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-top:6px}

.step{background:var(--surface);border:1px solid var(--rule);border-radius:6px;
  margin-top:10px;overflow:hidden}
.step.now{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.step > .head{display:flex;align-items:center;gap:12px;padding:13px 16px;cursor:pointer;
  user-select:none}
.step > .head:hover{background:var(--surface-2)}
.num{width:23px;height:23px;border-radius:50%;flex:none;display:grid;place-items:center;
  font-family:var(--mono);font-size:11px;font-weight:700;
  background:var(--surface-2);color:var(--ink-3)}
.step.done .num{background:var(--ok-soft);color:var(--ok)}
.step.now .num{background:var(--accent);color:var(--bg)}
.head h2{margin:0;font-size:15px;font-weight:600;flex:1}
.head .hint{font-size:12.5px;color:var(--ink-3)}
.body{padding:0 16px 16px;border-top:1px solid var(--rule)}
.step:not(.open) .body{display:none}

.grain{background:var(--surface-2);border-left:3px solid var(--accent);border-radius:5px;
  padding:12px 14px;margin-top:14px}
.grain b{display:block;font-size:15px}
.grain .n{font-family:var(--mono);font-size:12px;color:var(--ink-2)}
.grain .no{color:var(--warn);font-family:var(--mono);font-size:12px;display:block;margin-top:5px}

table{width:100%;border-collapse:collapse;font-size:13px;margin-top:12px}
th{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-3);font-weight:500;text-align:left;padding:7px 10px;
  background:var(--surface-2);border-radius:3px}
td{padding:7px 10px;border-top:1px solid var(--rule);color:var(--ink-2)}
td.p{font-family:var(--mono);font-size:12px;color:var(--ink)}
td .cav{color:var(--warn);font-size:11.5px;display:block;margin-top:2px}

.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(238px,1fr));gap:9px;margin-top:12px}
.card{border:1px solid var(--rule);border-radius:5px;padding:11px 13px;background:var(--bg)}
.card.no{border-style:dashed;opacity:.85}
.card h3{margin:0 0 5px;font-size:13.5px;display:flex;justify-content:space-between;gap:8px;
  align-items:center}
.card p{margin:0;font-size:12px;color:var(--ink-3);line-height:1.45}
.card p.why{color:var(--stop)}
.card .unlock{font-size:11.5px;color:var(--ink-3);margin-top:6px;display:block}
.chip{font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;
  padding:2px 6px;border-radius:3px;white-space:nowrap}
.chip.ok{background:var(--ok-soft);color:var(--ok)}
.chip.no{background:var(--stop-soft);color:var(--stop)}
.chip.det{background:var(--accent-soft);color:var(--accent)}
.chip.agg{background:var(--warn-soft);color:var(--warn)}

button{font:inherit;font-size:13px;font-weight:600;padding:7px 13px;border:1px solid var(--rule);
  border-radius:5px;background:var(--surface);color:var(--ink);cursor:pointer}
button.go{background:var(--accent);border-color:var(--accent);color:var(--bg)}
button:disabled{opacity:.5;cursor:default}
.card button{margin-top:9px;width:100%}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}
select{font:inherit;font-size:13px;padding:7px 10px;border:1px solid var(--rule);
  border-radius:5px;background:var(--bg);color:var(--ink)}
pre{background:var(--surface-2);border-radius:5px;padding:11px 13px;overflow-x:auto;
  font-family:var(--mono);font-size:11.5px;color:var(--ink-2);margin:12px 0 0;
  max-height:320px;white-space:pre-wrap}
.diag{font-family:var(--mono);font-size:12px;margin-top:12px}
.diag div{padding:3px 0}
.diag .b{color:var(--stop)}
.diag .w{color:var(--warn)}
.diag .g{color:var(--ok)}
.msg{font-size:12.5px;color:var(--ink-3);margin-top:10px}
.msg.bad{color:var(--stop)}

#log{max-height:40vh;overflow-y:auto}
.turn{padding:9px 0;border-top:1px solid var(--rule)}
.turn:first-child{border-top:0}
.who{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-3);margin-bottom:4px}
.turn pre{background:none;padding:0;margin:0;font-family:var(--sans);font-size:13.5px;
  color:var(--ink-2);max-height:none}
.steps{font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-bottom:5px}
form{display:flex;gap:8px;margin-top:12px}
input{flex:1;font:inherit;font-size:13.5px;padding:8px 11px;border:1px solid var(--rule);
  border-radius:5px;background:var(--bg);color:var(--ink)}
input:focus{outline:2px solid var(--accent);outline-offset:-1px}
</style></head><body>
<div class="wrap">
  <header><h1 id="title">Loading…</h1><div class="sub" id="sub"></div></header>
  <div id="steps"></div>
</div>

<script>
const $ = s => document.querySelector(s);
const esc = t => String(t == null ? "" : t)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const j = async (p, body) => (await fetch(p, body ? {
  method:"POST", headers:{"Content-Type":"application/json"},
  body: JSON.stringify(body)} : undefined)).json();

let D, A, S, HAS_CHAT = false;

function step(n, id, title, hint, state, body){
  return '<section class="step ' + state + (state === "now" ? " open" : "") +
    '" id="s' + id + '"><div class="head" onclick="this.parentNode.classList.toggle(\'open\')">' +
    '<span class="num">' + (state === "done" ? "✓" : n) + '</span>' +
    '<h2>' + title + '</h2><span class="hint">' + hint + '</span></div>' +
    '<div class="body">' + body + '</div></section>';
}

function fieldsTable(){
  return '<table><thead><tr><th>Field</th><th>Values</th><th>Access</th><th>Coverage</th>' +
    '</tr></thead><tbody>' + D.fields.map(f => {
      let v = f.type;
      if (f.range) v = f.type + " " + f.range[0] + "–" + f.range[1];
      else if (f.categories.length) v = f.categories.join(", ") +
        (f.cardinality > f.categories.length ? ", …" : "");
      else if (f.cardinality) v = f.type + " (" + f.cardinality.toLocaleString() + ")";
      const chip = f.access === "DETAILED"
        ? '<span class="chip det">detailed</span>'
        : '<span class="chip agg">' + esc((f.releasableAs || []).join(" · ") || "aggregate") + '</span>';
      return '<tr><td class="p">' + esc(f.path) + '</td><td>' + esc(v) +
        (f.caveats.length ? '<span class="cav">! ' + esc(f.caveats[0]) + '</span>' : '') +
        '</td><td>' + chip + '</td><td>' +
        (f.coverage == null ? "—" : Math.round(f.coverage * 100) + "%") + '</td></tr>';
    }).join("") + '</tbody></table>';
}

function analysisCards(){
  const card = m => '<div class="card' + (m.status === "FEASIBLE" ? '' : ' no') + '">' +
    '<h3>' + esc(m.title) + '<span class="chip ' +
      (m.status === "FEASIBLE" ? 'ok">available' : 'no">blocked') + '</span></h3>' +
    (m.status === "FEASIBLE"
      ? '<p>' + esc(m.summary) + '</p><button class="go" onclick="gen(\'' + m.key +
        '\')">Generate code</button>'
      : '<p class="why">' + esc(m.blockers[0] || "") + '</p>' +
        (m.unlock ? '<span class="unlock">' + esc(m.unlock) + '</span>' : '')) + '</div>';
  const ok = A.filter(m => m.status === "FEASIBLE");
  const no = A.filter(m => m.status !== "FEASIBLE");
  return '<p class="msg">' + ok.length + ' available, ' + no.length +
    ' not possible with this dataset. Every refusal says why.</p>' +
    '<div class="cards">' + ok.map(card).join("") + no.map(card).join("") + '</div>' +
    '<div id="genmsg"></div>';
}

function runPanel(){
  if (!S.analyses.length)
    return '<p class="msg">Generate an analysis in step 4 first.</p>';
  return '<div class="row"><select id="mod">' +
    S.analyses.map(m => '<option>' + esc(m) + '</option>').join("") +
    '</select><button class="go" onclick="runIt()">Run on synthetic data</button></div>' +
    '<p class="msg">Runs locally against generated/data.csv. These are not results.</p>' +
    '<div id="runout"></div>';
}

function checkPanel(){
  const f = S.blocking, w = S.warnings;
  let head = f ? '<div class="diag"><div class="b">' + f + ' blocking issue' +
      (f === 1 ? '' : 's') + ' — this would not pass the gate</div></div>'
    : '<div class="diag"><div class="g">✓ All checks passed</div></div>';
  return head + '<div class="row"><button onclick="recheck()">Re-check</button></div>' +
    '<div id="chkout"></div>';
}

function chatPanel(){
  if (!HAS_CHAT)
    return '<p class="msg">No model configured. Run <code>epsilon ai login</code> ' +
      'in the terminal, then reload. Everything above works without one.</p>';
  return '<div id="log"></div><form id="f"><input id="q" autocomplete="off" ' +
    'placeholder="Ask anything about this dataset…"><button class="go">Ask</button></form>';
}

async function render(){
  const current =
    !S.hasProject ? 2 : !S.analyses.length ? 4 : S.blocking ? 6 : 7;
  const st = n => n < current ? "done" : n === current ? "now" : "todo";

  $("#steps").innerHTML =
    step(1, 1, "Sign in", S.signedIn ? "done" : "epsilon login",
      S.signedIn ? "done" : "now",
      '<p class="msg">' + (S.signedIn
        ? "Credentials found in ~/.epsilon_sdk."
        : "Run <code>epsilon login</code> in the terminal, then reload.") + '</p>') +
    step(2, 2, "Start a project", S.hasProject ? "done" : "epsilon init",
      S.hasProject ? "done" : "now",
      '<p class="msg">' + (S.hasProject
        ? "project.yml and the archetype-scoped projection are in place."
        : "Run <code>epsilon init &lt;dataset_id&gt;</code>, then reload.") + '</p>') +
    step(3, 3, "Understand your data", D.rows ? D.rows.toLocaleString() + " rows" : "",
      st(3),
      '<div class="grain"><b>One row is a ' + esc(D.unit) + '</b>' +
      '<span class="n">' + (D.rows != null ? D.rows.toLocaleString() + " rows" : "") + '</span>' +
      (D.hasEntityKey ? "" : '<span class="no">No key groups rows back to a person or ' +
        'case — per-entity figures are not computable</span>') + '</div>' +
      fieldsTable() +
      (D.notes.length ? '<p class="msg">' + esc(D.notes[0]) + '</p>' : '')) +
    step(4, 4, "Choose what to build",
      A.filter(m => m.status === "FEASIBLE").length + " available", st(4),
      analysisCards()) +
    step(5, 5, "Run it",
      S.analyses.length ? S.analyses.length + " written" : "nothing yet", st(5),
      runPanel()) +
    step(6, 6, "Check before submitting",
      S.blocking ? S.blocking + " blocking" : "passing", st(6), checkPanel()) +
    step(7, 7, "Ask the copilot", HAS_CHAT ? "" : "no model", st(7), chatPanel());

  const f = $("#f");
  if (f) f.addEventListener("submit", ask);
}

async function refresh(){ S = await j("/api/status"); await render(); }

window.gen = async key => {
  const r = await j("/api/generate", {analysis:key});
  $("#genmsg").innerHTML = r.ok
    ? '<p class="msg">Wrote <code>' + esc(r.path) + '</code>. Step 5 can run it.</p>'
    : '<p class="msg bad">' + esc(r.message) + '</p>';
  if (r.ok) await refresh();
};

window.runIt = async () => {
  const m = $("#mod").value;
  $("#runout").innerHTML = '<p class="msg">Running…</p>';
  const r = await j("/api/run", {module:m});
  $("#runout").innerHTML = '<pre>' + esc(r.output) + '</pre>' +
    '<p class="msg">Synthetic data — these are not results.</p>';
};

window.recheck = async () => {
  const r = await j("/api/checks");
  $("#chkout").innerHTML = r.findings.length
    ? '<div class="diag">' + r.findings.map(f =>
        '<div class="' + (f.level === "BLOCK" ? "b" : "w") + '">' + f.level + "  " +
        esc(f.path) + (f.line ? ":" + f.line : "") + "  " + esc(f.message) +
        (f.fix ? '<br>&nbsp;&nbsp;&nbsp;→ ' + esc(f.fix) : "") + '</div>').join("") +
      '</div>'
    : '<div class="diag"><div class="g">✓ All checks passed</div></div>';
  await refresh();
};

async function ask(e){
  e.preventDefault();
  const q = $("#q").value.trim();
  if (!q) return;
  $("#q").value = "";
  add("you", esc(q));
  const pending = add("copilot", "…");
  const r = await j("/api/chat", {message:q});
  pending.innerHTML = '<div class="who">copilot</div>' +
    (r.steps && r.steps.length
      ? '<div class="steps">' + r.steps.map(s => "· " + esc(s.label)).join("<br>") + '</div>'
      : '') + '<pre>' + esc(r.reply || r.error) + '</pre>';
  await refresh();
}

function add(who, html){
  const el = document.createElement("div");
  el.className = "turn";
  el.innerHTML = '<div class="who">' + who + '</div><pre>' + html + '</pre>';
  $("#log").appendChild(el);
  $("#log").scrollTop = $("#log").scrollHeight;
  return el;
}

(async () => {
  D = await j("/api/dataset");
  A = (await j("/api/analyses")).analyses;
  HAS_CHAT = (await j("/api/session")).chat;
  $("#title").textContent = D.title;
  $("#sub").textContent = [D.archetype && "archetype " + D.archetype,
    D.rows != null && D.rows.toLocaleString() + " rows",
    "suppression n<" + D.minCell].filter(Boolean).join("  ·  ");
  await refresh();
})();
</script></body></html>
'''
