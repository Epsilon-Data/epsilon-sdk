import { requestRecovery } from "./assistant-controls.js";
import { fieldChoices, messageUsage, workspaceUsage } from "./usage.js";
import {
  api,
  apiProject,
  app,
  base,
  esc,
  icon,
  parts,
  pid,
  post,
  s,
  showError,
  toast,
  labelControls,
} from "./core.js";
import {
  askBox,
  go,
  messageHTML,
  planCard,
  progressMarkup,
  settingsPage,
  shell,
} from "./app.js";
import { exampleNotebookHint } from "./examples.js";
import {
  flushNotebook,
  rememberView,
  restoreView,
  updateNavigation,
} from "./interactions.js";
import { notebookCell } from "./notebook.js";
import {
  notebookLibraryNotice,
  notebookRuntimeNotice,
  notebookWelcome,
  promptSuggestions,
} from "./pages.js";

const starters = {
  describe: ["Explore the data", "See a summary of the available fields."],
  composition: ["Compare groups", "Compare record counts across groups."],
  cross_tab: ["Compare two variables", "See how two categories relate."],
  trend: ["Explore changes over time", "Plot record counts by date."],
};
const cellValue = (c) => JSON.stringify([c.kind || "code", c.source]);
const notebookSignature = (n) =>
  JSON.stringify(n.cells.map((c) => [c.id, c.kind || "code", c.source]));
