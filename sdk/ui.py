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
            elif self.path == "/api/session":
                self._json({"chat": session is not None})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
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
  --bg:#f5f7f6; --surface:#fff; --surface-2:#edf1ef;
  --ink:#141d1b; --ink-2:#4c5c58; --ink-3:#7c8c87;
  --rule:#dbe2df; --accent:#0d6b60; --accent-soft:#e1efeb;
  --warn:#8e5b0c; --warn-soft:#f6ecd9;
  --stop:#a03728; --stop-soft:#f7e5e1;
  --ok:#2c6b3b; --ok-soft:#e2efe4;
  --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
}
@media(prefers-color-scheme:dark){:root{
  --bg:#0e1413; --surface:#161e1c; --surface-2:#1c2523;
  --ink:#e7eeeb; --ink-2:#9daea9; --ink-3:#75857f;
  --rule:#26302e; --accent:#5ac3b2; --accent-soft:#153029;
  --warn:#d9a45c; --warn-soft:#2c2417;
  --stop:#e58c7c; --stop-soft:#301c19;
  --ok:#83c392; --ok-soft:#18291c;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px 80px}
header{padding:32px 0 20px;border-bottom:1px solid var(--rule)}
h1{margin:0;font-size:22px;letter-spacing:-.01em}
.sub{font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-top:6px}
h2{font-size:13px;font-family:var(--mono);letter-spacing:.12em;text-transform:uppercase;
  color:var(--ink-3);font-weight:500;margin:34px 0 12px}
.grain{background:var(--surface);border:1px solid var(--rule);border-left:3px solid var(--accent);
  border-radius:5px;padding:14px 16px;margin-top:18px}
.grain b{display:block;font-size:16px;margin-bottom:3px}
.grain .n{font-family:var(--mono);font-size:12px;color:var(--ink-2)}
.grain .no{color:var(--warn);font-family:var(--mono);font-size:12px;margin-top:5px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:5px;padding:12px 14px}
.card.no{background:var(--surface-2);border-style:dashed}
.card h3{margin:0 0 6px;font-size:14px;display:flex;justify-content:space-between;
  align-items:center;gap:8px}
.card p{margin:0;font-size:12.5px;color:var(--ink-3);line-height:1.45}
.card .why{color:var(--stop)}
.card code{font-family:var(--mono);font-size:11px;color:var(--accent);
  display:block;margin-top:8px;word-break:break-all}
.chip{font-family:var(--mono);font-size:10px;letter-spacing:.07em;text-transform:uppercase;
  padding:2px 6px;border-radius:3px;white-space:nowrap}
.chip.ok{background:var(--ok-soft);color:var(--ok)}
.chip.no{background:var(--stop-soft);color:var(--stop)}
.chip.det{background:var(--accent-soft);color:var(--accent)}
.chip.agg{background:var(--warn-soft);color:var(--warn)}
table{width:100%;border-collapse:collapse;background:var(--surface);
  border:1px solid var(--rule);border-radius:5px;overflow:hidden;font-size:13px}
th{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-3);font-weight:500;text-align:left;padding:8px 12px;background:var(--surface-2)}
td{padding:8px 12px;border-top:1px solid var(--rule);color:var(--ink-2);vertical-align:middle}
td.p{font-family:var(--mono);font-size:12px;color:var(--ink)}
td .cav{color:var(--warn);font-size:11.5px;display:block;margin-top:3px}
.note{background:var(--warn-soft);border-radius:5px;padding:10px 13px;font-size:12.5px;
  color:var(--ink-2);margin-top:10px}
#chat{position:fixed;left:0;right:0;bottom:0;background:var(--surface);
  border-top:1px solid var(--rule);box-shadow:0 -8px 24px -18px rgba(0,0,0,.5)}
#chat .inner{max-width:1080px;margin:0 auto;padding:12px 20px}
#log{max-height:38vh;overflow-y:auto;margin-bottom:10px}
#log:empty{display:none}
.turn{padding:8px 0;border-bottom:1px solid var(--rule)}
.turn:last-child{border-bottom:0}
.who{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-3);margin-bottom:4px}
.turn pre{margin:0;white-space:pre-wrap;font-family:var(--sans);font-size:13.5px;color:var(--ink-2)}
.steps{font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-bottom:5px}
form{display:flex;gap:8px}
input{flex:1;font:inherit;padding:9px 12px;border:1px solid var(--rule);border-radius:5px;
  background:var(--bg);color:var(--ink)}
input:focus{outline:2px solid var(--accent);outline-offset:-1px}
button{font:inherit;font-weight:600;padding:9px 16px;border:0;border-radius:5px;
  background:var(--accent);color:var(--bg);cursor:pointer}
button:disabled{opacity:.5;cursor:default}
.off{font-size:12.5px;color:var(--ink-3);font-family:var(--mono)}
.pad{height:120px}
</style></head><body>
<div class="wrap">
  <header><h1 id="title">Loading…</h1><div class="sub" id="sub"></div></header>
  <div id="grain"></div>

  <h2>What you can build</h2>
  <div class="cards" id="available"></div>

  <h2>Not possible with this dataset</h2>
  <div class="cards" id="blocked"></div>

  <h2>Fields</h2>
  <div id="fields"></div>
  <div id="notes"></div>
  <div class="pad"></div>
