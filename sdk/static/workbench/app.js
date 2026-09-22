import {
  app,
  icon,
  esc,
  s,
  fmt,
  pid,
  parts,
  base,
  apiProject,
  api,
  post,
  toast,
  showError,
  dialog,
  close,
  labelControls,
} from "./core.js";
import {
  chooseModel,
  loadModels,
  modelPicker,
  ratesText,
  usageTable,
} from "./usage.js";
import {
  selectedContext,
  contextMarkup,
  reviewCell,
  confirmCellContext,
  retryRequest,
  editResearchContext,
  saveResearchContext,
  refreshContextPreview,
} from "./assistant-controls.js";
import {
  flushNotebook,
  once,
  paintResult,
  updateNavigation,
} from "./interactions.js";
import { reconcileJobs, watch } from "./jobs.js";
import {
  createDatasetProject,
  ensureDatasetChoices,
  refreshDatasetChoices,
  resetDatasetChoices,
  retryDatasetDetails,
  selectDataset,
} from "./datasets.js";
import {
  lineChart,
  markLaterOutputsStale,
  notebookOutput,
} from "./notebook.js";
import {
  analysesPage,
  datasetPage,
  fieldRows,
  overviewPage,
  projectsPage,
  promptSuggestions,
  readableDate,
  runtimeLibrariesMarkup,
  setupPage,
  workRow,
  workspaceHref,
} from "./pages.js";
import { requestCellRepair, sendCellRepair } from "./repairs.js";
import {
  examplePage,
  examplesPage,
  showExampleCode,
  useExample,
} from "./examples.js";
import {
  acceptNotebook,
  applySuggestedCode,
  copyValue,
  loadResearchWorkspace,
  newCellId,
  openCodeCell,
  paintWorkspace,
  researchWorkspace,
  selectWorkspaceLayout,
  selectWorkspacePanel,
  startPlan,
  starters,
  workspaceJob,
} from "./workspace.js";

const initials = (name) =>
  (name || "Researcher")
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
const current = () =>
  s.project || s.projects.find((p) => p.id === pid()) || s.projects[0];
const brand = () =>
  '<span class="brand-mark">ε</span><div><div class="brand-name">epsilon</div><div class="brand-sub">Research workspace</div></div>';

