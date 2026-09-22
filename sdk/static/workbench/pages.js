import { usageTotals } from "./usage.js";
import { base, esc, fmt, icon, parts, pid, s } from "./core.js";
import {
  artifactRow,
  askBox,
  drawChart,
  heading,
  progressMarkup,
  resultTable,
} from "./app.js";
import { canLine, chartOptions } from "./notebook.js";
import { starters } from "./workspace.js";
import { datasetChoicesMarkup, datasetName } from "./datasets.js";
import { examplesSection } from "./examples.js";

const fieldTypes = {
  integer: "Whole number",
  number: "Number",
  categorical: "Category",
  boolean: "Yes / no",
  date: "Date",
  timestamp: "Date and time",
  string: "Text",
};
function fieldLabel(path) {
  const name = String(path).split(".").at(-1).replaceAll("_", " ");
  return name.charAt(0).toUpperCase() + name.slice(1);
}
function readableDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Saved locally";
  const today = new Date(),
    yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const day =
    date.toDateString() === today.toDateString()
      ? "Today"
      : date.toDateString() === yesterday.toDateString()
        ? "Yesterday"
        : date.toLocaleDateString(undefined, {
            day: "numeric",
            month: "short",
            ...(date.getFullYear() !== today.getFullYear()
              ? { year: "numeric" }
              : {}),
          });
  return (
    day +
    ", " +
    date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
  );
}
function workHref(item, projectId = pid()) {
  if (item.notebook_id)
    return (
      base(projectId) + "/notebook/" + encodeURIComponent(item.notebook_id)
    );
  if (item.thread_id)
    return (
      base(projectId) +
      "/assistant/" +
      encodeURIComponent(item.thread_id) +
      (item.artifact_id
        ? "?artifact=" + encodeURIComponent(item.artifact_id)
        : "")
    );
  return base(projectId) + "/analyses";
}
function workspaceHref(projectId = pid()) {
  if (projectId === pid() && ["assistant", "notebook"].includes(parts()[2]))
    return location.pathname + location.search;
  return s.workProject === projectId && s.recentWork?.length
    ? workHref(s.recentWork[0], projectId)
    : base(projectId) + "/assistant";
}
function workRow(item, manage = false) {
  const kind = {
    notebook: "Notebook",
    conversation: "Conversation",
    result: "Saved result",
  }[item.kind];
  return `<div class="work-row">
<a class="recent-row" href="${workHref(item)}">
<span class="recent-icon">${icon(item.kind === "notebook" ? "notebook" : item.kind === "result" ? "chart" : "chat")}</span>
<span class="grow">
<h3>${esc(item.title)}</h3>
<p>${kind} · ${esc(readableDate(item.updated))}${item.result_count && item.kind !== "result" ? ` · ${item.result_count} saved ${item.result_count === 1 ? "result" : "results"}` : ""}</p>
</span>${icon("chevron")}</a>${manage ? `<button class="link-btn tiny" data-action="archive-work" data-id="${esc(item.thread_id || item.notebook_id)}" data-kind="${item.thread_id ? "threads" : "notebooks"}" data-archived="${!item.archived}">${item.archived ? "Restore" : "Archive"}</button>` : ""}</div>`;
}
function projectCards(projectsList) {
  return projectsList
    .map(
      (
        p,
      ) => `<a class="project-card ${p.ready ? "" : "setup-project"}" href="${base(p.id)}">
<div class="row between">
<span class="project-icon">${icon("folder", "lg")}</span>
<span class="pill ${p.ready ? "green" : "amber"}">${p.ready ? "Ready" : "Finish setup"}</span>
</div>
<h2>${esc(p.name)}</h2>
<p>${esc(p.description || "Your data, conversations and notebooks in one place.")}</p>
<footer>
<span>${p.ready ? "Open project" : "Choose a dataset"}</span>${icon("arrow")}</footer>
</a>`,
    )
    .join("");
}
function projectsPage() {
  const visible = s.projects.filter((p) =>
      (p.name + " " + p.description)
        .toLowerCase()
        .includes(s.search.toLowerCase()),
    ),
    ready = visible.filter((p) => p.ready),
    pending = visible.filter((p) => !p.ready);
  const empty = !visible.length
    ? `<div class="empty-state">
<h3>No matching projects</h3>
<p>Try another name.</p>
<button class="btn" data-action="clear-project-search">Clear search</button>
</div>`
    : "";
  return `<div class="page simple-projects">${heading("Your datasets", "Choose an approved dataset to create a project on this computer.")}<section id="approved-datasets" class="approved-datasets" aria-label="Approved datasets">${datasetChoicesMarkup()}</section>${
    s.projects.length
      ? `<section class="continue-projects" aria-label="Local projects"><div class="projects-toolbar">
<div><h2>${s.search ? "Search results" : "Continue work"}<span class="section-count">${visible.length}</span>
</h2><p class="tiny muted">Local projects on this computer</p></div>
<div class="search-wrap">${icon("search")}<input id="project-search" class="search" aria-label="Search local projects" placeholder="Search local projects" value="${esc(s.search)}">
</div>` +
        `</div>${empty}${ready.length ? `<div class="project-list">${projectCards(ready)}</div>` : ""}${pending.length ? `${ready.length ? '<div class="section-head setup-section"><h2>Finish setting up</h2></div>' : ""}<div class="project-list">${projectCards(pending)}</div>` : ""}</section>`
      : ""
  }</div>`;
}
function overviewPage() {
  const p = s.project,
    d = p.dataset,
    work = s.recentWork || [];
  return `<div class="page simple-overview">${heading(
    p.name,
    p.description || "",
    `<div class="row">${work.length ? `<a class="btn primary" href="${workHref(work[0])}">Continue work ${icon("arrow")}</a>` : ""}<button class="icon-btn" data-action="project-details" aria-label="Project details">${icon("settings")}</button>
</div>`,
  )}<a class="dataset-summary" href="${base()}/dataset">
<span class="project-icon">${icon("database")}</span>
<span>
<strong>${esc(d.title)}</strong>
<small>Synthetic data · ${fmt(d.rows)} records · ${d.fields.length} fields</small>
</span>${icon("chevron")}</a>
${p.usage?.requests ? `<p class="usage-bar overview-usage">${icon("chart")}${usageTotals("AI usage in this project", p.usage)}<a class="link-btn tiny" href="/settings">All usage</a></p>` : ""}
${!work.length ? examplesSection(s.examples || []) : ""}
<section class="home-question">
<h2>${work.length ? "What would you like to explore?" : "Or ask your own question"}</h2>${askBox("overview-ask")}</section>
${work.length ? examplesSection(s.examples || []) : ""}
<section class="recent-section">
<div class="section-head">
<h2>${work.length ? "Pick up where you left off" : "Your workspace"}</h2>${work.length ? '<button class="link-btn" data-action="history">View all work</button>' : ""}</div>${
    work.length
      ? work
          .slice(0, 3)
          .map((item) => workRow(item))
          .join("")
      : `<div class="first-work">
<span class="project-icon">${icon("notebook")}</span>
<span class="grow">
<strong>Your first analysis</strong>
<p>Start with a worked example, run it locally, then ask the assistant to help you adapt it.</p>
<span class="row first-work-actions"><button class="btn primary small" data-action="start-tutorial">Run your first analysis ${icon("arrow")}</button>
</span>
</span>
<a class="btn" href="${base()}/assistant">Open workspace ${icon("arrow")}</a>
</div>`
  }</section>
</div>`;
}
function setupPage(datasets = []) {
  const p = s.project,
    job = Object.values(s.jobs).find(
      (j) =>
        j.project_id === p.id &&
        j.kind === "initialise" &&
        ["queued", "running"].includes(j.status),
    );
  return `<div class="page">
<div class="setup-layout">${heading("Choose your dataset", "We'll download the synthetic data and its field definitions.", "", p.name)}<div class="card card-pad">${
    !s.session.account.authenticated
      ? `<p>Sign in to see the datasets available to you.</p>
<button class="btn primary setup-signin" data-action="signin">Sign in ${icon("arrow")}</button>`
      : `<form id="setup-form" class="stack">
<label class="field">Dataset<select name="dataset_id" required ${job ? "disabled" : ""}>
<option value="">Select a dataset…</option>${datasets.map((d) => `<option value="${esc(d.id)}" ${d.id === p.dataset_id ? "selected" : ""}>${esc(datasetName(d))}</option>`).join("")}</select>
</label>${datasets.length ? "" : '<div class="notice info">No datasets are available for this account. Ask your project coordinator for access.</div>'}<details class="quiet-details">
<summary>Project options</summary>
<label class="row tiny">
<input type="checkbox" name="dummy_data" ${job ? "disabled" : ""}>Use randomly generated data instead</label>
<p class="tiny muted">Project folder</p>
<code class="project-path">${esc(p.path)}</code>
<p class="tiny muted">Existing project files are kept. Data and field definitions are checked before setup completes.</p>
</details>
<p class="form-error" role="alert">
</p>
<button class="btn primary wide" type="submit" ${job || !datasets.length ? "disabled" : ""}>${icon("download")}${job ? "Preparing project…" : "Prepare project"}</button>
</form>`
  }</div>
<div id="job-progress" class="setup-progress">${progressMarkup(job)}</div>
</div>
</div>`;
}
function fieldRows() {
  const fields = s.project.dataset.fields,
    query = (s.fieldSearch || "").trim().toLowerCase();
  const visible = fields.filter((f) =>
    [f.path, f.type, fieldTypes[f.type] || "", fieldLabel(f.path)]
      .join(" ")
      .toLowerCase()
      .includes(query),
  );
  return {
    count: visible.length,
    rows:
      visible
        .map(
          (f) => `<tr>
<td>
<strong>${esc(fieldLabel(f.path))}</strong>
<small>${esc(f.path.split(".").slice(0, -1).join(" · ").replaceAll("_", " "))}</small>
</td>
<td>
<span class="field-type">${esc(fieldTypes[f.type] || f.type)}</span>
</td>
<td>
<div class="field-code">
<code>${esc(f.path)}</code>
<button class="icon-btn" data-action="copy-field" data-field="${esc(f.path)}" aria-label="Copy ${esc(f.path)}">${icon("copy")}</button>
</div>
</td>
</tr>`,
        )
        .join("") ||
      '<tr><td colspan="3"><div class="field-empty">No fields match your search. <button class="link-btn" data-action="clear-field-search">Clear search</button></div></td></tr>',
  };
}
function capabilityCard(c) {
  return `<section class="capability-item">
<h3>${esc(starters[c.key]?.[0] || c.title)}</h3>
<p>${esc(starters[c.key]?.[1] || c.summary)}</p>${c.runnable ? `<button class="link-btn" data-action="capability-plan" data-key="${esc(c.key)}">Start preview ${icon("arrow")}</button>` : `<span class="pill soft">${c.status === "BLOCKED" ? "Needs more data structure" : "Not supported yet"}</span>${c.blockers.map((b) => `<p>${esc(b)}</p>`).join("")}`}</section>`;
}
function datasetPage() {
  const d = s.project.dataset,
    fields = fieldRows(),
    unavailable = s.project.capabilities.filter((c) => !c.runnable);
  return `<div class="page data-page">${heading("Data", d.title, '<span class="pill soft">Synthetic data</span>')}<div class="data-at-a-glance">
<span>
<strong>${fmt(d.rows)}</strong> records</span>
<span>
<strong>${d.fields.length}</strong> fields</span>
<p>A synthetic dataset for developing your analysis.</p>
</div>
<section class="card field-browser">
<header class="field-toolbar">
<div>
<h2>Explore the fields</h2>
<p id="field-count" class="tiny muted" role="status">${fields.count} fields</p>
</div>
<div class="search-wrap">${icon("search")}<input id="field-search" class="search" type="search" aria-label="Search data fields" placeholder="Search name or type" value="${esc(s.fieldSearch || "")}">
</div>
</header>
<div class="table-scroll">
<table class="data-table field-table">
<thead>
<tr>
<th>Field</th>
<th>Type</th>
<th>Name in code</th>
</tr>
</thead>
<tbody id="field-rows">${fields.rows}</tbody>
</table>
</div>
</section>${
    unavailable.length
      ? `<details class="quiet-details unavailable-methods">
<summary>Why some analyses aren't available (${unavailable.length})</summary>
<div class="capability-grid">${unavailable.map(capabilityCard).join("")}</div>
</details>`
      : ""
  }<details class="quiet-details data-rules">
<summary>Data rules and version details</summary>
<div class="detail-list">
<div>
<span>Each row represents</span>
<strong>${esc(d.unit)}</strong>
</div>
<div>
<span>Person or entity identifier</span>
<strong>${d.has_entity_key ? "Available" : "Not available"}</strong>
</div>
<div>
<span>Minimum group size for previews</span>
<strong>${d.min_cell}</strong>
</div>
<div>
<span>Data version</span>
<strong>${esc(d.version ?? "Not reported")}</strong>
</div>
<div>
<span>Archetype</span>
<code>${esc(d.archetype || "Not declared")}</code>
</div>
<div>
<span>Schema fingerprint</span>
<code>${esc(d.schema_hash || "Not pinned")}</code>
</div>
</div>
<p class="tiny muted">The archetype defines the fields and their allowed uses. These rules are checked again before each preview.</p>
<div class="table-scroll">
<table class="data-table">
<thead>
<tr>
<th>Field</th>
<th>Access</th>
<th>Allowed output</th>
</tr>
</thead>
<tbody>${d.fields
    .map(
      (f) => `<tr>
<td>
<code>${esc(f.path)}</code>
</td>
<td>${esc(f.access)}</td>
<td>${esc(f.releasable_as.join(", ") || "Checked aggregates")}</td>
</tr>`,
    )
    .join("")}</tbody>
</table>
</div>
</details>
</div>`;
}
function analysesPage() {
  const id = parts()[3];
  if (id) {
    const artifact = s.artifacts.find((a) => a.id === id);
    if (!artifact)
      throw new Error("This saved preview was not found in this project.");
    return `<div class="page result-page">
<div class="result-navigation">
<a class="link-btn" href="${base()}/analyses">All results</a>
<a class="btn small" href="${base()}/assistant/${artifact.thread_id}">${icon("notebook")}Back to workspace</a>
</div>
<p class="tiny muted">Saved preview · notebook edits and runs do not change this snapshot.</p>${artifactMarkup(artifact)}</div>`;
  }
  return `<div class="page">${heading("Saved results", "Charts and tables from your preview runs.", '<button class="btn primary" data-action="preview-options">New preview</button>')}<div class="stack">${
    s.artifacts.map(artifactRow).join("") ||
    `<div class="empty-state">${icon("chart", "lg")}<h3>Your results will appear here</h3>
<p>Save a fixed chart and table with the controlled preview methods.</p>
<button class="btn primary" data-action="preview-options">Choose a preview ${icon("arrow")}</button>
<a class="link-btn empty-secondary" href="${workspaceHref()}">Continue in your notebook</a>
</div>`
  }</div>
</div>`;
}
function artifactMarkup(a) {
  const tables = a.result.tables,
    table = tables[Math.min(s.table, tables.length - 1)];
  if (!table)
    return '<div class="result-empty">This preview returned no displayable fields.</div>';
  const axis = a.axes?.[Math.min(s.table, tables.length - 1)];
  if (s.chart === "line" && !canLine(axis)) s.chart = "bar";
  if (!["chart", "table", "code"].includes(s.tab)) s.tab = "chart";
  const content =
    s.tab === "chart"
      ? drawChart(table, s.chart, axis)
      : s.tab === "table"
        ? resultTable(table)
        : `<div class="code-wrap">
<div class="code-toolbar">
<span>analysis.py</span>
<button class="icon-btn" data-action="download-code" data-id="${a.id}" aria-label="Download analysis code">${icon("download")}</button>
</div>
<pre class="code">
<code>${esc(a.code)}</code>
</pre>
</div>`;
  return `<div class="artifact-card">
<header class="artifact-header">
<div>
<span class="pill soft">Synthetic preview</span>
<h2>${esc(a.title)}</h2>
<p>${esc(readableDate(a.created))}</p>
</div>
<button class="icon-btn" data-action="provenance" data-id="${a.id}" aria-label="How this result was made">${icon("info")}</button>
</header>
<div class="tabs" role="tablist" aria-label="Analysis views">${[
    ["chart", "chart", "Chart"],
    ["table", "table", "Table"],
    ["code", "code", "Code"],
  ]
    .map(
      ([key, ic, label]) =>
        `<button class="tab ${s.tab === key ? "active" : ""}" role="tab" aria-selected="${s.tab === key}" tabindex="${s.tab === key ? 0 : -1}" id="tab-${key}" aria-controls="result-panel" data-action="tab" data-tab="${key}">${icon(ic)}${label}</button>`,
    )
    .join("")}</div>
<div class="artifact-body" id="result-panel" role="tabpanel" aria-labelledby="tab-${s.tab}">${s.tab !== "code" ? `<div class="result-controls">${tables.length > 1 ? `<select id="result-table" class="notebook-selector" aria-label="Choose result field">${tables.map((t, i) => `<option value="${i}" ${i === s.table ? "selected" : ""}>${esc(fieldLabel(t.name))}</option>`).join("")}</select>` : '<span class="tiny muted">Record counts</span>'}${s.tab === "chart" ? `<select id="chart-type" class="notebook-selector" aria-label="Chart type">${chartOptions(s.chart, axis)}</select>` : ""}</div>` : ""}${content}<div class="artifact-note">${icon("shield")}<span>${table.withheld_groups ? `${table.withheld_groups} groups not shown. ` : ""}Minimum group size: ${a.result.min_cell} records.</span>
</div>
<details class="quiet-details preview-details">
<summary>About this preview</summary>
<p>${esc(a.result.notes[0])}</p>
<p>Hidden groups are excluded from the chart and table. Extra groups may be withheld to protect small counts. Record counts are not patient denominators.</p>
<p>This local policy does not assess inference across repeated queries or replace TRE output approval.</p>
</details>
</div>
<footer class="artifact-footer">
<span class="row">${icon("check")}Saved locally with its code</span>
<span class="tiny muted">For method development</span>
</footer>
</div>
<div class="canvas-actions">
<a class="btn primary small" href="${base()}/assistant/${encodeURIComponent(a.thread_id)}">${icon("notebook")}Continue in workspace</a>
<button class="btn small" data-action="export-result" data-id="${a.id}">${icon("download")}Download result</button>
<button class="btn small" data-action="review" data-id="${a.id}">Export analysis</button>
</div>`;
}
function notebookWelcome() {
  if (s.notebook.revision || s.notebook.temporary || s.thread?.messages.length)
    return "";
  return `<div class="notebook-welcome">
<h3>Your notebook starts here</h3>
<p>Each cell below is an editable Python editor. Start with an example, type code, or ask the assistant to write a cell.</p>
<ol class="workflow-steps">
<li>
<span>1</span>Ask</li>
<li>
<span>2</span>Review &amp; add</li>
<li>
<span>3</span>Run the cell</li>
</ol>
</div>`;
}
function notebookLibraryNotice() {
  if (s.runtime.update_available)
    return `<div class="notice notebook-setup-note">${icon("info")}<span>
<strong>New notebook libraries are ready</strong>
<p>Restart this notebook to use them. Saved code stays; variables reset.</p>
<button class="link-btn tiny" data-action="stop-kernel">Restart notebook ${icon("refresh")}</button>
</span>
</div>`;
  if (s.runtime.needs_rebuild)
    return `<div class="notice notebook-setup-note">${icon("info")}<span>
<strong>A library update is available</strong>
<p>${esc((s.runtime.missing_packages || []).join(", "))}</p>
<a class="link-btn tiny" href="/settings">Update notebook libraries ${icon("arrow")}</a>
</span>
</div>`;
  return "";
}
function notebookRuntimeNotice(runtime = {}) {
  if (runtime.available) return "";
  const reason = String(runtime.reason || "");
  let title = runtime.checking
    ? "Checking notebook setup…"
    : "Notebook cells are not ready";
  let detail =
    "You can still write and save code. Run the setup check when you are ready.";
  if (reason.includes("not installed")) {
    title = "Docker is not installed";
    detail =
      "Install Docker Desktop to run cells in Epsilon’s isolated notebook. Chat and code editing remain available.";
  } else if (reason.includes("Start Docker") || reason.includes("daemon")) {
    title = "Start Docker to run cells";
    detail =
      "Start Docker, then run epsilon notebook-build once. Your saved code stays in the project.";
  } else if (reason.includes("remote") || reason.includes("TCP")) {
    title = "Use a local Docker runtime";
    detail =
      "Epsilon only accepts a local Docker daemon for notebook execution. Check Docker Desktop and retry.";
  }
  return `<div class="notice notebook-setup-note">${icon("info")}<span>
<strong>${esc(title)}</strong>
<p>${esc(detail)}</p>
<a class="link-btn tiny" href="/settings">Open notebook setup ${icon("arrow")}</a>
</span>
</div>`;
}
function runtimeLibrariesMarkup() {
  const r = s.runtime,
    installed = new Map((r.packages || []).map((p) => [p.name, p])),
    profile = r.library_profile || [];
  const packages = [
    ...profile,
    ...(r.packages || []).filter(
      (p) => !profile.some((item) => item.name === p.name),
    ),
  ];
  return `<details class="quiet-details notebook-libraries">
<summary>Python libraries</summary>
<p class="tiny muted">${r.inventory_verified ? `Python ${esc(r.python)} · checked in the notebook image` : esc(r.inventory_reason || "Installed versions are available after notebook setup.")}</p>${r.needs_rebuild ? '<p class="notice">Rebuild the notebook image to add the missing libraries below.</p>' : ""}<div class="library-list">${packages
    .map(
      (p) => `<div>
<span>
<strong>${esc(p.name)}</strong>
<small>${esc(p.purpose || "")}</small>
</span>
<code>${esc(installed.get(p.name)?.version || (r.inventory_verified ? "Not installed" : "After setup"))}</code>
</div>`,
    )
    .join("")}</div>
<p class="tiny muted">These libraries belong to the notebook, separately from your SDK environment. To add an approved package, put its name in a separate requirements file and run <code>epsilon notebook-build --requirements &lt;file&gt;</code>. Notebook cells and the assistant cannot download packages.</p>
</details>`;
}
function promptSuggestions() {
  const field =
    s.project.dataset.fields.find((f) =>
      ["integer", "number"].includes(f.type),
    ) || s.project.dataset.fields.find((f) => f.type === "categorical");
  return [
    {
      label: "Summarise the data",
      question:
        "Write notebook code to summarise the fields in this synthetic dataset.",
    },
    {
      label: "Make a chart",
      question: field
        ? `Write a notebook cell to chart ${field.path}. Choose a suitable chart and explain how to run it.`
        : "Help me choose a suitable chart for this dataset and write the code in my notebook.",
    },
    {
      label: "Understand the fields",
      question:
        "Explain the available fields and what research questions this dataset can support, in plain language.",
    },
  ];
}

export {
  analysesPage,
  artifactMarkup,
  datasetPage,
  fieldRows,
  notebookLibraryNotice,
  notebookRuntimeNotice,
  notebookWelcome,
  overviewPage,
  projectsPage,
  promptSuggestions,
  readableDate,
  runtimeLibrariesMarkup,
  setupPage,
  workRow,
  workspaceHref,
};
