// Shared state and helpers every module needs. This module imports nothing,
// so it can load first and no other module has to import app.js for basics.

const app = document.getElementById("app");
const modal = document.getElementById("modal");
const icons = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/><path d="M9 21v-8h6v8"/>',
  chat: '<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0Z"/><path d="M7 9h10M7 13h7"/>',
  database:
    '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  chart: '<path d="M4 3v17h17M8 16v-5M13 16V6M18 16v-8"/>',
  trend: '<path d="M3 18 9 12l4 3 8-10M15 5h6v6"/>',
  pie: '<path d="M12 3v9h9A9 9 0 1 1 12 3Z"/><path d="M15 2v7h7a9 9 0 0 0-7-7Z"/>',
  code: '<path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18"/>',
  notebook:
    '<rect x="5" y="3" width="15" height="18" rx="2"/><path d="M3 7h4M3 12h4M3 17h4M10 8h6M10 12h6"/>',
  folder:
    '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
  shield:
    '<path d="m12 2 8 3v7c0 5-8 10-8 10S4 17 4 12V5Z"/><path d="m8 11 3 3 5-5"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  up: '<path d="M12 19V5m-6 6 6-6 6 6"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  spark:
    '<path d="m12 3 2.8 6.2L21 12l-6.2 2.8L12 21l-2.8-6.2L3 12l6.2-2.8ZM20 2v4m-2-2h4"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  settings:
    '<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM9 3h6l.5 3 2.5 1 3 1-1 5 .5 3-4 3-2.5-1-3 3-4-2v-3l-3-2 1-5 3-1Z"/>',
  history: '<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v6l4 2"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  play: '<path d="m8 4 13 8-13 8Z"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  refresh:
    '<path d="M20 7v5h-5M4 17v-5h5M4 8a8 8 0 0 1 14-4l2 3M4 17l2 3a8 8 0 0 0 14-4"/>',
  table:
    '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
  file: '<path d="M14 2H5v20h14V7ZM14 2v5h5M8 12h8M8 16h6"/>',
  copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  edit: '<path d="m15 4 5 5M4 20l5-1L21 7l-4-4L5 15Zm0 0 5-1-4-4"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 3H3v18h18v-7"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  logOut: '<path d="M10 3H3v18h7M9 12h12m-5-5 5 5-5 5"/>',
  monitor:
    '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M12 17v5m-5 0h10"/>',
  route:
    '<circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M9 5h7a4 4 0 0 1 0 8H8a3 3 0 0 0 0 6h7"/>',
  layers: '<path d="m12 2 10 6-10 6L2 8Zm-9 11 9 5 9-5M3 17l9 5 9-5"/>',
};
const icon = (name, cls = "") =>
  `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        ch
      ],
  );

const s = {
  recentWork: [],
  workProject: null,
  fieldSearch: "",
  fieldProject: null,
  layout: "both",
  notebookBase: null,
  chatWidth: 0.38,
  csrf: "",
  session: null,
  selectedContext: null,
  outgoingQuestions: {},
  projects: [],
  project: null,
  thread: null,
  artifacts: [],
  notebook: null,
  notebookDirty: false,
  notebookSaving: null,
  saveTimer: null,
  tab: "chart",
  table: 0,
  chart: "bar",
  jobs: {},
  mobile: false,
  drafts: {},
  routeVersion: 0,
  search: "",
  runtime: null,
  returnTo: "/projects",
  notebookProject: null,
  watched: new Set(),
  watchers: {},
  tutorial: null,
};
const fmt = (n) => new Intl.NumberFormat().format(n ?? 0);
const pid = () => parts()[1];
const parts = () =>
  location.pathname.split("/").filter(Boolean).map(decodeURIComponent);
const base = (id = pid()) => "/projects/" + encodeURIComponent(id);
const apiProject = (id = pid()) => "/api/projects/" + encodeURIComponent(id);

async function api(url, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.method && options.method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-Epsilon-CSRF"] = s.csrf;
  }
  const controller = new AbortController(),
    timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
      signal: controller.signal,
      headers,
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (data.code === "local_session_required" && !options.reconnected) {
        if (!s.reconnecting)
          s.reconnecting = (async () => {
            const session = await api("/api/session");
            if (!session.unlocked && !session.recoverable)
              throw new Error(
                "Open a fresh launch link from epsilon start to reconnect this browser. Your unsaved edits are still here.",
              );
            s.csrf = session.csrf;
            if (session.recoverable) await post("/api/session/renew");
          })().finally(() => (s.reconnecting = null));
        await s.reconnecting;
        return api(url, { ...options, reconnected: true });
      }
      const error = new Error(
        data.error || data.detail || "The request failed. Please retry.",
      );
      error.status = response.status;
      error.code = data.code;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error(
        "The server took too long to respond. Your edits are still here; retry shortly.",
      );
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
const post = (url, body = {}) => api(url, { method: "POST", body });
function toast(message) {
  const node = document.createElement("div");
  node.className = "toast";
  node.textContent = message;
  document.getElementById("toasts").replaceChildren(node);
  setTimeout(() => node.remove(), 5000);
}
function showError(error) {
  toast(error.message || String(error));
}
function dialog(title, subtitle, body, footer = "") {
  modal.innerHTML = `<div class="modal-header">
<div>
<h2 id="modal-title">${esc(title)}</h2>
<p>${esc(subtitle)}</p>
</div>
<button class="icon-btn" data-action="close" aria-label="Close dialog">${icon("close")}</button>
</div>
<div class="modal-body">${body}</div>${footer ? `<div class="modal-footer">${footer}</div>` : ""}`;
  if (!modal.open) modal.showModal();
  labelControls();
}
function close() {
  if (modal.open) modal.close();
}
modal.addEventListener("close", () => {
  s.repairReview = null;
  s.contextReview = null;
});

function labelControls() {
  document
    .querySelectorAll(".icon-btn[aria-label],summary[aria-label]")
    .forEach((el) => (el.title = el.getAttribute("aria-label")));
}

export {
  app,
  modal,
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
};