const tutorialSteps = [
  {
    action: "example",
    title: "Start with an example",
    body: "Choose a worked analysis using this dataset’s permitted fields. It uses local synthetic data and does not call AI.",
    selector: '[data-tour="example-card"]',
  },
  {
    action: "copy",
    title: "Make an editable copy",
    body: "Review the fields, charts and code, then choose Use this example to create your own notebook.",
    selector: '[data-tour="use-example"]',
  },
  {
    action: "run",
    title: "Run the notebook",
    body: "Run all cells to create the charts locally. Your synthetic data stays on this computer.",
    selector: '[data-tour="run-all"]',
  },
  {
    action: "ask",
    title: "Ask for a change",
    body: "Ask the assistant for one change, such as a wider band or an explanation. Review code before adding it.",
    selector: '[data-tour="ask-ai"]',
  },
];
function tutorialKey(projectId) {
  return "epsilon.first-analysis." + projectId;
}
function readTutorial(projectId) {
  try {
    const value = JSON.parse(
      localStorage.getItem(tutorialKey(projectId)) || "null",
    );
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}
function saveTutorial(state) {
  try {
    localStorage.setItem(
      tutorialKey(state.projectId),
      JSON.stringify({
        step: state.step,
        exampleId: state.exampleId || "",
        notebookId: state.notebookId || "",
        completed: Boolean(state.completed),
      }),
    );
  } catch {}
}
function clearTutorialMarkup() {
  (document.querySelectorAll?.(".tutorial-target") || []).forEach((target) => {
    target.classList.remove("tutorial-target");
    if (target.dataset.tutorialDescribed === "true") {
      target.removeAttribute("aria-describedby");
      delete target.dataset.tutorialDescribed;
    }
  });
  const card = document.getElementById?.("epsilon-tutorial");
  if (card?.remove) card.remove();
}
function tutorialPath(state) {
  if (!state || state.step === 0) return base(state?.projectId || pid());
  if (state.step === 1)
    return state.exampleId
      ? `${base(state.projectId || pid())}/examples/${encodeURIComponent(state.exampleId)}`
      : `${base(state.projectId || pid())}/examples`;
  return state.notebookId
    ? `${base(state.projectId || pid())}/notebook/${encodeURIComponent(state.notebookId)}?layout=both`
    : `${base(state.projectId || pid())}/assistant`;
}
function positionTutorial(card, target) {
  const gap = 14,
    margin = 16,
    rect = target.getBoundingClientRect(),
    width = Math.min(350, window.innerWidth - margin * 2),
    cardHeight = card.offsetHeight,
    left = Math.max(
      margin,
      Math.min(rect.left, window.innerWidth - width - margin),
    );
  let top = rect.bottom + gap;
  if (top + cardHeight > window.innerHeight - margin)
    top = Math.max(margin, rect.top - cardHeight - gap);
  card.style.width = `${width}px`;
  card.style.left = `${left}px`;
  card.style.top = `${top}px`;
}
function renderTutorial() {
  clearTutorialMarkup();
  const state = s.tutorial;
  if (!state?.active || state.projectId !== pid() || !s.project?.ready) return;
  const step = tutorialSteps[state.step];
  if (!step) return;
  const target = document.querySelector(step.selector);
  if (!target) return;
  target.classList.add("tutorial-target");
  target.setAttribute("aria-describedby", "epsilon-tutorial-card");
  target.dataset.tutorialDescribed = "true";
  const card = document.createElement("aside");
  card.id = "epsilon-tutorial";
  card.className = "tutorial-card";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-labelledby", "epsilon-tutorial-title");
  card.innerHTML = `<div class="tutorial-progress">Step ${state.step + 1} of ${tutorialSteps.length}</div>
<h2 id="epsilon-tutorial-title">${esc(step.title)}</h2><p>${esc(step.body)}</p>
<div class="tutorial-actions"><button class="link-btn" data-action="pause-tutorial">Pause</button><button class="link-btn" data-action="skip-tutorial">Skip guide</button></div>`;
  document.body.append(card);
  positionTutorial(card, target);
}
function pauseTutorial() {
  if (!s.tutorial) return;
  s.tutorial.active = false;
  saveTutorial(s.tutorial);
  clearTutorialMarkup();
}
function skipTutorial() {
  if (!s.tutorial) return;
  s.tutorial.active = false;
  s.tutorial.completed = true;
  s.tutorial.step = tutorialSteps.length;
  saveTutorial(s.tutorial);
  clearTutorialMarkup();
  toast("Guide skipped. Reopen it from Help & guide.");
}
function tutorialAdvance(action, details = {}) {
  const state = s.tutorial,
    expected = tutorialSteps[state?.step]?.action;
  if (!state?.active || state.projectId !== pid() || expected !== action)
    return;
  Object.assign(state, details);
  state.step += 1;
  if (state.step >= tutorialSteps.length) {
    state.active = false;
    state.completed = true;
    saveTutorial(state);
    clearTutorialMarkup();
    toast("First analysis guide complete. Reopen it from Help & guide.");
    return;
  }
  saveTutorial(state);
  renderTutorial();
}
s.tutorialAdvance = tutorialAdvance;
async function beginTutorial(restart = false) {
  const projectId = pid();
  if (!s.project?.ready || !projectId) {
    dialog(
      "Open a project first",
      "The guide follows one project at a time.",
      "<p>Open an initialised project, then choose Help & guide.</p>",
    );
    return;
  }
  const saved = readTutorial(projectId),
    state = {
      projectId,
      step:
        restart || saved.completed
          ? 0
          : Math.min(Number(saved.step) || 0, tutorialSteps.length - 1),
      exampleId: saved.exampleId,
      notebookId: saved.notebookId,
      active: true,
      completed: false,
    },
    destination = tutorialPath(state);
  s.tutorial = state;
  saveTutorial(state);
  if (location.pathname !== new URL(destination, location.origin).pathname)
    await go(destination);
  else renderTutorial();
}
function repositionTutorial() {
  if (!s.tutorial?.active) return;
  const card = document.getElementById("epsilon-tutorial"),
    step = tutorialSteps[s.tutorial.step],
    target = step && document.querySelector(step.selector);
  if (card && target) positionTutorial(card, target);
}
const textHTML = (text) =>
  esc(text)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
function messageHTML(text) {
  return String(text)
    .split(/(```[\s\S]*?```)/g)
    .map((part) =>
      part.startsWith("```")
        ? `<pre class="code">
<code>${esc(part.replace(/^```[^\n]*\n?/, "").replace(/```$/, ""))}</code>
</pre>`
        : textHTML(part),
    )
    .join("");
}

async function go(url) {
  await flushNotebook();
  close();
  s.mobile = false;
  s.project = null;
  s.thread = null;
  s.tab = "chart";
  s.table = 0;
  history.pushState({}, "", url);
  await render();
  window.scrollTo(0, 0);
  document.getElementById("main-content")?.focus({ preventScroll: true });
}
function navigateLink(event) {
  const link = event.target.closest("a[href]");
  if (
    link &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.shiftKey &&
    !event.altKey &&
    link.origin === location.origin &&
    !link.hasAttribute("download") &&
    link.target !== "_blank" &&
    !link.pathname.startsWith("/api/") &&
    !link.hash
  ) {
    event.preventDefault();
    const exampleCard = link.closest('[data-tour="example-card"]');
    if (exampleCard)
      tutorialAdvance("example", { exampleId: exampleCard.dataset.exampleId });
    go(link.pathname + link.search).catch(showError);
  }
}
function shell(body, title = "Projects") {
  const route = parts(),
    p = route[0] === "projects" && route[1] ? current() : null;
  const view = ["assistant", "notebook"].includes(route[2])
    ? "assistant"
    : route[2] || "overview";
  const names = [
    ["overview", "Overview", "home"],
    ["examples", "Examples", "layers"],
    ["assistant", "Workspace", "notebook"],
    ["dataset", "Data", "database"],
    ["analyses", "Results", "chart"],
  ];
  return `<div class="mobile-overlay ${s.mobile ? "visible" : ""}" data-action="menu-close">
</div>
<aside id="workspace-navigation" class="sidebar ${s.mobile ? "is-open" : ""}" aria-label="Workspace navigation">
<a href="/projects" class="brand">${brand()}</a>
<a class="nav-item ${route.length === 1 && route[0] === "projects" ? "active" : ""}" href="/projects">${icon("grid")}Datasets & projects</a>${
    p
      ? `<button class="project-switch" data-action="switch-project">
<span class="project-icon">${icon("folder")}</span>
<span class="grow truncate">${esc(p.name)}</span>${icon("down")}</button>
<nav>${names.map(([key, label, ic]) => `<a class="nav-item ${route[1] === p.id && view === key ? "active" : ""}" href="${key === "assistant" ? workspaceHref(p.id) : base(p.id) + (key === "overview" ? "" : "/" + key)}" ${route[1] === p.id && view === key ? 'aria-current="page"' : ""}>${icon(ic)}${label}${route[1] === p.id && view === key ? '<i class="nav-dot"></i>' : ""}</a>`).join("")}</nav>`
      : ""
  }<div class="sidebar-bottom">
<a class="nav-item ${route[0] === "settings" ? "active" : ""}" href="/settings">${icon("settings")}Settings</a>
<button class="nav-item" data-action="open-tutorial">${icon("info")}Help &amp; guide</button>
<button class="nav-item privacy-nav" data-action="boundary">${icon("shield")}Privacy</button>
<button class="sidebar-account" data-action="account">
<span class="avatar">${esc(initials(s.session?.account?.username))}</span>
<span class="grow">
<span class="tiny">${esc(s.session?.account?.username || "Local researcher")}</span>
<small>${s.session?.account?.authenticated ? "Signed in to Epsilon" : "Local projects"}</small>
</span>${icon("down")}</button>
</div>
</aside>
<div class="main-shell">
<header class="topbar">
<div class="row grow">
<button class="icon-btn mobile-menu" data-action="menu" aria-controls="workspace-navigation" aria-expanded="${s.mobile}" aria-label="Open navigation">${icon("menu")}</button>
<div class="breadcrumbs">
<a href="/projects">Projects</a>${icon("chevron")}${p && route[1] ? `<a href="${base(p.id)}">${esc(p.name)}</a>${icon("chevron")}` : ""}<strong>${esc(title)}</strong>
</div>
</div>
<div class="topbar-right">
<a class="pill ${s.session?.ai?.configured ? "soft" : "amber"} ai-settings-link" href="/settings" aria-label="AI connection settings">${icon("spark")}${s.session?.ai?.configured ? "AI settings" : "Connect AI"}${icon("chevron")}</a>
</div>
</header>
<main id="main-content" tabindex="-1">${body}</main>
</div>`;
}
function welcome(unlocked = true) {
  return `<main id="main-content" class="welcome">
<aside class="welcome-aside">
<a class="brand" href="/">${brand()}</a>
<div class="welcome-story">
<p class="eyebrow">A local home for your research</p>
<h1>From a good question<br>to a clear analysis.</h1>
<p>Bring your research into focus. Explore your dataset, develop a method, and keep the code and evidence together.</p>
<div class="welcome-visual" aria-hidden="true">
<span>
</span>
<span>
</span>
<span>
</span>
<span>
</span>
<span>
</span>
</div>
</div>
<footer>RUN LOCALLY · BUILT FOR RESEARCHERS</footer>
</aside>
<section class="welcome-main">
<div class="welcome-form">
<div class="project-icon">${icon(unlocked ? "folder" : "lock", "lg")}</div>
<h2>${unlocked ? "Sign in to Epsilon." : "Open your workspace securely."}</h2>
<p>${unlocked ? "Use the same credentials as epsilon login." : "Run epsilon start again and open the complete link it prints. A fresh link opens this browser without stopping your running work."}</p>${
    unlocked
      ? `<form id="login-form" class="stack">
<label class="field" for="login-username">Email or username
<input id="login-username" name="username" required maxlength="200" autocomplete="username" autocapitalize="none" spellcheck="false">
</label>
<label class="field" for="login-password">Password
<input id="login-password" name="password" type="password" required maxlength="1000" autocomplete="current-password">
</label>
<p id="login-error" class="form-error" role="alert"></p>
<button class="btn primary wide" type="submit">Sign in ${icon("arrow")}</button>
</form>
<p class="signin-note">Your password is used only to sign in. Epsilon saves the access token locally.</p>${s.projects.length ? '<div class="rule"></div><a class="link-btn" href="/projects">Continue with local projects →</a>' : ""}`
      : `<code class="code" style="display:block;border-radius:8px">epsilon start</code>
<button class="btn wide" data-action="reload">Check this browser again ${icon("refresh")}</button>`
  }<div class="welcome-features">
<span>${icon("monitor")}Local workspace</span>
<span>${icon("database")}Synthetic preview</span>
</div>
</div>
</section>
</main>`;
}
function heading(title, description, button = "", eyebrow = "") {
  return `<div class="page-heading">
<div>${eyebrow ? `<div class="eyebrow" style="margin-bottom:12px">${esc(eyebrow)}</div>` : ""}<h1>${esc(title)}</h1>
<p>${esc(description)}</p>
</div>${button}</div>`;
}
function askBox(id, compact = false) {
  const key = pid() + "/" + (compact ? s.thread?.id || "overview" : "overview");
  const busy = compact && workspaceJob("chat");
  return `<form class="ask-form" id="${id}">
<div class="ask-box">
<label class="hidden" for="${id}-input">Ask about your research</label>
<textarea id="${id}-input" name="message" required maxlength="8000" rows="2" ${compact ? 'data-tour="ask-ai"' : ""} placeholder="${compact ? "Ask a question or describe the code you need…" : "Ask a question about your data…"}">${esc(s.drafts[key] || "")}</textarea>
<div class="ask-bottom">
<span class="ask-context">${icon("database")}<span class="truncate">${esc(s.project?.dataset?.title || "Your dataset")}</span>
</span>
${modelPicker(Boolean(busy))}<button class="send-btn" type="submit" aria-label="Send question" ${busy ? "disabled" : ""}>${icon("up")}</button>
</div>
</div>
${compact ? contextMarkup() : ""}<p class="ask-footnote">
<button class="link-btn tiny" type="button" data-action="boundary">${icon("shield")}What AI can see</button>
</p>
</form>`;
}
function progressMarkup(job) {
  if (!job) return "";
  const pending = ["queued", "running"].includes(job.status);
  const last = job.events?.at(-1);
  const stopping = pending && job.cancel_requested;
  return `<div class="run-progress">${pending ? '<span class="spinner"></span>' : icon(job.status === "completed" ? "check" : "info")}<span class="grow">${esc(stopping ? "Stopping after the current step…" : job.error || (job.status === "completed" ? "Completed" : last?.message) || "Preparing the task…")}</span>${pending && !stopping ? `<button class="link-btn" data-action="cancel-job" data-id="${job.id}" data-project="${job.project_id}">Cancel</button>` : ""}</div>`;
}
function planCard(plan) {
  return `<div class="plan-card">
<h3>${esc(starters[plan.analysis]?.[0] || plan.title)}</h3>
<p>${esc(starters[plan.analysis]?.[1] || plan.summary)}</p>
<details class="method-details">
<summary>Method details</summary>
<p>${esc(plan.summary)}</p>${Object.entries(plan.fields)
    .map(
      ([k, v]) => `<p>${esc(k)}: <code>${esc(v)}</code>
</p>`,
    )
    .join(
      "",
    )}<p>${esc(plan.unit)} counts · synthetic data</p>${plan.warnings.map((w) => `<p>${esc(w)}</p>`).join("")}</details>
<footer>
<button class="link-btn tiny" data-action="plan-code" data-id="${plan.id}">View code</button>
<button class="btn primary small" data-action="run-plan" data-id="${plan.id}" ${workspaceJob("preview") ? "disabled" : ""}>${icon("play")}Run preview</button>
</footer>
</div>`;
}
function resultTable(table) {
  return `<div class="table-scroll">
<table class="data-table">
<thead>
<tr>${table.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>
</thead>
<tbody>${
    table.rows
      .map(
        (row) =>
          `<tr>${table.columns.map((c) => `<td>${c === "records" ? fmt(row[c]) : esc(row[c])}</td>`).join("")}</tr>`,
      )
      .join("") ||
    `<tr>
<td colspan="${table.columns.length}">No groups can be displayed under the preview policy.</td>
</tr>`
  }</tbody>
</table>
</div>`;
}
function drawChart(table, chart = s.chart, axis = null) {
  if (chart === "line") return lineChart(table, axis);
  const values = table.chart.values,
    labels = table.chart.labels;
  if (!values.length)
    return '<div class="result-empty">All groups are withheld in this preview. Inspect the method and consider coarser groupings.</div>';
  if (chart === "pie") {
    const total = values.reduce((a, b) => a + b, 0);
    let angle = -Math.PI / 2;
    const colors = [
      "#1481F1",
      "#9FCBF9",
      "#014FE9",
      "#C5D3E0",
      "#3B3B3B",
      "#AEAEAE",
    ];
    const slices = values
      .map((value, i) => {
        const end = angle + (value / total) * Math.PI * 2;
        const start = [
          130 + 100 * Math.cos(angle),
          125 + 100 * Math.sin(angle),
        ];
        const finish = [130 + 100 * Math.cos(end), 125 + 100 * Math.sin(end)];
        const path =
          values.length === 1
            ? `<circle cx="130" cy="125" r="100" fill="${colors[0]}"/>`
            : `<path d="M 130 125 L ${start.join(" ")} A 100 100 0 ${end - angle > Math.PI ? 1 : 0} 1 ${finish.join(" ")} Z" fill="${colors[i % colors.length]}" stroke="white" stroke-width="2">
<title>${esc(labels[i])}: ${fmt(value)} records</title>
</path>`;
        angle = end;
        return path;
      })
      .join("");
    return `<svg viewBox="0 0 260 250" style="display:block;height:240px;width:100%" role="img" aria-label="Composition of displayed groups; withheld groups excluded">${slices}</svg>
<p class="tiny muted" style="text-align:center">Composition of displayed groups only. See the table for group names and counts.</p>`;
  }
  const shown = values.slice(0, 12),
    max = Math.max(...shown),
    ceiling =
      Math.ceil(max / Math.pow(10, Math.floor(Math.log10(max)))) *
      Math.pow(10, Math.floor(Math.log10(max)));
  return `<div class="chart-kicker">
<span>SYNTHETIC RECORDS</span>
<span>${esc(table.name)}</span>
</div>
<div class="bar-chart" role="img" aria-label="${esc(
    labels
      .slice(0, 12)
      .map((l, i) => l + ": " + fmt(shown[i]))
      .join(", "),
  )}">
<div class="y-axis">${[ceiling, ceiling * 0.75, ceiling * 0.5, ceiling * 0.25, 0].map((n) => `<span>${n >= 1000 ? Math.round(n / 100) / 10 + "k" : Math.round(n)}</span>`).join("")}</div>
<div class="plot">${shown
    .map(
      (n, i) => `<div class="bar-column">
<div class="bar" style="height:${(n / ceiling) * 100}%" title="${esc(labels[i])}: ${fmt(n)}">
<span class="bar-value">${fmt(n)}</span>
</div>
<span class="bar-label" title="${esc(labels[i])}">${esc(labels[i].length > 13 ? labels[i].slice(0, 11) + "…" : labels[i])}</span>
</div>`,
    )
    .join("")}</div>
</div>
<div class="chart-foot">
<span>
</span>Number of records${values.length > 12 ? " · first 12 displayed groups; full table available" : ""}</div>`;
}
function artifactRow(a) {
  return `<a class="recent-row" href="${base(a.project_id)}/analyses/${a.id}">
<span class="recent-icon">${icon("chart")}</span>
<span class="grow">
<h3>${esc(a.title)}</h3>
<p>${esc(readableDate(a.created))} · synthetic preview</p>
</span>
<span class="pill green">Saved</span>${icon("chevron")}</a>`;
}
function settingsPage() {
  const ai = s.session.ai;
  return `<div class="page">${heading("Settings", "Your account, AI connection and notebook setup.")}<div class="settings-layout">
<div>
<section class="settings-section">
<h2>Epsilon account</h2>
<p>${s.session.account.authenticated ? `Signed in as ${esc(s.session.account.username)}. The browser and epsilon login share the saved token.` : "Sign in to access authorised datasets. Local projects remain available."}</p>
<button class="btn" data-action="${s.session.account.authenticated ? "signout" : "signin"}">${icon("logOut")}${s.session.account.authenticated ? "Sign out" : "Sign in"}</button>
</section>
<section class="settings-section">
<h2>AI connection</h2>
<p>Saved connection: ${esc(ai.source)}${ai.key_source ? " · " + esc(ai.key_source) : ""}.</p>
<form id="ai-form" class="stack">
<label class="field">Provider<select name="provider">${[
    ["anthropic", "Anthropic"],
    ["openai", "OpenAI"],
    ["openai-compatible", "Institution / OpenAI-compatible"],
  ]
    .map(
      ([key, label]) =>
        `<option value="${key}" ${ai.provider === key ? "selected" : ""}>${label}</option>`,
    )
    .join("")}</select>
</label>
<label class="field">Model<input name="model" required value="${esc(ai.model)}" maxlength="150" autocomplete="off" list="ai-model-list">
<datalist id="ai-model-list">${(s.models?.models || []).map((m) => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join("")}</datalist>
<small>${s.models?.source === "provider" ? "Models your key can use, listed by the provider. You can also change model from the chat." : "Type a model name, or pick a suggestion. You can also change model from the chat."}</small>
</label>
<label class="field">Endpoint <span class="tiny muted">Optional for hosted providers</span>
<input name="base_url" value="${esc(ai.base_url)}" maxlength="300" placeholder="https://your-approved-endpoint/v1" autocomplete="off">
</label>
<label class="field">API key<input type="password" name="api_key" maxlength="1000" autocomplete="off" placeholder="Enter a key, or retain the current workspace connection">
<small>The key is never returned to the browser or stored in browser storage.</small>
</label>
<label class="row tiny">
<input type="checkbox" name="persist">Remember the key in the OS keyring when available</label>
<p class="form-error" id="ai-error" role="alert">
</p>
<button class="btn primary" type="submit">Save connection ${icon("check")}</button>
</form>
<div class="connection-test">
<button class="btn" data-action="test-ai">Test connection</button>
<p class="tiny muted">Uses your saved connection. No project data is included.</p>
<p id="ai-test-result" class="connection-result" role="status" aria-live="polite">
</p>
</div>
<button class="link-btn" data-action="cli-ai" style="margin-top:20px">Use existing epsilon ai login settings ${icon("arrow")}</button>
</section>
<section class="settings-section">
<h2>Usage and cost</h2>
<p>Tokens are counted from your provider's own report for each request, including retries. Costs are estimates; your provider's invoice is the record.</p>${usageTable(s.usageReport)}
<h3 class="settings-subhead">Rates for <code>${esc(ai.model)}</code></h3>
<p class="tiny muted">${ratesText(ai.rates)}</p>
<form id="price-form" class="row price-form">
<label class="field">Input $ / 1M<input name="input" type="number" min="0" max="10000" step="0.0001" inputmode="decimal" value="${ai.rates?.source === "custom" ? ai.rates.input : ""}">
</label>
<label class="field">Output $ / 1M<input name="output" type="number" min="0" max="10000" step="0.0001" inputmode="decimal" value="${ai.rates?.source === "custom" ? ai.rates.output : ""}">
</label>
<button class="btn small" type="submit">Save rates</button>
</form>
<p class="form-error" id="price-error" role="alert"></p>
<p class="tiny muted">Your own rates replace list prices for this model, for example on an institution endpoint. Leave both empty and save to clear them. Earlier requests keep the cost recorded at the time.</p>
</section>
</div>
<aside>
<section class="settings-section">
<h2>What is shared?</h2>
<p>${esc(ai.sharing)}</p>
<div class="boundary-flow">${icon("file")}<span>
<strong>Permitted context</strong>
<p>Questions, a saved research goal, field names/types, column names you confirmed, template source, AI code suggestions and unchanged AI-written cells.</p>
</span>
</div>
<div class="boundary-flow">${icon("lock")}<span>
<strong>Local only by default</strong>
<p>Manual notebook edits, dataset rows, measured values, notebook outputs and credentials.</p>
</span>
</div>
<p class="tiny muted">A localhost interface does not make a cloud model local. Use a provider and metadata-sharing policy approved for your dataset.</p>
<button class="link-btn" data-action="boundary" style="margin-top:17px">Inspect the full boundary ${icon("arrow")}</button>
</section>
<section class="settings-section">
<h2>Notebook setup</h2>
<p>${s.runtime.available ? "The isolated Docker/Jupyter runtime is available." : esc(s.runtime.reason)}</p>
<code class="mono">epsilon notebook-build</code>
<p class="footer-note">Run this command to prepare or update notebook libraries. Then choose Restart notebook in the notebook options. Saved code and outputs are kept; variables reset.</p>${runtimeLibrariesMarkup()}</section>
</aside>
</div>
</div>`;
}
function activityPage() {
  return `<div class="page">${heading("Project activity", "Saved runs and their reproducibility references.")}<div class="card card-pad">
<div class="timeline">${
    s.artifacts
      .map(
        (a) => `<div class="timeline-item">
<time>${esc(readableDate(a.created))}</time>
<h3>${esc(a.title)}</h3>
<p>Code ${esc(a.code_digest.slice(0, 12))} · input ${esc(a.input_digest.slice(0, 12))}</p>
<a class="link-btn" href="${base()}/analyses/${a.id}" style="margin-top:10px">Open saved result ${icon("arrow")}</a>
</div>`,
      )
      .join("") ||
    '<p class="muted tiny">Run a synthetic preview to record an analysis here.</p>'
  }</div>
</div>
<p class="footer-note">Audit decisions are recorded separately from editable conversation and notebook state. Existing .epsilon/chat transcripts are preserved.</p>
</div>`;
}

async function render() {
  const version = ++s.routeVersion;
  const route = parts();
  if (!s.session?.unlocked) {
    app.innerHTML = welcome(false);
    return;
  }
  if (
    route[0] === "signin" ||
    (!route.length && !s.session.account.authenticated)
  ) {
    app.innerHTML = welcome(true);
    document.title = "Sign in · Epsilon";
    return;
  }
  try {
    const projectsData = await api("/api/projects");
    if (version !== s.routeVersion) return;
    s.projects = projectsData.projects;
    let body, title;
    if (route[0] === "settings") {
      const [ai, runtime, usageReport] = await Promise.all([
        api("/api/settings/ai"),
        api("/api/runtime"),
        api("/api/usage"),
        loadModels(),
      ]);
      if (version !== s.routeVersion) return;
      s.session.ai = ai;
      s.runtime = runtime;
      s.usageReport = usageReport;
      body = settingsPage();
      title = "Settings";
    } else if (route[0] === "projects" && route[1]) {
      const [project, active] = await Promise.all([
        api(apiProject(route[1])),
        api(apiProject(route[1]) + "/jobs"),
      ]);
      if (version !== s.routeVersion) return;
      s.project = project;
      reconcileJobs(project.id, active.jobs);
      if (!project.ready) {
        let datasets = [];
        if (s.session.account.authenticated)
          datasets = (await api("/api/datasets")).datasets;
        if (version !== s.routeVersion) return;
        body = setupPage(datasets);
        title = "Project set-up";
      } else {
        const view = route[2] || "overview";
        if (["overview", "examples"].includes(view)) {
          const data = await api(
            apiProject(project.id) +
              "/examples" +
              (view === "examples" && route[3]
                ? "/" + encodeURIComponent(route[3])
                : ""),
          );
          if (version !== s.routeVersion) return;
          if (view === "examples" && route[3]) s.example = data;
          else s.examples = data.examples;
        }
        if (
          [
            "overview",
            "assistant",
            "notebook",
            "analyses",
            "activity",
            "dataset",
          ].includes(view)
        ) {
          const [artifacts, work] = await Promise.all([
            api(apiProject() + "/artifacts"),
            api(apiProject() + "/work"),
          ]);
          if (version !== s.routeVersion) return;
          s.artifacts = artifacts.artifacts;
          s.recentWork = work.work;
          s.workProject = project.id;
        }
        if (
          view === "assistant" &&
          new URLSearchParams(location.search).has("artifact")
        ) {
          const aid = new URLSearchParams(location.search).get("artifact");
          history.replaceState(
            {},
            "",
            base() + "/analyses/" + encodeURIComponent(aid),
          );
          return render();
        }
        if (["assistant", "notebook"].includes(view)) {
          if (!(await loadResearchWorkspace(route, version, project))) return;
          body = researchWorkspace();
          title = "Workspace";
        } else if (view === "examples") {
          body = route[3] ? examplePage(s.example) : examplesPage(s.examples);
          title = "Examples";
        } else if (view === "dataset") {
          if (s.fieldProject !== project.id) {
            s.fieldSearch = "";
            s.fieldProject = project.id;
          }
          body = datasetPage();
          title = "Data";
        } else if (view === "analyses") {
          body = analysesPage();
          title = "Results";
        } else if (view === "activity") {
          body = activityPage();
          title = "Activity";
        } else {
          body = overviewPage();
          title = "Overview";
        }
      }
    } else {
      body = projectsPage();
      title = "Datasets & projects";
    }
    if (version !== s.routeVersion) return;
    paintWorkspace(body, title);
    loadModels();
    renderTutorial();
    if (document.getElementById("approved-datasets")) ensureDatasetChoices();
    document.title =
      (s.project && route[1] ? s.project.name : title) + " · Epsilon";
  } catch (error) {
    if (version !== s.routeVersion) return;
    app.innerHTML = shell(
      `<div class="page">
<div class="empty-state">${icon("info", "lg")}<h3>We couldn't open this view.</h3>
<p>${esc(error.message)}</p>
<button class="btn primary" data-action="reload">Retry ${icon("refresh")}</button>
<a class="btn" href="/projects" style="margin-left:8px">All projects</a>${error.code === "local_session_required" ? '<button class="btn" data-action="reconnect">Reconnect browser</button>' : ""}</div>
</div>`,
      "Workspace",
    );
  }
}

async function start() {
  clearTutorialMarkup();
  app.innerHTML =
    '<div class="empty-state" style="margin:10vh auto;max-width:500px"><span class="spinner"></span> Opening Epsilon…</div>';
  try {
    const token = new URLSearchParams(location.hash.slice(1)).get("launch");
    if (token)
      history.replaceState({}, "", location.pathname + location.search);
    s.session = await api("/api/session");
    // A bookmark or reopened launch link may already be spent. The browser's
    // existing cookie takes precedence, including a session we can renew.
    if (token && !s.session.unlocked && !s.session.recoverable) {
      let bootstrapError;
      try {
        await post("/api/bootstrap", { token });
      } catch (error) {
        bootstrapError = error;
      }
      // Another tab may have unlocked this browser while we were connecting,
      // or the response may have been lost after its cookie was accepted.
      s.session = await api("/api/session");
      if (bootstrapError && !s.session.unlocked && !s.session.recoverable)
        throw bootstrapError;
    }
    resetDatasetChoices();
    s.csrf = s.session.csrf || "";
    if (s.session.recoverable) {
      await post("/api/session/renew");
      s.session = await api("/api/session");
    }
    if (s.session.unlocked) {
      s.projects = (await api("/api/projects")).projects;
      if (location.pathname === "/" && s.session.account.authenticated)
        history.replaceState({}, "", "/projects");
    }
    await render();
  } catch (error) {
    app.innerHTML = welcome(false);
    toast(error.message);
  }
}

async function submitQuestion(message, options = {}) {
  return once(pid() + ":question", () => sendQuestion(message, options));
}
async function sendQuestion(
  message,
  { preserveDraft = false, reviewedCell = null, fieldChoice = null } = {},
) {
  if (!message || workspaceJob("chat")) return;
  await flushNotebook({ persistDraft: true });
  const projectId = pid(),
    inWorkspace = ["assistant", "notebook"].includes(parts()[2]);
  let tid = inWorkspace ? s.thread?.id : null;
  if (!tid) {
    if (inWorkspace) {
      tid = (
        await post(
          apiProject(projectId) +
            "/notebooks/" +
            encodeURIComponent(s.notebook.id) +
            "/conversation",
        )
      ).thread_id;
    } else {
      tid = (
        await post(apiProject(projectId) + "/threads", {
          title: message.slice(0, 100),
        })
      ).id;
    }
  }
  const nid = inWorkspace ? s.notebook.id : tid;
  const requestedSelection = reviewedCell || s.selectedContext;
  const selection = inWorkspace ? selectedContext(requestedSelection) : null;
  if (
    (reviewedCell ||
      (inWorkspace &&
        requestedSelection?.project_id === projectId &&
        requestedSelection?.notebook_id === nid)) &&
    !selection
  )
    throw new Error(
      "The selected cell changed. Choose Use with AI again to review it, or remove it from this question.",
    );
  const submissionKey = JSON.stringify([
    projectId,
    tid,
    nid,
    message,
    selection?.context_digest,
  ]);
  const requestId = (s.outgoingQuestions[submissionKey] ||= crypto
    .randomUUID()
    .replaceAll("-", ""));
  const job = await post(
    apiProject(projectId) + "/threads/" + tid + "/messages",
    {
      message,
      notebook_id: nid,
      request_id: requestId,
      ...(fieldChoice ? { field_choice: fieldChoice } : {}),
      ...(selection
        ? {
            selected_cell: {
              cell_id: selection.cell_id,
              context_digest: selection.context_digest,
              confirmed: true,
              ...(selection.helper_cell_ids?.length
                ? { helper_cell_ids: selection.helper_cell_ids }
                : {}),
            },
          }
        : {}),
    },
  );
  delete s.outgoingQuestions[submissionKey];
  if (!preserveDraft) {
    s.selectedContext = null;
    s.drafts[
      projectId + "/" + (inWorkspace ? s.thread?.id || "overview" : "overview")
    ] = "";
  }
  s.jobs[job.id] = job;
  if (inWorkspace) await render();
  else await go(base(projectId) + "/assistant/" + tid);
  watch(job).catch(showError);
  return job;
}
function findArtifact(id) {
  return [...s.artifacts, ...(s.thread?.artifacts || [])].find(
    (a) => a.id === id,
  );
}
function download(name, content, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function saveNotebook() {
  if (s.notebookSaving) {
    await s.notebookSaving;
    if (s.notebookDirty) return saveNotebook();
    return s.notebook;
  }
  if (!s.notebook || !s.notebookDirty) return s.notebook;
  clearTimeout(s.saveTimer);
  s.notebookSaving = (async () => {
    for (let attempt = 0; attempt < 3; attempt++) {
      const snapshot = copyValue(s.notebook),
        projectId = s.notebookProject,
        status = document.getElementById("save-status");
      if (status) status.textContent = "Saving…";
      try {
        const result = await api(
          apiProject(projectId) +
            "/notebooks/" +
            encodeURIComponent(snapshot.id),
          {
            method: "PUT",
            body: {
              revision: snapshot.revision,
              title: snapshot.title,
              cells: snapshot.cells.map((c) => ({
                id: c.id,
                source: c.source,
                kind: c.kind || "code",
              })),
            },
          },
        );
        acceptNotebook(result, snapshot);
        if (snapshot.temporary) {
          s.starterDraft = null;
          const query = new URLSearchParams(location.search);
          query.delete("starter");
          query.delete("fields");
          history.replaceState(
            {},
            "",
            base(projectId) +
              "/notebook/" +
              encodeURIComponent(result.id) +
              (query.size ? "?" + query.toString() : ""),
          );
        }
        for (let i = 0; i < s.notebook.cells.length; i++) {
          const el = document.querySelector(`[data-markdown-cell="${i}"]`);
          if (el) el.innerHTML = s.notebook.cells[i].html || "";
        }
        if (status?.isConnected)
          status.textContent = s.notebookDirty
            ? "Unsaved edits"
            : "All changes saved";
        s.saveFailed = false;
        return result;
      } catch (error) {
        if (error.status !== 409) {
          s.saveFailed = true;
          if (status?.isConnected)
            status.textContent = "Not saved · retry Save";
          throw error;
        }
        const remote = await api(
          apiProject(projectId) +
            "/notebooks/" +
            encodeURIComponent(snapshot.id),
        );
        acceptNotebook(remote);
        if (!s.notebookDirty) return remote;
      }
    }
    throw new Error(
      "The notebook is changing. Your edits are still here; save again in a moment.",
    );
  })();
  try {
    return await s.notebookSaving;
  } finally {
    s.notebookSaving = null;
  }
}
async function executeCell(index, fromAll = false) {
  if (s.executingCell || workspaceJob("notebook") || (s.runningAll && !fromAll))
    return;
  s.executingCell = true;
  try {
    return await runCell(index);
  } finally {
    s.executingCell = false;
  }
}
async function runCell(index) {
  selectWorkspacePanel();
  await flushNotebook({ persistDraft: true });
  if (s.notebook.cells[index].kind === "markdown") {
    document
      .getElementById("cell-" + index)
      ?.closest(".cell-source")
      .removeAttribute("open");
    return;
  }
  const projectId = pid(),
    nid = s.notebook.id;
  const job = await post(
    apiProject(projectId) +
      "/notebooks/" +
      encodeURIComponent(nid) +
      "/execute",
    { cell: index, revision: s.notebook.revision },
  );
  s.jobs[job.id] = job;
  await render();
  return watch(job, async (result) => {
    if (result.notebook && pid() === projectId && s.notebook?.id === nid)
      acceptNotebook(result.notebook);
    if (pid() === projectId) await render();
    if (result.saved === false) toast(result.note);
  });
}
function boundary() {
  dialog(
    "Understand the data boundary",
    "The assistant helps develop a method; it does not authorise disclosure.",
    `<div class="boundary-flow">${icon("monitor")}<span>
<strong>Your machine</strong>
<p>Project files, synthetic rows, notebooks and local artifacts.</p>
</span>
</div>
<div class="boundary-flow">${icon("shield")}<span>
<strong>What AI sees</strong>
<p>Your questions, a saved research goal, field names and types, the column names you confirmed for your own words, AI code suggestions and unchanged cells previously written by AI. Use with AI shares one reviewed cell and any helper cells you explicitly check for that question. Fix with AI shares one failed cell and a short error description. Other manual edits and notebook outputs stay out of those requests.</p>
</span>
</div>
<div class="boundary-flow">${icon("spark")}<span>
<strong>Your approved model</strong>
<p>Permitted context leaves the machine when you use a cloud provider.</p>
</span>
</div>
<div class="notice">${icon("info")}<span>Never paste confidential rows or credentials into chat. Metadata sharing must be permitted for your dataset. Automated checks cannot determine every sensitive fact in a research question.</span>
</div>
<div class="rule">
</div>
<ul class="check-list">
<li>${icon("check")}The model has no file, shell, network or execution tools.</li>
<li>${icon("check")}Plans are validated independently and previewed through vetted operations.</li>
<li>${icon("check")}Notebook output stays separate from reviewed artifacts and model context.</li>
<li>${icon("check")}Small cells and complementary groups are withheld locally. Repeated-query inference and TRE approval require further review.</li>
</ul>`,
    `<button class="btn primary" data-action="close">Understood</button>`,
  );
}
const actions = {
  "use-example": (el) => useExample(el.dataset.id),
  "example-code": showExampleCode,
  close: close,
  reconnect: async () => {
    s.session = await api("/api/session");
    if (!s.session.unlocked && !s.session.recoverable) {
      dialog(
        "Reconnect this browser",
        "Your edits remain in this tab.",
        "<p>Open a fresh launch link from epsilon start in this browser, then retry saving.</p>",
      );
      return;
    }
    s.csrf = s.session.csrf;
    if (s.session.recoverable) await post("/api/session/renew");
    s.session = await api("/api/session");
    await render();
  },
  "choose-notebook": () =>
    dialog(
      "Open a notebook",
      "Choose the work you want to continue.",
      `<div class="modal-menu">${s.notebooks
        .map(
          (
            n,
          ) => `<a href="${base()}/notebook/${encodeURIComponent(n.id)}">${icon("notebook")}<span>${esc(n.title || "Research notebook")}</span>
</a>`,
        )
        .join("")}</div>`,
    ),
  "export-notebook": async () => {
    await flushNotebook({ persistDraft: true });
    const n = s.notebook;
    download(
      "epsilon-analysis.ipynb",
      JSON.stringify(
        {
          nbformat: 4,
          nbformat_minor: 5,
          metadata: {
            kernelspec: {
              name: "python3",
              display_name: "Python 3",
              language: "python",
            },
          },
          cells: n.cells.map((c) => ({
            id: c.id,
            cell_type: c.kind || "code",
            metadata: {},
            source: c.source.split(/(?<=\n)/),
            ...(c.kind === "markdown"
              ? {}
              : { execution_count: null, outputs: [] }),
          })),
        },
        null,
        2,
      ),
      "application/x-ipynb+json",
    );
  },
  "prepare-build": async () => {
    await flushNotebook({ persistDraft: true });
    const result = await api(
      apiProject() +
        "/notebooks/" +
        encodeURIComponent(s.notebook.id) +
        "/prepare-build",
    );
    const blocking = result.findings.filter((finding) => finding.blocking);
    s.preparedBuild = result.script;
    dialog(
      "Prepare for build",
      "Review-only source preparation · notebook revision " + result.revision,
      `<div class="review-list"><div class="review-row ${blocking.length ? "pending" : ""}">${icon(blocking.length ? "info" : "check")}<span><strong>${blocking.length ? "Needs attention before packaging" : "Ready for source review"}</strong><small>${esc(blocking.length ? blocking.map((finding) => finding.message).join(" · ") : "The selected Python cells passed the available local checks.")}</small></span></div><div class="review-row">${icon("database")}<span><strong>Dataset identity recorded</strong><small>${esc(result.provenance.dataset_id || "Dataset")} · schema ${esc(result.provenance.schema_hash || "not reported")}</small></span></div></div><p class="tiny muted">${esc(result.notice)}</p><details class="repair-source"><summary>Python source candidate</summary><pre><code>${esc(result.script)}</code></pre></details><details class="quiet-details"><summary>Runtime requirements</summary><p class="tiny muted">${esc(result.requirements.join(", ") || "The notebook runtime inventory is not available yet.")}</p></details>`,
      `<button class="btn" data-action="close">Close</button><button class="btn" data-action="download-prepared-build" ${blocking.length ? "disabled" : ""}>${icon("download")}Download Python source</button>`,
    );
  },
  "download-prepared-build": () =>
    download("epsilon-analysis.py", s.preparedBuild || ""),
  "notebook-runs": async (button) => {
    const offset = Number(button?.dataset.offset || 0);
    const { runs, next_offset } = await api(
      apiProject() +
        "/notebooks/" +
        encodeURIComponent(s.notebook.id) +
        "/runs?offset=" +
        offset,
    );
    dialog(
      "Notebook run history",
      "These local outputs are kept with the source that produced them.",
      runs
        .map(
          (run) => `<details class="run-history-entry">
<summary>${esc(readableDate(run.created))} · ${run.attached ? "Attached to cell" : "Source changed during run"}</summary>
<pre class="code">${esc(run.source)}</pre>${notebookOutput({ ...run.output, error: false }, -1)}</details>`,
        )
        .join("") || "<p>No cells have run yet.</p>",
      `${offset ? `<button class="btn" data-action="notebook-runs" data-offset="${Math.max(0, offset - 20)}">Newer runs</button>` : ""}${next_offset !== null ? `<button class="btn" data-action="notebook-runs" data-offset="${next_offset}">Older runs</button>` : ""}`,
    );
  },
  "preview-options": () =>
    dialog(
      "Create a saved preview",
      "These fixed count methods save a snapshot in Results.",
      `<div class="preview-options">${s.project.capabilities
        .filter((c) => c.runnable)
        .map(
          (c) => `<section>
<strong>${esc(c.title)}</strong>
<p>${
            Object.values(c.fields)
              .map((value) => `<code>${esc(value)}</code>`)
              .join(" × ") || "All available fields"
          }</p>
<button class="btn small" data-action="start-preview" data-id="${esc(c.key)}">Run preview</button>
</section>`,
        )
        .join("")}</div>`,
    ),
  "start-preview": async (el) => {
    await flushNotebook();
    const projectId = pid(),
      capability = s.project.capabilities.find((c) => c.key === el.dataset.id);
    const plan = await post(apiProject(projectId) + "/plans", {
      analysis: capability.key,
      fields: capability.fields,
    });
    const job = await post(
      apiProject(projectId) + "/plans/" + plan.id + "/run",
    );
    close();
    s.jobs[job.id] = job;
    watch(job, async (artifact) => {
      if (pid() === projectId)
        await go(
          base(projectId) + "/analyses/" + encodeURIComponent(artifact.id),
        );
    }).catch(showError);
    toast("Preparing the saved preview…");
  },
  "archived-work": async () => {
    const data = await api(apiProject() + "/work?archived=true");
    dialog(
      "Archived work",
      s.project.name,
      `<div class="work-history">${data.work.map((item) => workRow(item, true)).join("") || "<p>No archived work.</p>"}</div>`,
      '<button class="btn" data-action="history">Back to your work</button>',
    );
  },
  "archive-work": async (el) => {
    await flushNotebook();
    await post(
      apiProject() +
        "/" +
        el.dataset.kind +
        "/" +
        encodeURIComponent(el.dataset.id) +
        "/archive",
      { archived: el.dataset.archived === "true" },
    );
    await render();
    await actions[
      el.dataset.archived === "true" ? "history" : "archived-work"
    ]();
  },
  "clear-project-search": () => {
    s.search = "";
    paintWorkspace(projectsPage(), "Projects");
    document.getElementById("project-search")?.focus();
  },
  "clear-field-search": () => {
    s.fieldSearch = "";
    const input = document.getElementById("field-search");
    if (input) {
      input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
    }
  },
  "copy-field": async (el) => {
    await navigator.clipboard.writeText(el.dataset.field);
    toast("Field name copied.");
  },
  "copy-draft": async (el) => {
    const draft = s.thread.drafts.find((d) => d.id === el.dataset.id);
    if (draft) {
      await navigator.clipboard.writeText(draft.code);
      toast("Code copied.");
    }
  },
  "apply-code": (el) => applySuggestedCode(el.dataset.id, el.dataset.mode),
  "open-code-cell": (el) => openCodeCell(el.dataset.cellId),
  "prompt-suggestion": (el) => {
    const input = document.getElementById("chat-ask-input");
    if (input) {
      input.value = promptSuggestions()[Number(el.dataset.prompt)].question;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
  },
  "latest-message": () => {
    const pane = document.getElementById("chat-messages");
    if (pane) {
      pane.scrollTop = pane.scrollHeight;
      delete pane.dataset.unread;
      document.getElementById("latest-message").hidden = true;
    }
  },
  reload: () => start(),
  menu: () => updateNavigation(!s.mobile),
  "menu-close": () => updateNavigation(false, true),
  "start-tutorial": () => beginTutorial(true),
  "open-tutorial": () => beginTutorial(false),
  "pause-tutorial": pauseTutorial,
  "skip-tutorial": skipTutorial,
  boundary: boundary,
  signin: () => {
    s.returnTo = location.pathname;
    return go("/signin");
  },
  signout: async () => {
    await post("/api/auth/logout");
    s.session.account = { authenticated: false };
    resetDatasetChoices();
    s.returnTo = null;
    await go("/signin");
  },
  account: () =>
    dialog(
      "Epsilon account",
      "The browser and epsilon login share the same saved token.",
      `<div class="row">
<span class="avatar">${esc(initials(s.session.account.username))}</span>
<span>${esc(s.session.account.username || "Not signed in")}</span>
</div>`,
      `<a class="btn" href="/settings">Settings</a>
<button class="btn" data-action="${s.session.account.authenticated ? "signout" : "signin"}">${s.session.account.authenticated ? "Sign out" : "Sign in"}</button>`,
    ),
  "switch-project": () =>
    dialog(
      "Switch project",
      "Conversations and artifacts belong to their project.",
      `<div class="modal-menu">${s.projects
        .map(
          (p) => `<a href="${base(p.id)}">
<span class="project-icon">${icon("folder")}</span>
<span class="grow">${esc(p.name)}<small>${p.ready ? "Initialised" : "Needs set-up"}</small>
</span>${icon("arrow")}</a>`,
        )
        .join("")}</div>`,
    ),
  "refresh-datasets": refreshDatasetChoices,
  "choose-dataset": (el) => selectDataset(el.dataset.id),
  "retry-dataset": (el) => retryDatasetDetails(el.dataset.id),
  "project-details": () =>
    dialog(
      "Project details",
      "The registered folder remains the home of this project.",
      `<form id="project-edit-form" class="stack">
<label class="field">Name<input name="name" required maxlength="100" value="${esc(s.project.name)}">
</label>
<label class="field">Description<textarea name="description" maxlength="500">${esc(s.project.description)}</textarea>
</label>
<p class="mono muted" style="overflow-wrap:anywhere">${esc(s.project.path)}</p>
<p id="project-error" class="form-error" role="alert">
</p>
</form>`,
      `<button class="btn" data-action="close">Cancel</button>
<button class="btn primary" form="project-edit-form" type="submit">Save details</button>`,
    ),
  "capability-plan": (el) => {
    const c = s.project.capabilities.find((c) => c.key === el.dataset.key);
    return startPlan({ analysis: c.key, fields: c.fields }, el);
  },
  "run-plan": async (el) => {
    const projectId = pid(),
      threadId = s.thread.id;
    const job = await post(apiProject() + "/plans/" + el.dataset.id + "/run");
    s.jobs[job.id] = job;
    await render();
    watch(job, async () => {
      if (pid() === projectId && s.thread?.id === threadId) {
        await render();
        toast("Preview saved. Use View saved preview to open it in Results.");
      }
    }).catch(showError);
  },
  "plan-code": (el) => {
    const p = s.thread.plans.find((p) => p.id === el.dataset.id);
    dialog(
      p.title,
      "This source reproduces the controlled synthetic preview.",
      `<pre class="code">
<code>${esc(p.code)}</code>
</pre>`,
      `<button class="btn" data-action="open-notebook" data-kind="plan" data-id="${p.id}">${icon("notebook")}Open notebook</button>
<button class="btn primary" data-action="close">Done</button>`,
    );
  },
  "new-chat": async () => {
    await flushNotebook();
    const projectId = pid();
    const t = await post(apiProject() + "/threads", { title: "New analysis" });
    await go(base(projectId) + "/assistant/" + t.id);
  },
  history: async () => {
    const data = await api(apiProject() + "/work");
    dialog(
      "Your work",
      s.project.name,
      `<div class="work-history">${data.work.map((item) => workRow(item, true)).join("") || '<p class="muted">Your conversations, notebooks and results will appear here.</p>'}</div>`,
      `<button class="link-btn tiny" data-action="archived-work">Archived work</button>
<button class="link-btn tiny" data-action="import-history">Import older conversations</button>
<button class="btn primary" data-action="close">Done</button>`,
    );
  },
  "import-history": async () => {
    const result = await post(apiProject() + "/history/import");
    toast(
      `${result.imported} conversations imported. Existing history was preserved.`,
    );
    close();
  },
  "rename-thread": () =>
    dialog(
      "Rename conversation",
      "Use a title that helps you find this research later.",
      `<form id="thread-title-form">
<label class="field">Title<input name="title" required maxlength="100" value="${esc(s.thread.title)}">
</label>
</form>`,
      `<button class="btn primary" form="thread-title-form" type="submit">Save title</button>`,
    ),
  tab: async (el) => {
    s.tab = el.dataset.tab;
    paintResult();
    document.getElementById("tab-" + s.tab)?.focus({ preventScroll: true });
  },
  "download-code": (el) =>
    download("epsilon-analysis.py", findArtifact(el.dataset.id).code),
  "export-result": (el) =>
    download(
      "epsilon-preview.json",
      JSON.stringify(findArtifact(el.dataset.id), null, 2),
      "application/json",
    ),
  provenance: (el) => {
    const a = findArtifact(el.dataset.id);
    dialog(
      "Analysis provenance",
      "This record belongs to the saved preview, even after notebook edits.",
      `<div class="detail-list">${[
        ["Dataset", a.dataset_id],
        ["Archetype", a.archetype_id],
        ["Version", a.dataset_version],
        ["Engine", a.engine_version],
        ["Code digest", a.code_digest],
        ["Input digest", a.input_digest],
      ]
        .map(
          ([k, v]) => `<div>
<span>${k}</span>
<strong class="mono" style="max-width:65%;overflow-wrap:anywhere">${esc(v ?? "Not reported")}</strong>
</div>`,
        )
        .join("")}</div>`,
    );
  },
  review: async (el) => {
    const a = findArtifact(el.dataset.id);
    const check = await post(apiProject() + "/artifacts/" + a.id + "/checks");
    dialog(
      "Review & export",
      a.title,
      `<div class="review-list">
<div class="review-row">${icon("check")}<span>Code and dataset identity recorded<small>Exact preview source and provenance included.</small>
</span>
</div>
<div class="review-row ${check.findings.some((f) => f.blocking) ? "pending" : ""}">${icon("info")}<span>SDK source checks<small>${esc(check.findings.map((f) => f.message).join(" · ") || "No blocking source findings in the selected preview code.")}</small>
</span>
</div>
<div class="review-row pending">${icon("shield")}<span>TRE approval not requested<small>Review export is not a deployment or submission bundle.</small>
</span>
</div>
</div>
<p class="tiny muted">The ZIP includes source, a manifest and instructions. It excludes dataset rows, notebook outputs, credentials and conversations.</p>`,
      `<button class="btn" data-action="close">Keep exploring</button>
<a class="btn primary" href="${apiProject()}/artifacts/${a.id}/export" download>${icon("download")}Download review ZIP</a>`,
    );
  },
  "open-notebook": async (el) => {
    await flushNotebook();
    const projectId = pid();
    const n = await post(apiProject() + "/notebooks/import", {
      kind: el.dataset.kind,
      object_id: el.dataset.id,
    });
    await go(base(projectId) + "/notebook/" + encodeURIComponent(n.id));
  },
  "save-notebook": async () => {
    await flushNotebook({ persistDraft: true });
    toast("Notebook source saved locally.");
  },
  "add-cell": () => {
    s.notebook.cells.push({
      id: newCellId(),
      kind: "code",
      source: "",
      output: null,
    });
    s.notebookDirty = true;
    paintWorkspace(researchWorkspace(), "Workspace");
  },
  "add-markdown": () => {
    s.notebook.cells.push({
      id: newCellId(),
      kind: "markdown",
      source: "## Research notes\n",
      output: null,
    });
    s.notebookDirty = true;
    paintWorkspace(researchWorkspace(), "Workspace");
  },
  "workspace-layout": (el) => {
    selectWorkspaceLayout(el.dataset.layout);
    paintWorkspace(researchWorkspace(), "Workspace");
  },
  "undo-cell": async (el) => {
    await flushNotebook();
    const value = await post(
      apiProject() +
        "/notebooks/" +
        encodeURIComponent(s.notebook.id) +
        "/changes/" +
        encodeURIComponent(el.dataset.change) +
        "/undo",
    );
    acceptNotebook(value);
    await render();
    toast("Code change undone.");
  },
  "notebook-info": () =>
    dialog(
      "Your notebook",
      "Code and results are saved in this project.",
      '<p>AI suggests code in chat. You decide where to add it and when to run it. Cells run in a local container without network access. Notebook outputs stay out of AI context and saved analysis previews.</p><p style="margin-top:12px">Export includes source only. Restarting clears variables while keeping saved code and outputs.</p>',
    ),
  "use-cell-context": reviewCell,
  "confirm-cell-context": confirmCellContext,
  "explain-cell": () => confirmCellContext("explain"),
  "clear-cell-context": async () => {
    s.selectedContext = null;
    await render();
  },
  "retry-question": retryRequest,
  "research-context": editResearchContext,
  "fix-cell": (el) => requestCellRepair(el),
  "send-repair": (el) => sendCellRepair(el),
  "run-cell": (el) => executeCell(Number(el.dataset.cell)),
  "run-all": async () => {
    if (s.runningAll || s.executingCell || workspaceJob("notebook")) return;
    s.runningAll = true;
    try {
      const count = s.notebook.cells.length,
        projectId = pid(),
        notebookId = s.notebook.id;
      let completed = true;
      for (let i = 0; i < count; i++) {
        if (pid() !== projectId || s.notebook?.id !== notebookId) break;
        await executeCell(i, true);
        if (
          s.notebook.cells[i].kind === "code" &&
          s.notebook.cells[i].output?.error
        ) {
          completed = false;
          break;
        }
      }
      if (completed && pid() === projectId && s.notebook?.id === notebookId)
        tutorialAdvance("run");
    } finally {
      s.runningAll = false;
    }
  },
  "stop-kernel": async () => {
    await flushNotebook();
    await post(
      apiProject() +
        "/notebooks/" +
        encodeURIComponent(s.notebook.id) +
        "/stop",
    );
    await render();
    toast("Notebook restarted. Run the cells again to rebuild variables.");
  },
  "cancel-job": async (el) => {
    await post(
      apiProject(el.dataset.project) + "/jobs/" + el.dataset.id + "/cancel",
    );
    toast("Cancellation requested. Committed work is preserved.");
  },
  "test-ai": async (el) => {
    const result = document.getElementById("ai-test-result"),
      form = document.getElementById("ai-form"),
      ai = s.session.ai;
    if (!result || !form) return;
    if (
      ["provider", "model", "base_url"].some(
        (key) => form.elements[key].value.trim() !== (ai[key] || ""),
      ) ||
      form.elements.api_key.value
    ) {
      result.dataset.ok = "false";
      result.textContent = "Save your changes before testing the connection.";
      return;
    }
    el.disabled = true;
    result.removeAttribute("data-ok");
    result.textContent = "Checking connection…";
    try {
      const checked = await post("/api/settings/ai/test");
      if (result.isConnected) {
        result.dataset.ok = String(checked.connected);
        result.textContent = checked.message;
      }
    } catch (error) {
      if (result.isConnected) {
        result.dataset.ok = "false";
        result.textContent = error.message;
      }
    } finally {
      if (el.isConnected) el.disabled = false;
    }
  },
  "forget-field": async (el) => {
    await post(apiProject(pid()) + "/vocabulary/forget", {
      term: el.dataset.term,
    });
    el.closest("li")?.remove();
  },
  "choose-field": (el) =>
    submitQuestion(`Use ${el.dataset.path} for "${el.dataset.term}".`, {
      fieldChoice: { term: el.dataset.term, path: el.dataset.path },
    }),
  "cli-ai": async () => {
    const result = await post("/api/settings/ai/cli");
    s.session.ai = result;
    s.models = null;
    await render();
    toast(
      "Using the existing epsilon ai login configuration." +
        (result.credential_cleanup === false
          ? " The old workspace credential could not be removed from your OS keyring."
          : ""),
    );
  },
};

document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-action]");
  if (el && !el.disabled) {
    event.preventDefault();
    once(
      pid() +
        ":" +
        el.dataset.action +
        ":" +
        (el.dataset.id || el.dataset.change || ""),
      () => actions[el.dataset.action]?.(el),
      el,
    ).catch(showError);
  } else navigateLink(event);
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  event.preventDefault();
  if (form.dataset.submitting === "true") return;
  form.dataset.submitting = "true";
  const submit =
    document.querySelector(`button[form="${form.id}"]`) ||
    form.querySelector('button[type="submit"]');
  if (submit) submit.disabled = true;
  try {
    if (form.id === "login-form") {
      const label = submit?.innerHTML;
      form.querySelector('[role="alert"]').textContent = "";
      form.setAttribute("aria-busy", "true");
      if (submit) submit.textContent = "Signing in…";
      try {
        s.session.account = await post("/api/auth/login", {
          username: form.elements.username.value.trim(),
          password: form.elements.password.value,
        });
        resetDatasetChoices();
        const destination = s.returnTo || "/projects";
        s.returnTo = null;
        await go(destination);
      } finally {
        form.elements.password.value = "";
        form.removeAttribute("aria-busy");
        if (submit?.isConnected) submit.innerHTML = label;
      }
    } else if (form.id === "research-context-form") {
      await saveResearchContext(form);
    } else if (form.id === "dataset-project-form") {
      await createDatasetProject(form);
    } else if (form.id === "project-edit-form") {
      await api(apiProject(), {
        method: "PATCH",
        body: {
          name: form.elements.name.value,
          description: form.elements.description.value,
        },
      });
      close();
      await render();
    } else if (form.id === "setup-form") {
      const projectId = pid();
      const job = await post(apiProject() + "/initialise", {
        dataset_id: form.elements.dataset_id.value,
        dummy_data: form.elements.dummy_data.checked,
      });
      s.jobs[job.id] = job;
      await render();
      watch(job, async (result) => {
        if (pid() === projectId) await go(base(projectId));
        toast(
          result.warnings?.join(" ") ||
            "Project initialised. Your dataset is ready to explore.",
        );
      }).catch(showError);
    } else if (form.classList.contains("ask-form")) {
      const job = await submitQuestion(form.elements.message.value.trim());
      if (job) tutorialAdvance("ask");
    } else if (form.id === "thread-title-form") {
      if (s.thread.id) {
        await api(
          apiProject() + "/threads/" + encodeURIComponent(s.thread.id),
          {
            method: "PATCH",
            body: { title: form.elements.title.value },
          },
        );
      } else {
        s.notebook.title = form.elements.title.value;
        s.notebookDirty = true;
        await flushNotebook();
      }
      close();
      await render();
    } else if (form.id === "price-form") {
      const rate = (name) =>
        form.elements[name].value === ""
          ? null
          : Number(form.elements[name].value);
      document.getElementById("price-error").textContent = "";
      s.session.ai = await post("/api/settings/ai/price", {
        model: s.session.ai.model,
        input: rate("input"),
        output: rate("output"),
      });
      s.models = null;
      await render();
      toast("Rates saved. They apply to new requests.");
    } else if (form.id === "ai-form") {
      const result = await post("/api/settings/ai", {
        provider: form.elements.provider.value,
        model: form.elements.model.value,
        base_url: form.elements.base_url.value,
        api_key: form.elements.api_key.value,
        persist: form.elements.persist.checked,
      });
      form.elements.api_key.value = "";
      s.session.ai = result;
      s.models = null;
      await render();
      toast(
        "Connection saved. Credential storage: " +
          (result.saved_in || "not needed") +
          "." +
          (result.credential_cleanup === false
            ? " The old workspace credential could not be removed from your OS keyring."
            : ""),
      );
    }
  } catch (error) {
    const target = form.querySelector('[role="alert"]');
    if (target) target.textContent = error.message;
    else showError(error);
  } finally {
    delete form.dataset.submitting;
    if (submit?.isConnected) submit.disabled = false;
  }
});
document.addEventListener("input", (event) => {
  const el = event.target;
  if (el.id === "field-search") {
    s.fieldSearch = el.value;
    const result = fieldRows();
    document.getElementById("field-rows").innerHTML = result.rows;
    document.getElementById("field-count").textContent =
      result.count + " of " + s.project.dataset.fields.length + " fields";
    labelControls();
  }
  if (el.id === "project-search") {
    const position = el.selectionStart;
    s.search = el.value;
    paintWorkspace(projectsPage(), "Projects");
    const input = document.getElementById("project-search");
    input.focus();
    input.setSelectionRange(position, position);
  }
  if (el.closest(".ask-form") && el.tagName === "TEXTAREA")
    s.drafts[
      pid() +
        "/" +
        (el.closest(".ask-form").id === "chat-ask"
          ? s.thread?.id || "overview"
          : "overview")
    ] = el.value;
  if (el.matches(".cell-editor")) {
    const cell = s.notebook.cells[Number(el.dataset.cell)];
    cell.source = el.value;
    const context = document.querySelector(".assistant-context");
    if (context) context.outerHTML = contextMarkup();
    cell.output = null;
    delete cell.digest;
    markLaterOutputsStale(Number(el.dataset.cell));
    if (cell.ai) cell.ai.can_undo = false;
    if (cell.kind === "markdown") {
      cell.html = "";
      el.closest(".notebook-cell").querySelector(".markdown-cell").textContent =
        "Save or press Shift+Enter to render these notes.";
    }
    s.notebookDirty = true;
    el.closest(".notebook-cell").querySelector(".cell-output")?.remove();
    document.getElementById("save-status").textContent = "Unsaved edits";
    clearTimeout(s.saveTimer);
    if (!s.saveFailed)
      s.saveTimer = setTimeout(() => saveNotebook().catch(showError), 800);
  }
});
document.addEventListener("change", (event) => {
  const el = event.target;
  if (el.matches("[data-model-picker]")) {
    chooseModel(el, go);
    return;
  }
  if (el.matches("[data-helper-cell]")) {
    refreshContextPreview().catch(showError);
    return;
  }
  if (el.id === "result-table") {
    s.table = Number(el.value);
    paintResult();
  }
  if (el.id === "chart-type") {
    s.chart = el.value;
    paintResult();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && s.tutorial?.active) {
    event.preventDefault();
    pauseTutorial();
    return;
  }
  if (
    event.target.matches(".ask-form textarea") &&
    event.key === "Enter" &&
    !event.shiftKey
  ) {
    event.preventDefault();
    event.target.form.requestSubmit();
  }
  if (
    event.target.matches('[role="tab"]') &&
    ["ArrowLeft", "ArrowRight"].includes(event.key)
  ) {
    event.preventDefault();
    const tabs = [...event.target.parentElement.children];
    const i = tabs.indexOf(event.target);
    tabs[
      (i + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length
    ].click();
  }
});
window.addEventListener("resize", repositionTutorial);
document.addEventListener("scroll", repositionTutorial, true);
window.addEventListener("popstate", async () => {
  try {
    await flushNotebook();
    s.project = null;
    s.thread = null;
    await render();
  } catch (error) {
    showError(error);
  }
});
window.addEventListener("beforeunload", (event) => {
  if (s.notebookDirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});
start();

export {
  artifactRow,
  askBox,
  drawChart,
  executeCell,
  go,
  heading,
  messageHTML,
  planCard,
  progressMarkup,
  render,
  resultTable,
  saveNotebook,
  settingsPage,
  shell,
  submitQuestion,
};