</div>

<div id="chat"><div class="inner">
  <div id="log"></div>
  <form id="f"><input id="q" autocomplete="off"
      placeholder="Ask about this dataset…"><button id="send">Ask</button></form>
  <div class="off" id="off" hidden></div>
</div></div>

<script>
const $ = s => document.querySelector(s);
const esc = t => String(t == null ? "" : t)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");

async function boot(){
  const d = await (await fetch("/api/dataset")).json();
  $("#title").textContent = d.title;
  $("#sub").textContent = [d.archetype && "archetype " + d.archetype,
    d.rows != null && d.rows.toLocaleString() + " rows",
    "suppression n<" + d.minCell].filter(Boolean).join("  ·  ");

  $("#grain").innerHTML =
    '<div class="grain"><b>One row is a ' + esc(d.unit) + '</b>' +
    '<span class="n">' + (d.rows != null ? d.rows.toLocaleString() + " rows" : "") + '</span>' +
    (d.hasEntityKey ? "" :
      '<span class="no">No key groups rows back to a person or case — ' +
      'per-entity figures are not computable</span>') + '</div>';

  $("#fields").innerHTML = '<table><thead><tr><th>Field</th><th>Values</th>' +
    '<th>Access</th><th>Coverage</th></tr></thead><tbody>' +
    d.fields.map(f => {
      let vals = f.type;
      if (f.range) vals = f.type + " " + f.range[0] + "–" + f.range[1];
      else if (f.categories.length) vals = f.categories.join(", ") +
        (f.cardinality > f.categories.length ? ", …" : "");
      else if (f.cardinality) vals = f.type + " (" + f.cardinality.toLocaleString() + ")";
      const chip = f.access === "DETAILED"
        ? '<span class="chip det">detailed</span>'
        : '<span class="chip agg">' + esc((f.releasableAs || []).join(" · ") || "aggregate") + '</span>';
      return '<tr><td class="p">' + esc(f.path) + '</td><td>' + esc(vals) +
        (f.caveats.length ? '<span class="cav">! ' + esc(f.caveats[0]) + '</span>' : '') +
        '</td><td>' + chip + '</td><td>' +
        (f.coverage == null ? "—" : Math.round(f.coverage * 100) + "%") + '</td></tr>';
    }).join("") + '</tbody></table>';

  if (d.notes.length)
    $("#notes").innerHTML = d.notes.map(n => '<div class="note">' + esc(n) + '</div>').join("");

  const a = await (await fetch("/api/analyses")).json();
  const card = m => '<div class="card' + (m.status === "FEASIBLE" ? '' : ' no') + '">' +
    '<h3>' + esc(m.title) + '<span class="chip ' +
      (m.status === "FEASIBLE" ? 'ok">available' : 'no">blocked') + '</span></h3>' +
    (m.status === "FEASIBLE"
      ? '<p>' + esc(m.summary) + '</p>' +
        (m.command ? '<code>' + esc(m.command) + '</code>' : '')
      : '<p class="why">' + esc(m.blockers[0] || "") + '</p>' +
        (m.unlock ? '<code>' + esc(m.unlock) + '</code>' : '')) + '</div>';
  $("#available").innerHTML = a.analyses.filter(m => m.status === "FEASIBLE").map(card).join("");
  $("#blocked").innerHTML  = a.analyses.filter(m => m.status !== "FEASIBLE").map(card).join("");

  const s = await (await fetch("/api/session")).json();
  if (!s.chat){
    $("#f").hidden = true;
    $("#off").hidden = false;
    $("#off").textContent =
      "No model configured — run 'epsilon ai login' to enable chat. " +
      "Everything above needs no model.";
  }
}

$("#f").addEventListener("submit", async e => {
  e.preventDefault();
  const q = $("#q").value.trim();
  if (!q) return;
  $("#q").value = ""; $("#send").disabled = true;
  add("you", esc(q));
  const pending = add("copilot", "…");
  try{
    const r = await (await fetch("/api/chat", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({message:q})})).json();
    pending.innerHTML =
      '<div class="who">copilot</div>' +
      (r.steps && r.steps.length
        ? '<div class="steps">' + r.steps.map(s => "· " + esc(s.label)).join("<br>") + '</div>'
        : '') +
      '<pre>' + esc(r.reply || r.error) + '</pre>';
  }catch(err){
    pending.innerHTML = '<div class="who">copilot</div><pre>' + esc(err) + '</pre>';
  }
  $("#send").disabled = false; $("#q").focus();
  $("#log").scrollTop = $("#log").scrollHeight;
});

function add(who, html){
  const el = document.createElement("div");
  el.className = "turn";
  el.innerHTML = '<div class="who">' + who + '</div><pre>' + html + '</pre>';
  $("#log").appendChild(el);
  $("#log").scrollTop = $("#log").scrollHeight;
  return el;
}
boot();
</script></body></html>
'''