const copyValue = (value) => JSON.parse(JSON.stringify(value));
const newCellId = () => "cell-" + crypto.randomUUID().replaceAll("-", "");
async function startPlan(card, button = null) {
  if (s.startingPlan) return;
  const projectId = pid(),
    origin = location.href;
  const original = button?.innerHTML;
  s.startingPlan = true;
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    const arrow = button.querySelector(".card-arrow");
    if (arrow) arrow.innerHTML = '<span class="spinner"></span>';
  }
  try {
    await flushNotebook();
    const notebook = await post(apiProject(projectId) + "/starters", {
      analysis: card.analysis,
      fields: card.fields || {},
    });
    if (pid() !== projectId || location.href !== origin) return;
    s.starterDraft = { projectId, notebook };
    const query = new URLSearchParams({
      layout: "both",
      starter: card.analysis,
      fields: JSON.stringify(card.fields || {}),
    });
    await go(
      base(projectId) +
        "/notebook/" +
        encodeURIComponent(notebook.id) +
        "?" +
        query.toString(),
    );
  } finally {
    s.startingPlan = false;
    if (button?.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.innerHTML = original;
    }
  }
}
function mergeNotebook(local, baseline, remote) {
  const result = copyValue(remote),
    before = new Map((baseline?.cells || []).map((c) => [c.id, c]));
  let conflicts = 0;
  const moved = {};
  for (const cell of local.cells) {
    const old = before.get(cell.id);
    if (old && cellValue(old) === cellValue(cell)) continue;
    const index = result.cells.findIndex((c) => c.id === cell.id),
      server = result.cells[index];
    if (server && cellValue(server) === cellValue(cell)) continue;
    const changed = server && (!old || cellValue(server) !== cellValue(old));
    const kept = copyValue(cell);
    kept.output = null;
    if (changed) {
      kept.id = newCellId();
      delete kept.ai;
      result.cells.push(kept);
      moved[cell.id] = kept.id;
      conflicts++;
    } else if (index >= 0) result.cells[index] = kept;
    else result.cells.push(kept);
  }
  return { notebook: result, conflicts, moved };
}
function acceptNotebook(remote, baseline = s.notebookBase) {
  if (
    s.notebookBase?.id === remote.id &&
    remote.revision < s.notebookBase.revision
  )
    return;
  if (
    s.notebookDirty &&
    s.notebook?.id === remote.id &&
    s.notebookProject === pid()
  ) {
    const merged = mergeNotebook(s.notebook, baseline, remote);
    s.notebook = merged.notebook;
    s.selectionRemap = { ...s.selectionRemap, ...merged.moved };
    s.notebookDirty =
      notebookSignature(s.notebook) !== notebookSignature(remote);
    if (merged.conflicts)
      toast("Your edits were kept in a separate cell alongside the AI update.");
  } else {
    s.notebook = remote;
    s.notebookDirty = false;
  }
  s.notebookBase = copyValue(remote);
}
function workspaceMode() {
  const requested = new URLSearchParams(location.search).get("layout");
  if (["both", "assistant", "notebook"].includes(requested)) return requested;
  try {
    const saved = localStorage.getItem("epsilon.workspace.layout");
    if (["both", "assistant", "notebook"].includes(saved)) return saved;
  } catch {}
  return "both";
}
function selectWorkspacePanel() {
  const url = new URL(location.href);
  url.searchParams.delete("artifact");
  url.searchParams.delete("panel");
  if (s.layout === "assistant") {
    s.layout = "both";
    url.searchParams.set("layout", "both");
  }
  // A notebook render must not restore a result the researcher already left.
  history.replaceState({}, "", url.pathname + url.search);
}
function selectWorkspaceLayout(layout) {
  s.layout = layout;
  if (layout !== "assistant") selectWorkspacePanel();
  try {
    localStorage.setItem("epsilon.workspace.layout", s.layout);
  } catch {}
  const url = new URL(location.href);
  url.searchParams.set("layout", s.layout);
  history.replaceState({}, "", url.pathname + url.search);
}
function workspaceJob(kind) {
  return Object.values(s.jobs).find(
    (j) =>
      j.project_id === pid() &&
      ["queued", "running"].includes(j.status) &&
      (kind
        ? j.kind === kind
        : ["chat", "notebook", "preview"].includes(j.kind)) &&
      (j.kind !== "chat" || j.scope === pid() + ":thread:" + s.thread?.id) &&
      (j.kind !== "notebook" ||
        j.scope === pid() + ":notebook:" + s.notebook?.id),
  );
}
async function loadResearchWorkspace(route, version, project) {
  const query = new URLSearchParams(location.search);
  let tid = route[2] === "assistant" ? route[3] : null;
  let nid =
    route[2] === "notebook" ? route[3] || "main" : query.get("notebook");
  if (query.has("starter")) {
    const cached = s.starterDraft;
    const notebook =
      cached?.projectId === project.id && cached.notebook.id === nid
        ? cached.notebook
        : await post(apiProject(project.id) + "/starters", {
            analysis: query.get("starter"),
            fields: JSON.parse(query.get("fields") || "{}"),
          });
    const runtime = await api("/api/runtime");
    if (version !== s.routeVersion) return false;
    s.notebookProject = project.id;
    s.notebookDirty = false;
    s.notebook = copyValue(notebook);
    s.notebookBase = copyValue(notebook);
    s.starterDraft = { projectId: project.id, notebook };
    s.thread = {
      id: null,
      title: notebook.title,
      messages: [],
      plans: [],
      artifacts: [],
      drafts: [],
    };
    s.notebooks = [{ id: notebook.id, title: notebook.title }];
    s.runtime = runtime;
    s.layout = workspaceMode();
    history.replaceState(
      {},
      "",
      base(project.id) +
        "/notebook/" +
        encodeURIComponent(notebook.id) +
        "?" +
        query.toString(),
    );
    return true;
  }
  if (route[2] === "assistant" && !tid && !nid && s.recentWork?.length) {
    const recent = s.recentWork[0];
    tid = recent.thread_id;
    nid = recent.notebook_id;
  }
  let notebook;
  if (!tid || nid) {
    nid = nid || "main";
    const linked = await post(
      apiProject() + "/notebooks/" + encodeURIComponent(nid) + "/conversation",
    );
    if (tid && tid !== linked.thread_id)
      throw new Error("Choose the conversation linked to this notebook.");
    tid = linked.thread_id;
    notebook = await api(
      apiProject() + "/notebooks/" + encodeURIComponent(nid),
    );
  } else {
    notebook = await post(
      apiProject() + "/threads/" + encodeURIComponent(tid) + "/notebook",
    );
    nid = notebook.id;
  }
  const [thread, notebooks, runtime] = await Promise.all([
    api(apiProject() + "/threads/" + encodeURIComponent(tid)),
    api(apiProject() + "/notebooks"),
    api(apiProject() + "/notebooks/" + encodeURIComponent(nid) + "/runtime"),
  ]);
  if (version !== s.routeVersion) return false;
  if (s.notebookProject !== project.id || s.notebook?.id !== nid) {
    s.notebookDirty = false;
    s.notebookBase = null;
  }
  s.notebookProject = project.id;
  acceptNotebook(notebook);
  s.thread = thread;
  s.notebooks = notebooks.notebooks;
  s.runtime = runtime;
  if (!s.notebooks.some((n) => n.id === nid))
    s.notebooks.unshift({ id: nid, title: "Research notebook" });
  // Panel/layout choices can change while the notebook requests are in flight.
  const currentQuery = new URLSearchParams(location.search);
  s.layout = workspaceMode();
  currentQuery.delete("artifact");
  currentQuery.delete("panel");
  history.replaceState(
    {},
    "",
    location.pathname +
      (currentQuery.size ? "?" + currentQuery.toString() : ""),
  );
  try {
    const width = Number(localStorage.getItem("epsilon.workspace.paneWidth"));
    if (width >= 0.27 && width <= 0.6) s.chatWidth = width;
  } catch {}
  if (route[2] === "assistant" && !route[3]) {
    currentQuery.set("notebook", nid);
    history.replaceState(
      {},
      "",
      base() + "/assistant/" + tid + "?" + currentQuery.toString(),
    );
  }
  return true;
}
function paintWorkspace(body, title) {
  const viewKey = location.pathname,
    remembered = s.paintedView === viewKey ? rememberView() : [];
  const focus = document.activeElement,
    selection = focus?.matches("textarea,input")
      ? {
          id: focus.id,
          cellId: focus.dataset.cellId,
          start: focus.selectionStart,
          end: focus.selectionEnd,
        }
      : null;
  const chat = document.getElementById("chat-messages"),
    followChat =
      !chat || chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
  const context = pid() + "/" + s.thread?.id,
    newThread = s.paintedThread !== context,
    unread =
      chat?.dataset.unread === "true" ||
      (!followChat &&
        (s.thread?.messages.length || 0) > (s.paintedMessages || 0));
  const scrolls = ["chat-messages", "notebook-pane"].map((id) => ({
    id,
    top: document.getElementById(id)?.scrollTop || 0,
  }));
  app.innerHTML = shell(body, title);
  restoreView(remembered);
  s.paintedView = viewKey;
  updateNavigation(s.mobile);
  for (const item of scrolls) {
    const node = document.getElementById(item.id);
    if (node) node.scrollTop = item.top;
  }
  const next = document.getElementById("chat-messages");
  if (next) {
    if (newThread || followChat) next.scrollTop = next.scrollHeight;
    else if (unread) {
      next.dataset.unread = "true";
      document.getElementById("latest-message").hidden = false;
    }
    s.paintedThread = context;
    s.paintedMessages = s.thread?.messages.length || 0;
  }
  labelControls();
  if (s.runtime?.checking && !s.runtimeTimer) {
    s.runtimeTimer = setTimeout(async () => {
      s.runtimeTimer = null;
      try {
        const project = pid(),
          notebook = s.notebook?.id;
        const runtime = await api(
          notebook
            ? apiProject() +
                "/notebooks/" +
                encodeURIComponent(notebook) +
                "/runtime"
            : "/api/runtime",
        );
        if (project !== pid() || notebook !== s.notebook?.id) return;
        s.runtime = runtime;
        if (["assistant", "notebook"].includes(parts()[2]))
          paintWorkspace(researchWorkspace(), "Workspace");
        else if (parts()[0] === "settings")
          paintWorkspace(settingsPage(), "Settings");
      } catch {}
    }, 1500);
  }
  if (selection) {
    const cellId = s.selectionRemap?.[selection.cellId] || selection.cellId;
    const node = cellId
      ? document.querySelector(`.cell-editor[data-cell-id="${cellId}"]`)
      : document.getElementById(selection.id);
    if (node) {
      node.focus({ preventScroll: true });
      node.setSelectionRange(selection.start, selection.end);
    }
  }
  s.selectionRemap = {};
}
function codeDraftCard(draft) {
  const sameBook = !draft.notebook_id || draft.notebook_id === s.notebook.id;
  const applied =
    draft.applied ||
    (draft.workflow !== "review" && draft.cell_id
      ? { cell_id: draft.cell_id }
      : null);
  const index = sameBook
    ? s.notebook.cells.findIndex(
        (c) => c.id === (applied?.cell_id || draft.target_cell_id),
      )
    : -1;
  const target = index >= 0 ? s.notebook.cells[index] : null;
  const canUpdate =
    !applied &&
    target &&
    (target.digest || target.ai?.digest) === draft.expected_digest &&
    (!s.notebookDirty ||
      cellValue(target) ===
        cellValue(s.notebookBase?.cells.find((c) => c.id === target.id) || {}));
  const busy =
      workspaceJob("chat") ||
      workspaceJob("notebook") ||
      s.applyingCode?.has(draft.id),
    lines = draft.code.split("\n").length;
  let actions;
  if (!sameBook)
    actions = `<a class="btn small" href="${base()}/notebook/${encodeURIComponent(draft.notebook_id)}">Open its notebook ${icon("arrow")}</a>`;
  else if (applied)
    actions = `<button class="btn small" data-action="open-code-cell" data-cell-id="${esc(applied.cell_id)}">${icon("notebook")}${index >= 0 ? `Open cell ${index + 1}` : "Open notebook"}</button>`;
  else
    actions = `${canUpdate ? `<button class="btn primary small" data-action="apply-code" data-id="${draft.id}" data-mode="replace" ${busy ? "disabled" : ""}>Update cell ${index + 1}</button>` : ""}<button class="btn ${canUpdate ? "" : "primary"} small" data-action="apply-code" data-id="${draft.id}" data-mode="append" ${busy ? "disabled" : ""}>${icon("plus")}${canUpdate ? "Add as new cell" : "Add to notebook"}</button>`;
  return `<section class="chat-code-card" data-draft-id="${draft.id}" aria-label="Code suggestion">
<header>
<span class="grow">
<strong>${esc(draft.title)}</strong>
<small>${draft.kind === "markdown" ? "Notes" : "Python"} · ${applied ? "Added to notebook" : draft.checks?.issues?.length ? "Needs attention" : "Ready to add"}</small>
</span>
<button class="icon-btn" data-action="copy-draft" data-id="${draft.id}" aria-label="Copy suggested code">${icon("copy")}</button>
</header>
<details class="chat-code-source" ${applied ? "" : "open"}>
<summary>${lines} ${lines === 1 ? "line" : "lines"} of ${draft.kind === "markdown" ? "Markdown" : "code"}</summary>
<pre>
<code>${esc(draft.code)}</code>
</pre>
</details>${codeChecksMarkup(draft.checks)}${
    canUpdate
      ? `<details class="code-comparison">
<summary>Compare with cell ${index + 1}</summary>
<div>
<span class="tiny muted">Current code</span>
<pre>
<code>${esc(target.source)}</code>
</pre>
<span class="tiny muted">Proposed code</span>
<pre>
<code>${esc(draft.code)}</code>
</pre>
</div>
</details>`
      : ""
  }${!applied && sameBook && draft.target_cell_id && !canUpdate ? '<p class="code-target-note">The original cell has changed. Add this as a new cell to keep your edits.</p>' : ""}<footer>${actions}<span class="code-card-error" role="alert"></span>
</footer>
</section>`;
}
function codeChecksMarkup(checks) {
  if (!checks) return "";
  const issues = checks.issues || [];
  return `<details class="code-checks ${issues.length ? "has-issues" : ""}" ${issues.length ? "open" : ""}>
<summary>${issues.length ? `${issues.length} code ${issues.length === 1 ? "check" : "checks"} to review` : checks.status === "limited" ? "Library checks need notebook setup" : "Code checks"}</summary>${issues.length ? `<ul>${issues.map((i) => `<li>Line ${esc(i.line)}: ${esc(i.message)}</li>`).join("")}</ul>` : "<p>No issues found in the checks available.</p>"}<p class="tiny muted">${esc(checks.scope)}</p>
</details>`;
}
function conversationMessage(message) {
  const drafts = (s.thread.drafts || []).filter(
    (d) => d.message_id === message.seq,
  );
  return `<article class="message ${message.role}">
<div class="message-by">${message.role === "assistant" ? '<span class="assistant-mark">ε</span>Epsilon' : "You"}</div>
<div class="message-body">${messageHTML(message.text)}</div>${fieldChoices(message)}${drafts.map(codeDraftCard).join("")}${messageUsage(message.usage)}</article>`;
}
async function applySuggestedCode(draftId, mode) {
  if (s.applyingCode?.has(draftId)) return;
  s.applyingCode = s.applyingCode || new Set();
  s.applyingCode.add(draftId);
  const projectId = pid(),
    threadId = s.thread.id;
  document
    .querySelectorAll(`[data-action="apply-code"][data-id="${draftId}"]`)
    .forEach((el) => (el.disabled = true));
  try {
    await flushNotebook();
    const result = await post(
      apiProject(projectId) + "/drafts/" + draftId + "/apply",
      { mode },
    );
    if (
      pid() === projectId &&
      s.thread?.id === threadId &&
      s.notebook?.id === result.notebook.id
    ) {
      const thread = await api(apiProject(projectId) + "/threads/" + threadId);
      if (
        pid() === projectId &&
        s.thread?.id === threadId &&
        s.notebook?.id === result.notebook.id
      ) {
        acceptNotebook(result.notebook);
        s.thread = thread;
        s.applyingCode.delete(draftId);
        openCodeCell(result.change.cell_id);
      }
    }
    toast(
      result.change.status === "added_after_edit"
        ? "Your original cell was kept. The new code is in a separate cell."
        : result.change.status === "updated"
          ? "Cell updated. Run it when you're ready."
          : "Code added. Run the cell when you're ready.",
    );
  } catch (error) {
    const card = document.querySelector(
      `[data-draft-id="${draftId}"] .code-card-error`,
    );
    if (card) card.textContent = error.message;
    else showError(error);
  } finally {
    s.applyingCode.delete(draftId);
    document
      .querySelectorAll(`[data-action="apply-code"][data-id="${draftId}"]`)
      .forEach(
        (el) =>
          (el.disabled = Boolean(
            workspaceJob("chat") || workspaceJob("notebook"),
          )),
      );
  }
}
function openCodeCell(cellId) {
  selectWorkspacePanel();
  paintWorkspace(researchWorkspace(), "Workspace");
  const editor = document.querySelector(
    `.cell-editor[data-cell-id="${CSS.escape(cellId || "")}"]`,
  );
  if (editor) {
    editor.closest(".cell-source").open = true;
    editor.closest(".notebook-cell").classList.add("cell-highlight");
    editor.scrollIntoView({
      block: "center",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
    editor.focus({ preventScroll: true });
  }
}
function compactChat() {
  const t = s.thread,
    job = workspaceJob("chat"),
    plans = t?.plans || [],
    latest = plans[0];
  const pending = latest && !t.artifacts.some((a) => a.plan_id === latest.id);
  return `<section class="workspace-chat" aria-label="Assistant">
<header class="pane-heading">
<h2>${icon("chat")}Assistant</h2>
<div class="row">
<button class="link-btn tiny" data-action="history">${icon("history")}History</button>
<button class="icon-btn" data-action="new-chat" aria-label="New conversation">${icon("plus")}</button>
</div>
</header>
<div class="chat-messages" id="chat-messages">${
    t?.messages.length
      ? t.messages
          .map(
            (m) =>
              conversationMessage(m) +
              (m.role === "user" ? requestRecovery(m) : ""),
          )
          .join("")
      : `<div class="chat-welcome">
<span class="assistant-mark">ε</span>
<h3>What would you like to explore?</h3>
<p>Describe what you need. I can help explain the data and write notebook code.</p>${!s.session.ai.configured ? '<a class="btn small" href="/settings">Connect AI to start</a>' : ""}<div class="chat-chips">${promptSuggestions()
          .map(
            (p, i) =>
              `<button class="chat-chip" data-action="prompt-suggestion" data-prompt="${i}">${esc(p.label)} ${icon("arrow")}</button>`,
          )
          .join("")}</div>
</div>`
  }${pending ? planCard(latest) : ""}${
    plans.length > (pending ? 1 : 0)
      ? `<details class="quiet-details earlier-plans">
<summary>${pending ? "Earlier plans" : "Preview plans"}</summary>${plans
          .slice(pending ? 1 : 0)
          .map(planCard)
          .join("")}</details>`
      : ""
  }${(t?.drafts || [])
    .filter((d) => !d.message_id)
    .slice(0, 3)
    .map(codeDraftCard)
    .join("")}${
    t?.artifacts.length
      ? `<a class="notebook-change-link" href="${base()}/analyses/${t.artifacts[0].id}">${icon("chart")}<span>View saved preview<small>Opens in Results</small>
</span>${icon("arrow")}</a>`
      : ""
  }<div id="job-progress">${progressMarkup(job)}</div>
</div>
<button id="latest-message" class="message-jump" data-action="latest-message" hidden>Latest message ${icon("down")}</button>
${workspaceUsage()}<div class="chat-compose">${askBox("chat-ask", true)}</div>
</section>`;
}
function compactNotebook() {
  const n = s.notebook,
    running = workspaceJob("notebook"),
    busy = running || workspaceJob("chat");
  return `<div class="notebook-controls">
<div class="row">
<button class="link-btn notebook-picker" data-action="choose-notebook">${esc(s.thread?.title || n.title || "Research notebook")}${icon("down")}</button>
<span id="save-status" class="tiny muted" role="status">${s.notebookDirty ? "Unsaved edits" : n.temporary ? "Draft · saved when you edit or run" : "All changes saved"}</span>
</div>
<div class="row">
<button class="icon-btn" data-action="save-notebook" aria-label="Save notebook">${icon("check")}</button>
<button class="btn primary small" data-tour="run-all" data-action="run-all" ${!s.runtime.available || busy ? "disabled" : ""}>${icon("play")}Run all</button>
<details class="notebook-menu">
<summary aria-label="Notebook options">${icon("settings")}</summary>
<div>
<button data-action="export-notebook">${icon("download")}Export notebook</button>
<button data-action="prepare-build">${icon("shield")}Prepare for build</button>
<button data-action="notebook-runs">${icon("history")}Run history</button>
<button data-action="stop-kernel">${icon("refresh")}Restart notebook</button>
<button data-action="notebook-info">${icon("info")}About this notebook</button>
</div>
</details>
</div>
</div>${notebookRuntimeNotice(s.runtime)}${exampleNotebookHint(n)}${notebookLibraryNotice()}${notebookWelcome()}<div id="notebook-progress">${progressMarkup(running)}</div>
<div class="notebook-cells">${n.cells.map((cell, i) => notebookCell(cell, i, busy)).join("")}</div>
<div class="add-cells">
<button class="btn small" data-action="add-cell">${icon("plus")}Code cell</button>
<button class="btn small" data-action="add-markdown">${icon("plus")}Notes</button>
<span class="tiny muted">Shift+Enter to run</span>
</div>`;
}
function researchWorkspace() {
  const mode = s.layout || "both";
  const disconnected = Object.values(s.jobs).some(
    (job) => job.project_id === pid() && job.status === "disconnected",
  );
  return `<div class="research-workspace" data-layout="${mode}">
${disconnected ? '<div class="notice connection-notice"><span>Your connection was interrupted. Your edits are still here.</span><button class="btn small" data-action="reconnect">Reconnect</button></div>' : ""}
<header class="workspace-toolbar">
<div class="workspace-title">
<h1>${esc(s.thread?.title || "Research workspace")}</h1>
<button class="icon-btn" data-action="rename-thread" aria-label="Rename conversation">${icon("edit")}</button>
</div>
<div class="view-switch" role="group" aria-label="Workspace layout">${[
    ["assistant", "chat", "Assistant"],
    ["both", "layers", "Both"],
    ["notebook", "notebook", "Notebook"],
  ]
    .map(
      ([
        key,
        ic,
        label,
      ]) => `<button data-action="workspace-layout" data-layout="${key}" aria-pressed="${mode === key}" ${mode === key ? 'class="selected"' : ""}>${icon(ic)}<span>${label}</span>
</button>`,
    )
    .join("")}</div>
</header>
<div class="workspace-split" style="--chat-width:${(s.chatWidth || 0.38) * 100}%">${compactChat()}<div class="pane-divider" role="separator" aria-label="Resize assistant and notebook" aria-orientation="vertical" aria-valuemin="27" aria-valuemax="60" aria-valuenow="${Math.round((s.chatWidth || 0.38) * 100)}" tabindex="0">
</div>
<section class="workspace-notebook" aria-label="Notebook">
<header class="pane-heading">
<h2>${icon("notebook")}Notebook</h2>
<span class="pill soft">Synthetic data</span>
</header>
<div id="notebook-pane" class="notebook-pane">${compactNotebook()}</div>
</section>
</div>
</div>`;
}
async function refreshLiveNotebook() {
  const project = pid(),
    nid = s.notebook?.id;
  if (!nid || !["assistant", "notebook"].includes(parts()[2])) return;
  const remote = await api(
    apiProject() + "/notebooks/" + encodeURIComponent(nid),
  );
  if (pid() !== project || s.notebook?.id !== nid) return;
  acceptNotebook(remote);
  selectWorkspacePanel();
  paintWorkspace(researchWorkspace(), "Workspace");
}
document.addEventListener("pointerdown", (event) => {
  const handle = event.target.closest(".pane-divider");
  if (!handle) return;
  event.preventDefault();
  const split = handle.parentElement;
  handle.setPointerCapture(event.pointerId);
  const move = (e) => {
    const box = split.getBoundingClientRect(),
      fraction = Math.max(
        0.27,
        Math.min(0.6, (e.clientX - box.left) / box.width),
      );
    split.style.setProperty("--chat-width", fraction * 100 + "%");
    handle.setAttribute("aria-valuenow", Math.round(fraction * 100));
    s.chatWidth = fraction;
  };
  const stop = () => {
    try {
      localStorage.setItem("epsilon.workspace.paneWidth", s.chatWidth);
    } catch {}
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", stop);
    handle.removeEventListener("pointercancel", stop);
  };
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", stop);
  handle.addEventListener("pointercancel", stop);
});
document.addEventListener("keydown", (event) => {
  if (
    event.target.matches(".pane-divider") &&
    ["ArrowLeft", "ArrowRight"].includes(event.key)
  ) {
    event.preventDefault();
    s.chatWidth = Math.max(
      0.27,
      Math.min(
        0.6,
        (s.chatWidth || 0.38) + (event.key === "ArrowRight" ? 0.03 : -0.03),
      ),
    );
    event.target.parentElement.style.setProperty(
      "--chat-width",
      s.chatWidth * 100 + "%",
    );
    event.target.setAttribute("aria-valuenow", Math.round(s.chatWidth * 100));
    try {
      localStorage.setItem("epsilon.workspace.paneWidth", s.chatWidth);
    } catch {}
  }
});
document.addEventListener(
  "scroll",
  (event) => {
    const pane = event.target;
    if (
      pane.id === "chat-messages" &&
      pane.scrollHeight - pane.scrollTop - pane.clientHeight < 80
    ) {
      delete pane.dataset.unread;
      const jump = document.getElementById("latest-message");
      if (jump) jump.hidden = true;
    }
  },
  true,
);

export {
  acceptNotebook,
  applySuggestedCode,
  copyValue,
  loadResearchWorkspace,
  newCellId,
  openCodeCell,
  paintWorkspace,
  refreshLiveNotebook,
  researchWorkspace,
  selectWorkspaceLayout,
  selectWorkspacePanel,
  startPlan,
  starters,
  workspaceJob,
};
