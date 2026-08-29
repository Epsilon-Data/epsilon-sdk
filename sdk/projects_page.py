"""
The projects screen: what you are working on, and what you could ask of it.

The workspace page reproduces the design canvas exactly and is left alone.
This is the screen in front of it -- pick a cohort, say what you are trying to
find out, and get analyses the dataset can actually answer. Same palette,
type and spacing as the canvas, so the two read as one product.

Standard library and one string, for the same reason as the workspace page.
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

  /* -- the rail ------------------------------------------------------ */
  .rail {
    width: 236px; flex: none; background: var(--sidebar); color: #cfe3dd;
    display: flex; flex-direction: column; padding: 20px 0; gap: 4px;
    height: 100vh; position: sticky; top: 0;
  }
  .brand {
    padding: 0 20px 18px; font-weight: 600; font-size: 15px; color: #fff;
    letter-spacing: -0.01em;
  }
  .brand span { color: var(--mint); }
  .rail-label {
    padding: 14px 20px 6px; font-size: 10px; letter-spacing: 0.12em;
    text-transform: uppercase; color: #6c8a83;
  }
  .rail-list { overflow-y: auto; flex: 1; padding-bottom: 8px; }
  .rail-item {
    display: block; width: 100%; text-align: left; background: none;
    border: 0; color: #cfe3dd; padding: 9px 20px; font-size: 13px;
    border-left: 2px solid transparent;
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
    margin: 8px 16px 0; padding: 9px 12px; background: var(--deep);
    color: #fff; border: 0; border-radius: 6px; font-size: 13px;
    font-weight: 500;
  }
  .rail-new:hover { background: #0f766a; }
  .rail-foot {
    padding: 12px 20px 0; font-size: 11px; color: #6c8a83;
    border-top: 1px solid #21332f; margin-top: 8px;
  }

  /* -- the page ------------------------------------------------------ */
  main { flex: 1; min-width: 0; padding: 40px 48px 72px; max-width: 1080px; }
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
  .facts {
    display: flex; flex-wrap: wrap; gap: 10px 26px; margin: 22px 0 0;
    padding: 16px 0 0; border-top: 1px solid var(--rule);
  }
  .fact { font-size: 12px; }
  .fact b {
    display: block; font-family: var(--mono); font-size: 13px;
    font-weight: 500; font-variant-numeric: tabular-nums;
  }
  .fact span { color: var(--muted); }

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
  .empty code {
    font-family: var(--mono); font-size: 12px; background: #efece6;
    padding: 2px 6px; border-radius: 4px; color: var(--ink);
  }
  .note { font-size: 12px; color: var(--muted); margin-top: 12px; }
  .err {
    color: var(--warn); background: #fdf6f4; border: 1px solid #f0d9d3;
    border-radius: 8px; padding: 11px 14px; margin-top: 14px; font-size: 13px;
  }

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
    padding: 11px 20px; background: var(--deep); color: #fff; border: 0;
    border-radius: 8px; font-weight: 500;
  }
  .primary:hover { background: #0f766a; }
  .ghost {
    padding: 11px 16px; background: none; border: 1px solid var(--rule);
    border-radius: 8px; color: var(--muted);
  }
  .ghost:hover { border-color: var(--muted); color: var(--ink); }

  .spin { color: var(--muted); font-size: 13px; }
  @media (prefers-reduced-motion: no-preference) {
    .card, .rail-item, .primary { transition: all .12s ease; }
  }
</style>
</head>
<body>
<nav class="rail">
  <div class="brand">epsilon<span>.</span></div>
  <div class="rail-label">Projects</div>
  <div class="rail-list" id="rail"></div>
  <button class="rail-new" id="new">New project</button>
  <div class="rail-foot">Everything stays on this machine.</div>
</nav>
<main id="main"><p class="spin">Loading…</p></main>

<script>
const $ = (id) => document.getElementById(id);
const esc = (t) => String(t == null ? "" : t)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const state = { projects: [], openId: null, cards: null, view: "home",
                error: "", busy: false };

async function api(path, body) {
  const res = await fetch(path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ("Request failed (" + res.status + ")"));
  return data;
}

async function load() {
  const p = await api("/api/projects");
  state.projects = p.projects;
  state.openId = p.openId;
  if (!state.projects.length) state.view = "new";
  paint();
  if (state.view === "home") loadCards();
}

async function loadCards(refresh) {
  state.cards = null;
  paint();
  try {
    const c = await api("/api/cards" + (refresh ? "?refresh=1" : ""));
    state.cards = c;
  } catch (e) {
    state.cards = { ready: false, cards: [], error: e.message };
  }
  paint();
}

// -- actions ---------------------------------------------------------

async function openProject(id) {
  state.error = ""; state.view = "home";
  try {
    await api("/api/projects/open", { id: id });
    state.openId = id;
    await load();
  } catch (e) { state.error = e.message; paint(); }
}

async function createProject(ev) {
  ev.preventDefault();
  state.error = ""; state.busy = true; paint();
  try {
    await api("/api/projects/new", {
      name: $("f-name").value.trim(),
      path: $("f-path").value.trim(),
      description: $("f-desc").value.trim()
    });
    state.view = "home"; state.busy = false;
    await load();
  } catch (e) {
    state.error = e.message; state.busy = false; paint();
  }
}

async function forget(id, name) {
  state.error = "";
  // The directory and its files are untouched; only the entry goes.
  try {
    await api("/api/projects/forget", { id: id });
    await load();
  } catch (e) { state.error = e.message; paint(); }
}

// A card, or a typed question, becomes a session that already knows the
// project -- which is why we ask the server for the seed before navigating.
async function openSession(payload, path) {
  state.error = "";
  try {
    const out = await api(path, payload);
    window.location.href = out.url;
  } catch (e) { state.error = e.message; paint(); }
}

function ask(ev) {
  ev.preventDefault();
  const q = $("q").value.trim();
  if (q) openSession({ question: q }, "/api/ask");
}

// -- rendering -------------------------------------------------------

function paintRail() {
  $("rail").innerHTML = state.projects.map(p => (
    '<button class="rail-item" aria-current="' + (p.id === state.openId) +
    '" data-open="' + esc(p.id) + '">' + esc(p.name) +
    '<small>' + esc(p.initialised ? p.path.split("/").slice(-2).join("/")
                                  : "not initialised") + '</small></button>'
  )).join("") || '<p class="rail-foot" style="border:0">Nothing yet.</p>';
}

function open() {
  return state.projects.find(p => p.id === state.openId) || null;
}

function cardsHtml() {
  const c = state.cards;
  if (!c) return '<p class="spin">Looking at what this dataset supports…</p>';
  if (c.error) return '<div class="err">' + esc(c.error) + '</div>';
  if (!c.ready) return (
    '<div class="empty">This project has no projection yet. Run ' +
    '<code>epsilon init &lt;dataset_id&gt;</code> inside it, then reload.</div>');
  if (!c.cards.length) return '<div class="empty">Nothing to suggest here.</div>';

  return '<div class="cards">' + c.cards.map(card => (
    '<button class="card" data-card="' + card.index + '">' +
      '<h3>' + esc(card.title) + '</h3>' +
      '<p>' + esc(card.why || card.question) + '</p>' +
      '<footer>' + esc(card.analysis) +
        (card.warnings && card.warnings.length
          ? '<span class="flag">· caveat</span>' : '') +
      '</footer>' +
    '</button>')).join("") + '</div>' +
    '<p class="note">' + (c.suggested
      ? 'Suggested for this dataset, then checked against what the archetype ' +
        'allows — a blocked analysis is never offered.'
      : 'From the catalogue. Point the assistant at a model with ' +
        '<code>epsilon ai login</code> for suggestions specific to this data.') +
    '</p>';
}

function homeHtml(p) {
  const facts = [];
  if (state.cards && state.cards.ready) {
    facts.push(['Analyses offered', state.cards.cards.length]);
  }
  return (
    '<div class="eyebrow">Project</div>' +
    '<h1>' + esc(p.name) + '</h1>' +
    (p.description ? '<p class="desc">' + esc(p.description) + '</p>' : '') +
    '<p class="path">' + esc(p.path) +
      (p.exists ? '' : ' — <span class="flag">missing</span>') + '</p>' +
    '<section>' +
      '<h2>Ask</h2>' +
      '<p class="sub">Describe what you want to find out. The assistant ' +
        'checks it against the archetype before writing anything.</p>' +
      '<form class="ask" id="askform">' +
        '<input id="q" placeholder="Is diabetes more common at higher BMI?" ' +
          'autocomplete="off">' +
        '<button type="submit">Ask</button>' +
      '</form>' +
    '</section>' +
    '<section>' +
      '<h2>Start from</h2>' +
      '<p class="sub">Each opens a session that already knows this project.</p>' +
      cardsHtml() +
    '</section>' +
    '<section>' +
      '<h2>Project</h2>' +
      '<div class="actions">' +
        '<a class="ghost" style="text-decoration:none" href="/">Open the workspace</a>' +
        '<button class="ghost" data-forget="' + esc(p.id) + '">Forget this project</button>' +
      '</div>' +
      '<p class="note">Forgetting removes it from this list only. The ' +
        'directory and everything in it stays where it is.</p>' +
    '</section>');
}

function newHtml() {
  return (
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
        '<button class="primary" type="submit"' +
          (state.busy ? ' disabled' : '') + '>' +
          (state.busy ? 'Measuring…' : 'Create project') + '</button>' +
        (state.projects.length
          ? '<button class="ghost" type="button" id="cancel">Cancel</button>' : '') +
      '</div>' +
    '</form>');
}

function paint() {
  paintRail();
  const p = open();
  let html;
  if (state.view === "new" || !p) html = newHtml();
  else html = homeHtml(p);
  if (state.error) html += '<div class="err">' + esc(state.error) + '</div>';
  $("main").innerHTML = html;

  const form = $("newform");
  if (form) form.addEventListener("submit", createProject);
  const askform = $("askform");
  if (askform) askform.addEventListener("submit", ask);
  const cancel = $("cancel");
  if (cancel) cancel.onclick = () => { state.view = "home"; paint(); };
}

document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-open], [data-card], [data-forget]");
  if (!el) return;
  if (el.dataset.open) openProject(el.dataset.open);
  else if (el.dataset.card) openSession({ index: Number(el.dataset.card) }, "/api/handoff");
  else if (el.dataset.forget) forget(el.dataset.forget);
});

$("new").onclick = () => { state.view = "new"; state.error = ""; paint(); };

load().catch(e => { $("main").innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
</script>
</body>
</html>
'''
