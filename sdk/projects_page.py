"""
The projects screens: the list, one project, and the new-project form.

The URL is the state -- `/` lists projects, `/projects/<id>` is one project,
`/projects/new` is the form. Real navigation, so the back button and reload
behave like any other site.

A project's cards are drawn twice: the catalogue answers instantly, and model
suggestions replace them when they arrive. A model call never sits between the
researcher and the page.

Standard library and one string, like the workspace page.
"""
from __future__ import annotations

PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Epsilon projects</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root {
    --ground: #f4f2ee;      --ink: #1c1b19;      --muted: #6b675f;
    --rule: #dcd8d0;        --card: #fbfaf8;     --sidebar: #14201e;
    --deep: #0d6459;        --mint: #6fd3bd;     --warn: #a33a2b;
    --sans: 'IBM Plex Sans', system-ui, -apple-system, sans-serif;
    --mono: 'IBM Plex Mono', ui-monospace, 'SF Mono', monospace;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--ground); color: var(--ink); font-family: var(--sans);
    font-size: 14px; line-height: 1.5; display: flex; min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }
  button { font: inherit; cursor: pointer; }
  input, textarea { font: inherit; color: inherit; }
  a { color: inherit; }

  /* -- the rail ------------------------------------------------------ */
  .rail {
    width: 236px; flex: none; background: var(--sidebar); color: #cfe3dd;
    display: flex; flex-direction: column; padding: 20px 0; gap: 4px;
    height: 100vh; position: sticky; top: 0;
  }
  .brand {
    display: block; padding: 0 20px 18px; font-weight: 600; font-size: 15px;
    color: #fff; letter-spacing: -0.01em; text-decoration: none;
  }
  .brand span { color: var(--mint); }
  .rail-label {
    padding: 14px 20px 6px; font-size: 10px; letter-spacing: 0.12em;
    text-transform: uppercase; color: #6c8a83;
  }
  .rail-list { overflow-y: auto; flex: 1; padding-bottom: 8px; }
  .rail-item {
    display: block; color: #cfe3dd; padding: 9px 20px; font-size: 13px;
    border-left: 2px solid transparent; text-decoration: none;
  }
  .rail-item:hover { background: #1b2b28; }
  .rail-item[aria-current="true"] {
    background: #1b2b28; border-left-color: var(--mint); color: #fff;
    font-weight: 500;
  }
  .rail-item small {
    display: block; color: #6c8a83; font-size: 11px; font-family: var(--mono);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .rail-new {
    display: block; margin: 8px 16px 0; padding: 9px 12px;
    background: var(--deep); color: #fff; border-radius: 6px; font-size: 13px;
    font-weight: 500; text-align: center; text-decoration: none;
  }
  .rail-new:hover { background: #0f766a; }
  .rail-foot {
    padding: 12px 20px 0; font-size: 11px; color: #6c8a83;
    border-top: 1px solid #21332f; margin-top: 8px;
  }

  /* -- the page ------------------------------------------------------ */
  main { flex: 1; min-width: 0; padding: 40px 48px 72px; max-width: 1080px; }
  .back {
    display: inline-block; margin-bottom: 16px; color: var(--muted);
    font-size: 13px; text-decoration: none;
  }
  .back:hover { color: var(--ink); }
  .eyebrow {
    font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--muted); margin-bottom: 10px;
  }
  h1 {
    font-size: 27px; font-weight: 600; letter-spacing: -0.02em; margin: 0;
    text-wrap: balance;
  }
  .desc { color: var(--muted); margin: 10px 0 0; max-width: 64ch; }
  .path {
    font-family: var(--mono); font-size: 12px; color: var(--muted);
    margin-top: 12px; word-break: break-all;
  }

  section { margin-top: 40px; }
  h2 {
    font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--muted); font-weight: 500; margin: 0 0 4px;
  }
  .sub { color: var(--muted); font-size: 13px; margin: 0 0 16px; }

  .ask { display: flex; gap: 10px; align-items: stretch; }
  .ask input {
    flex: 1; padding: 13px 15px; border: 1px solid var(--rule);
    border-radius: 8px; background: #fff;
  }
  .ask input:focus {
    outline: 2px solid var(--mint); outline-offset: -1px;
    border-color: transparent;
  }
  .ask button {
    padding: 0 20px; background: var(--deep); color: #fff; border: 0;
    border-radius: 8px; font-weight: 500;
  }
  .ask button:hover { background: #0f766a; }

  .cards { display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(268px, 1fr)); }
  .card {
    text-align: left; background: var(--card); border: 1px solid var(--rule);
    border-radius: 10px; padding: 17px 18px 15px; display: flex;
    flex-direction: column; gap: 8px; min-height: 152px;
    text-decoration: none; color: inherit;
  }
  .card:hover { border-color: var(--deep); background: #fff; }
  .card:focus-visible { outline: 2px solid var(--mint); outline-offset: 2px; }
  .card h3 { margin: 0; font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }
  .card p { margin: 0; color: var(--muted); font-size: 13px; flex: 1; }
  .card footer {
    display: flex; align-items: center; gap: 8px; font-family: var(--mono);
    font-size: 11px; color: var(--deep);
  }
  .flag { color: var(--warn); font-family: var(--sans); }
  .empty {
    border: 1px dashed var(--rule); border-radius: 10px; padding: 26px;
    color: var(--muted); background: var(--card);
  }
  .empty code, .note code {
    font-family: var(--mono); font-size: 12px; background: #efece6;
    padding: 2px 6px; border-radius: 4px; color: var(--ink);
  }
  .note { font-size: 12px; color: var(--muted); margin-top: 12px; }
  .err {
    color: var(--warn); background: #fdf6f4; border: 1px solid #f0d9d3;
    border-radius: 8px; padding: 11px 14px; margin-top: 14px; font-size: 13px;
  }
  .spin { color: var(--muted); font-size: 13px; }

  /* -- set-up steps -------------------------------------------------- */
  .steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
  .step {
    display: flex; gap: 13px; align-items: flex-start; padding: 13px 15px;
    background: var(--card); border: 1px solid var(--rule); border-radius: 8px;
  }
  .step.done { background: transparent; border-color: transparent; }
  .step .tick {
    flex: none; width: 19px; height: 19px; border-radius: 50%;
    border: 1px solid var(--rule); display: flex; align-items: center;
    justify-content: center; font-size: 11px; margin-top: 1px;
  }
  .step.done .tick {
    background: var(--deep); border-color: var(--deep); color: #fff;
  }
  .step b { display: block; font-size: 13.5px; font-weight: 600; }
  .step b i { font-weight: 400; color: var(--muted); font-style: normal; }
  .step code {
    display: inline-block; font-family: var(--mono); font-size: 12px;
    background: #efece6; padding: 2px 7px; border-radius: 4px; margin: 5px 0 0;
  }
  .step.done code { background: transparent; padding-left: 0; color: var(--muted); }
  .step small { display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }

  /* -- the new-project form ------------------------------------------ */
  .form { max-width: 560px; }
  .field { margin-bottom: 18px; }
  .field label { display: block; font-size: 12px; font-weight: 500; margin-bottom: 6px; }
  .field input, .field textarea {
    width: 100%; padding: 11px 13px; border: 1px solid var(--rule);
    border-radius: 8px; background: #fff;
  }
  .field textarea { min-height: 84px; resize: vertical; }
  .field input:focus, .field textarea:focus {
    outline: 2px solid var(--mint); outline-offset: -1px; border-color: transparent;
  }
  .field .hint { font-size: 12px; color: var(--muted); margin-top: 5px; }
  .field input.mono { font-family: var(--mono); font-size: 12.5px; }
  .actions { display: flex; gap: 10px; align-items: center; }
  .primary {
    display: inline-block; padding: 11px 20px; background: var(--deep);
    color: #fff; border: 0; border-radius: 8px; font-weight: 500;
    text-decoration: none;
  }
  .primary:hover { background: #0f766a; }
  .primary:disabled { opacity: 0.6; cursor: default; }
  .ghost {
    display: inline-block; padding: 11px 16px; background: none;
    border: 1px solid var(--rule); border-radius: 8px; color: var(--muted);
    text-decoration: none;
  }
  .ghost:hover { border-color: var(--muted); color: var(--ink); }

  @media (prefers-reduced-motion: no-preference) {
    .card, .rail-item, .primary { transition: all .12s ease; }
  }
</style>
</head>
<body>
<nav class="rail">
  <a class="brand" href="/">epsilon<span>.</span></a>
  <div class="rail-label">Projects</div>
  <div class="rail-list" id="rail"></div>
  <a class="rail-new" href="/projects/new">New project</a>
  <div class="rail-foot">Everything stays on this machine.</div>
</nav>
<main id="main"><p class="spin">Loading…</p></main>

<script>
const $ = (id) => document.getElementById(id);
const esc = (t) => String(t == null ? "" : t)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// The URL is the state: / lists projects, /projects/<id> is one project,
// /projects/new is the form. Back and reload behave like any other site.
const route = (() => {
  const path = location.pathname.replace(/\/+$/, "") || "/";
  if (path === "/" || path === "/projects") return { kind: "list" };
  if (path === "/projects/new") return { kind: "new" };
  const m = path.match(/^\/projects\/([a-z0-9-]+)$/);
  return m ? { kind: "detail", id: m[1] } : { kind: "list" };
})();

const state = { projects: [], openId: null, shownCards: [] };

async function api(path, body) {
  const res = await fetch(path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("Request failed (" + res.status + ")"));
  return data;
}

const errHtml = (m) => '<div class="err">' + esc(m) + '</div>';

// -- rendering --------------------------------------------------------

function paintRail() {
  $("rail").innerHTML = state.projects.map(p => (
    '<a class="rail-item" aria-current="' +
      (route.kind === "detail" && p.id === route.id) +
    '" href="/projects/' + esc(p.id) + '">' + esc(p.name) +
      '<small>' + esc(p.initialised ? p.path.split("/").slice(-2).join("/")
                                    : "not initialised") + '</small></a>'
  )).join("");
}

function projectGrid(list) {
  return '<div class="cards">' + list.map(p => (
    '<a class="card" href="/projects/' + esc(p.id) + '">' +
      '<h3>' + esc(p.name) + '</h3>' +
      '<p>' + esc(p.description || "No description.") + '</p>' +
      '<footer>' + (p.exists
        ? (p.initialised ? "ready" : "needs set-up")
        : '<span class="flag">folder missing</span>') + '</footer>' +
    '</a>')).join("") + '</div>';
}

function listHtml() {
  const ready = state.projects.filter(p => p.initialised);
  const pending = state.projects.filter(p => !p.initialised);
  return (
    '<div class="eyebrow">Projects</div>' +
    '<h1>What are you working on?</h1>' +
    '<p class="desc">Each one points at a folder on this machine. Open one ' +
      'to see what its dataset can answer, or to pick up where you left off.</p>' +
    (ready.length
      ? '<section><h2>Initialised</h2>' + projectGrid(ready) + '</section>'
      : '') +
    (pending.length
      ? '<section><h2>Needs set-up</h2><p class="sub">Registered, but with ' +
        'no projection yet — open one for the steps.</p>' +
        projectGrid(pending) + '</section>'
      : ''));
}

function stepsHtml(s) {
  if (!s || !s.steps) return errHtml("Could not read the folder.");
  return (
    '<h2>Set up</h2>' +
    '<p class="sub">Each step is detected from the folder, so doing one in ' +
      'a terminal and reloading loses nothing.</p>' +
    '<ol class="steps">' + s.steps.map(x => (
      '<li class="step' + (x.done ? ' done' : '') + '">' +
        '<span class="tick">' + (x.done ? '✓' : '') + '</span>' +
        '<div>' +
          '<b>' + esc(x.title) + (x.optional ? '<i> · optional</i>' : '') + '</b>' +
          '<code>' + esc(x.cmd) + '</code>' +
          '<small>' + esc(x.note || x.desc) + '</small>' +
        '</div>' +
      '</li>')).join("") + '</ol>');
}

function cardsHtml(payload) {
  state.shownCards = payload.cards;
  return (
    '<h2>Start from</h2>' +
    '<p class="sub">Each opens a session that already knows this project.</p>' +
    (payload.cards.length
      ? '<div class="cards">' + payload.cards.map((c, i) => (
          '<button class="card" data-card="' + i + '">' +
            '<h3>' + esc(c.title) + '</h3>' +
            '<p>' + esc(c.why || c.question) + '</p>' +
            '<footer>' + esc(c.analysis) +
              (c.warnings && c.warnings.length
                ? '<span class="flag">· caveat</span>' : '') +
            '</footer>' +
          '</button>')).join("") + '</div>'
      : '<div class="empty">Nothing to suggest here.</div>') +
    '<p class="note">' + (payload.suggested
      ? 'Suggested for this dataset, then checked against what the ' +
        'archetype allows — a blocked analysis is never offered.'
      : 'From the catalogue. Point the assistant at a model with ' +
        '<code>epsilon ai login</code> for suggestions specific to this data.') +
    '</p>');
}

function detailHtml(p) {
  return (
    '<a class="back" href="/">← Projects</a>' +
    '<div class="eyebrow">Project</div>' +
    '<h1>' + esc(p.name) + '</h1>' +
    (p.description ? '<p class="desc">' + esc(p.description) + '</p>' : '') +
    '<p class="path">' + esc(p.path) +
      (p.exists ? '' : ' — <span class="flag">missing</span>') + '</p>' +
    (p.initialised
      ? '<section>' +
          '<h2>Ask</h2>' +
          '<p class="sub">Describe what you want to find out. The assistant ' +
            'checks it against the archetype before writing anything.</p>' +
          '<form class="ask" id="askform">' +
            '<input id="q" placeholder="Is diabetes more common at higher ' +
              'BMI?" autocomplete="off">' +
            '<button type="submit">Ask</button>' +
          '</form>' +
        '</section>'
      : '') +
    '<section><div id="body"><p class="spin">' +
      (p.initialised ? 'Reading the catalogue…' : 'Reading the folder…') +
    '</p></div></section>' +
    '<section>' +
      '<h2>Project</h2>' +
      '<div class="actions">' +
        (p.initialised
          ? '<a class="primary" href="/workspace">Open the workspace</a>'
          : '') +
        '<button class="ghost" id="forget">Forget this project</button>' +
      '</div>' +
      '<p class="note">Forgetting removes it from this list only. The ' +
        'directory and everything in it stays where it is.</p>' +
    '</section>' +
    '<div id="pageerr"></div>');
}

function newHtml(showCancel) {
  return (
    (showCancel ? '<a class="back" href="/">← Projects</a>' : '') +
    '<div class="eyebrow">New project</div>' +
    '<h1>What are you trying to find out?</h1>' +
    '<p class="desc">A project points at a directory on this machine. ' +
      'Nothing is uploaded; the description is only used to suggest ' +
      'analyses that fit what you are asking.</p>' +
    '<form class="form" id="newform" style="margin-top:28px">' +
      '<div class="field"><label for="f-name">Name</label>' +
        '<input id="f-name" required placeholder="Diabetes risk factors" ' +
          'autocomplete="off"></div>' +
      '<div class="field"><label for="f-desc">What you are investigating</label>' +
        '<textarea id="f-desc" placeholder="Whether BMI and family history ' +
          'track with diagnosis in the adult cohort."></textarea>' +
        '<div class="hint">Optional, but it makes the suggestions better.</div></div>' +
      '<div class="field"><label for="f-path">Folder</label>' +
        '<input id="f-path" class="mono" required placeholder="~/research/diabetes-cohort" ' +
          'autocomplete="off" spellcheck="false">' +
        '<div class="hint">The directory you ran <code>epsilon init</code> in, ' +
          'or an empty one you are about to.</div></div>' +
      '<div class="actions">' +
        '<button class="primary" id="create" type="submit">Create project</button>' +
        (showCancel ? '<a class="ghost" href="/">Cancel</a>' : '') +
      '</div>' +
      '<div id="formerr"></div>' +
    '</form>');
}

// -- actions ----------------------------------------------------------

async function createProject(ev) {
  ev.preventDefault();
  const entry = {
    name: $("f-name").value.trim(),
    path: $("f-path").value.trim(),
    description: $("f-desc").value.trim()
  };
  const btn = $("create");
  btn.disabled = true;
  btn.textContent = "Measuring…";
  try {
    const out = await api("/api/projects/new", entry);
    location.href = "/projects/" + out.project.id;
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Create project";
    $("formerr").innerHTML = errHtml(e.message);
  }
}

async function forget(id) {
  try {
    await api("/api/projects/forget", { id: id });
    location.href = "/";
  } catch (e) {
    $("pageerr").innerHTML = errHtml(e.message);
  }
}

// A card, or a typed question, becomes a session. The server re-validates the
// card against the catalogue before seeding anything.
async function openSession(payload, path) {
  try {
    const out = await api(path, payload);
    location.href = out.url;
  } catch (e) {
    $("pageerr").innerHTML = errHtml(e.message);
  }
}

// -- the three screens ------------------------------------------------

async function showDetail() {
  const p = state.projects.find(x => x.id === route.id);
  if (!p) {
    $("main").innerHTML = errHtml("No such project.");
    return;
  }
  if (p.id !== state.openId) {
    try {
      await api("/api/projects/open", { id: p.id });
      state.openId = p.id;
    } catch (e) {
      $("main").innerHTML = errHtml(e.message);
      return;
    }
  }
  $("main").innerHTML = detailHtml(p);
  $("forget").onclick = () => forget(p.id);
  const form = $("askform");
  if (form) form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("q").value.trim();
    if (q) openSession({ question: q }, "/api/ask");
  });

  const body = $("body");
  if (!p.initialised) {
    body.innerHTML = stepsHtml(await api("/api/status").catch(() => null));
    return;
  }

  // The catalogue answers instantly; model suggestions replace it when ready.
  let payload;
  try {
    payload = await api("/api/cards?fast=1");
  } catch (e) {
    body.innerHTML = errHtml(e.message);
    return;
  }
  body.innerHTML = cardsHtml(payload);
  if (payload.canSuggest) {
    const tag = document.createElement("p");
    tag.className = "note";
    tag.textContent = "Tailoring suggestions to this dataset…";
    body.appendChild(tag);
    const full = await api("/api/cards").catch(() => null);
    if (full && full.cards.length) body.innerHTML = cardsHtml(full);
    else tag.remove();
  }
}

async function main() {
  try {
    const p = await api("/api/projects");
    state.projects = p.projects;
    state.openId = p.openId;
  } catch (e) {
    $("main").innerHTML = errHtml(e.message);
    return;
  }
  paintRail();
  if (route.kind === "new") {
    $("main").innerHTML = newHtml(state.projects.length > 0);
    $("newform").addEventListener("submit", createProject);
  } else if (route.kind === "detail") {
    await showDetail();
  } else if (!state.projects.length) {
    $("main").innerHTML = newHtml(false);
    $("newform").addEventListener("submit", createProject);
  } else {
    $("main").innerHTML = listHtml();
  }
}

document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-card]");
  if (!el) return;
  const card = state.shownCards[Number(el.dataset.card)];
  if (card) openSession({ card: card }, "/api/handoff");
});

main();
</script>
</body>
</html>
'''
