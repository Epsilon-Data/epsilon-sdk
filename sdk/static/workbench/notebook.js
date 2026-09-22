import { rememberView, restoreView } from "./interactions.js";
import { esc, fmt, icon, pid, s, showError } from "./core.js";
import { drawChart, executeCell, resultTable } from "./app.js";
import { workspaceJob } from "./workspace.js";

// Shared chart rendering for saved previews and local notebook displays.
function canLine(axis) {
  return ["numeric", "time"].includes(axis?.kind) && axis.points?.length > 0;
}
function chartOptions(value, axis) {
  return [
    ["bar", "Bar chart"],
    ["pie", "Pie chart"],
    ["line", "Line chart"],
  ]
    .map(
      ([key, label]) =>
        `<option value="${key}" ${value === key ? "selected" : ""} ${key === "line" && !canLine(axis) ? "disabled" : ""}>${label}${key === "line" && !canLine(axis) ? " · needs an ordered axis" : ""}</option>`,
    )
    .join("");
}
function lineChart(table, axis) {
  if (!canLine(axis))
    return '<p class="muted">Choose a numeric or time field for a line chart.</p>';
  const points = axis.points,
    labels = table.chart.labels,
    values = table.chart.values;
  const min = points[0].x,
    max = points[points.length - 1].x,
    peak = Math.max(...points.map((p) => values[p.index]));
  const magnitude = 10 ** Math.floor(Math.log10(peak)),
    ceiling = Math.ceil(peak / magnitude) * magnitude;
  const x = (p) => (min === max ? 365 : 64 + ((p.x - min) / (max - min)) * 600),
    y = (p) => 250 - (values[p.index] / ceiling) * 215;
  const path = points
    .map(
      (p, i) =>
        `${i && p.x - points[i - 1].x <= axis.step * (1 + 1e-6) ? "L" : "M"}${x(p).toFixed(2)},${y(p).toFixed(2)}`,
    )
    .join(" ");
  const ticks = points.filter(
    (p, i) =>
      i === 0 ||
      i === points.length - 1 ||
      i % Math.max(1, Math.ceil(points.length / 6)) === 0,
  );
  return `<div class="chart-kicker">
<span>SYNTHETIC RECORDS</span>
<span>${esc(table.name)}</span>
</div>
<svg class="line-chart" viewBox="0 0 710 335" role="img" aria-label="${esc(points.map((p) => labels[p.index] + ": " + fmt(values[p.index]) + " records").join(", "))}">
    ${[0, 0.25, 0.5, 0.75, 1]
      .map(
        (
          t,
        ) => `<line x1="64" x2="664" y1="${250 - t * 215}" y2="${250 - t * 215}" stroke="#E6E6E6"/>
<text x="54" y="${254 - t * 215}" text-anchor="end">${fmt(Math.round(t * ceiling))}</text>`,
      )
      .join("")}
    <path class="series-line" d="${path}" fill="none" stroke="#1481F1" stroke-width="2.5"/>
    ${points
      .map(
        (p) => `<circle cx="${x(p)}" cy="${y(p)}" r="4" fill="#1481F1">
<title>${esc(labels[p.index])}: ${fmt(values[p.index])} records</title>
</circle>`,
      )
      .join("")}
    ${ticks.map((p) => `<text transform="translate(${x(p)},270) rotate(-25)" text-anchor="end">${esc(labels[p.index])}</text>`).join("")}</svg>
    <p class="tiny muted">Ordered ${axis.kind === "time" ? "time periods" : "numeric bands"}. Lines break across absent or withheld intervals; missing and invalid values remain in the table.</p>`;
}

const notebookViews = new Map();
function lineNumberText(source) {
  const count = Math.max(1, String(source || "").split("\n").length);
  return Array.from({ length: count }, (_, index) => String(index + 1)).join(
    "\n",
  );
}
function syncEditorLineNumbers(editor) {
  if (!editor) return;
  const gutter = editor.parentElement?.querySelector(".cell-line-numbers");
  if (!gutter) return;
  gutter.textContent = lineNumberText(editor.value);
  gutter.scrollTop = editor.scrollTop;
}
document.addEventListener("input", (event) => {
  if (event.target.matches?.(".cell-editor"))
    syncEditorLineNumbers(event.target);
});
document.addEventListener(
  "scroll",
  (event) => {
    if (event.target.matches?.(".cell-editor"))
      syncEditorLineNumbers(event.target);
  },
  true,
);
function notebookViewState(cell, block) {
  const key = pid() + "/" + s.notebook.id + "/" + cell + "/" + block;
  if (!notebookViews.has(key))
    notebookViews.set(key, { table: 0, tab: "chart", chart: "bar" });
  return notebookViews.get(key);
}
function jsonTree(value) {
  let remaining = 1500;
  function node(value, key, depth) {
    if (--remaining < 0) return "";
    const prefix =
      key === null ? "" : `<span class="json-key">${esc(key)}</span>: `;
    if (value === null || typeof value !== "object")
      return `<div class="json-leaf">${prefix}<span class="json-${typeof value}">${esc(JSON.stringify(value))}</span>
</div>`;
    const entries = Object.entries(value),
      label = Array.isArray(value)
        ? `Array (${entries.length})`
        : `Object (${entries.length})`;
    return `<details class="json-node" ${depth < 1 ? "open" : ""}>
<summary>${prefix}${label}</summary>${
      depth < 8
        ? entries
            .slice(0, 100)
            .map(([k, v]) => node(v, k, depth + 1))
            .join("")
        : ""
    }${entries.length > 100 || depth >= 8 ? '<p class="muted">More values are available in the full JSON below.</p>' : ""}</details>`;
  }
  return `<div class="json-tree">${node(value, null, 0)}</div>
<details class="raw-json">
<summary>Full JSON</summary>
<pre>${esc(JSON.stringify(value, null, 2))}</pre>
</details>`;
}
function notebookPreview(block, cell, index) {
  const view = notebookViewState(cell, index),
    tables = block.result.tables;
  view.table = Math.min(view.table, tables.length - 1);
  const table = tables[view.table],
    axis = block.axes?.[view.table];
  if (view.chart === "line" && !canLine(axis)) view.chart = "bar";
  const scope = `data-cell="${cell}" data-block="${index}"`;
  return `<div class="notebook-preview" ${scope}>
<div class="notebook-display-toolbar">
<select class="notebook-selector" data-notebook-control="table" ${scope} aria-label="Notebook result field">${tables.map((t, i) => `<option value="${i}" ${i === view.table ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select>
<div class="row">
<select class="notebook-selector" data-notebook-control="tab" ${scope} aria-label="Notebook output view">${["chart", "table", "json"].map((tab) => `<option value="${tab}" ${tab === view.tab ? "selected" : ""}>${tab === "json" ? "JSON" : tab[0].toUpperCase() + tab.slice(1)}</option>`).join("")}</select>${view.tab === "chart" ? `<select class="notebook-selector" data-notebook-control="chart" ${scope} aria-label="Notebook chart type">${chartOptions(view.chart, axis)}</select>` : ""}</div>
</div>
    ${view.tab === "chart" ? drawChart(table, view.chart, axis) : view.tab === "table" ? resultTable(table) : jsonTree(block.result)}
    <p class="tiny muted notebook-preview-note">${table.withheld_groups ? `${fmt(table.withheld_groups)} groups withheld; hidden values are excluded.` : "Synthetic record counts."} Notebook output remains unreviewed.</p>
</div>`;
}
function notebookOutput(output, cell) {
  const blocks = output.display?.blocks || [
    { kind: "text", text: output.text || "" },
  ];
  return `<div class="cell-output" data-output-cell="${cell}">
<div class="output-heading">
<span>Out [${esc(output.execution_count ?? " ")}]</span>
<span class="pill ${output.stale ? "amber" : "soft"}">${output.stale ? "Needs rerun" : "Local output"}</span>
</div>${output.stale ? `<p class="stale-output-note">${esc(output.stale_reason || "Code changed. Rerun this cell to refresh its output.")}</p>` : ""}${blocks
    .map((b, i) => {
      if (b.kind === "preview") return notebookPreview(b, cell, i);
      if (b.kind === "html") return `<div class="rich-output">${b.html}</div>`; // Server rebuilds inert, URL-free HTML.
      if (b.kind === "image")
        return `<figure class="notebook-figure">
<img alt="Notebook figure, unreviewed" src="data:image/png;base64,${b.data}">
</figure>`;
      if (b.kind === "json") return jsonTree(b.value);
      return `<pre class="notebook-stream ${b.kind === "error" || b.name === "stderr" ? "notebook-error" : ""}">${esc(b.text)}</pre>`;
    })
    .join(
      "",
    )}${!blocks.length ? '<p class="tiny muted">Completed without displayed output.</p>' : ""}${output.error && !blocks.some((b) => b.kind === "error") ? '<p class="notebook-error">Execution failed. Inspect the output or restart the kernel before continuing.</p>' : ""}${output.truncated ? '<p class="notice">Output reached the display limit. Show fewer rows or a smaller figure.</p>' : ""}${blocks.some((b) => b.kind === "error" && b.text?.includes("ModuleNotFoundError")) ? '<div class="notice library-error"><span><strong>A Python library is missing</strong><p>The notebook has its own libraries. <a class="link-btn tiny" href="/settings">Check notebook libraries in Settings</a></p></span></div>' : ""}${
    output.error && !output.stale
      ? `<div class="cell-repair">
<button class="btn small" data-action="fix-cell" data-cell-id="${esc(s.notebook.cells[cell]?.id || "")}" ${!s.session.ai.configured || workspaceJob("chat") || workspaceJob("notebook") ? "disabled" : ""}>${icon("spark")}Fix with AI</button>
<span class="tiny muted">Review what is shared first.</span>
</div>`
      : ""
  }<details class="run-details">
<summary>Run details</summary>
<p>Runtime ${esc(output.image_id?.slice(0, 19) || "not recorded")} · input ${esc(output.input_digest?.slice(0, 10) || "not recorded")}</p>
</details>
</div>`;
}
function notebookCell(cell, i, running) {
  const md = cell.kind === "markdown",
    language = md ? "Markdown" : "Python",
    lines = cell.source.split("\n").length,
    placeholder = md
      ? "Write notes here, or ask the assistant to add a note…"
      : "Write Python code here, or ask the assistant to add code…";
  return `<section class="notebook-cell">
<div class="cell-heading">
<span class="cell-index">${md ? icon("file") : `[${esc(cell.output?.execution_count ?? " ")}]`}</span>
<span class="grow">${md ? "Markdown" : "Python"} · ${esc(cell.ai?.title || "cell " + (i + 1))}</span>${
    cell.ai
      ? `<span class="pill soft">AI</span>${
          cell.ai.can_undo
            ? `<button class="cell-undo link-btn tiny" data-action="undo-cell" data-change="${esc(cell.ai.change_id)}" ${running ? "disabled" : ""} aria-label="Undo AI change to cell ${i + 1}">${icon("history")}<span>Undo</span>
</button>`
            : ""
        }`
      : ""
  }<button class="link-btn tiny cell-context-button" data-action="use-cell-context" data-cell-id="${esc(cell.id)}" aria-label="Use cell ${i + 1} with AI" ${running || !s.session.ai.configured ? "disabled" : ""}>${icon("chat")}Use with AI</button><button class="cell-run btn small" data-action="run-cell" data-cell="${i}" aria-label="${md ? "Render" : "Run"} cell ${i + 1}" ${(!md && !s.runtime.available) || running ? "disabled" : ""}>${icon("play")}<span>${md ? "Show" : "Run"}</span>
</button>
</div>${md ? `<div class="rich-output markdown-cell" data-markdown-cell="${i}">${cell.html || ""}</div>` : ""}<details class="cell-source" ${md ? (cell.html ? "" : "open") : lines > 35 && cell.output ? "" : "open"}>
<summary>${md ? "Edit Markdown" : `Code · ${lines} ${lines === 1 ? "line" : "lines"}`}</summary>
<label class="hidden" for="cell-${i}">${md ? "Markdown" : "Python"} source, cell ${i + 1}</label>
<div class="cell-editor-frame" data-editor-language="${language.toLowerCase()}">
<div class="cell-editor-toolbar"><span class="cell-editor-language"><span class="cell-editor-dot" aria-hidden="true"></span>${language}</span><span class="cell-editor-hint">Editable source</span></div>
<div class="cell-editor-body"><pre class="cell-line-numbers" aria-hidden="true">${lineNumberText(cell.source)}</pre>
<textarea class="cell-editor" id="cell-${i}" data-cell="${i}" data-cell-id="${esc(cell.id || i)}" spellcheck="false" autocomplete="off" autocapitalize="off" placeholder="${esc(placeholder)}" style="min-height:${Math.min(450, Math.max(120, lines * 20 + 40))}px">${esc(cell.source)}</textarea>
</div>
</div>
</details>${cell.output ? notebookOutput(cell.output, i) : ""}</section>`;
}
function refreshNotebookOutput(cell) {
  const old = document.querySelector(`[data-output-cell="${cell}"]`);
  if (old && s.notebook.cells[cell].output) {
    const previous = rememberView();
    old.outerHTML = notebookOutput(s.notebook.cells[cell].output, cell);
    restoreView(previous);
  }
}
document.addEventListener("change", (event) => {
  const el = event.target;
  if (!el.dataset.notebookControl) return;
  const cell = Number(el.dataset.cell),
    block = Number(el.dataset.block);
  const state = notebookViewState(cell, block);
  state[el.dataset.notebookControl] =
    el.dataset.notebookControl === "table" ? Number(el.value) : el.value;
  refreshNotebookOutput(cell);
  document
    .querySelector(
      `[data-notebook-control="${el.dataset.notebookControl}"][data-cell="${cell}"][data-block="${block}"]`,
    )
    ?.focus({ preventScroll: true });
});
document.addEventListener("keydown", (event) => {
  if (
    event.target.matches(".cell-editor") &&
    event.key === "Enter" &&
    (event.shiftKey || event.ctrlKey || event.metaKey)
  ) {
    event.preventDefault();
    executeCell(Number(event.target.dataset.cell)).catch(showError);
  }
});

function markLaterOutputsStale(index) {
  if (s.notebook.cells[index]?.kind === "markdown") return;
  s.notebook.cells.slice(index + 1).forEach((cell, offset) => {
    if (cell.output && !cell.output.stale) {
      cell.output.stale = true;
      cell.output.stale_reason =
        "Code earlier in this notebook changed. Rerun from that cell to refresh these outputs.";
      const output = document.querySelector(
        `[data-output-cell="${index + offset + 1}"]`,
      );
      const badge = output?.querySelector(".output-heading .pill");
      if (badge) {
        badge.textContent = "Needs rerun";
        badge.className = "pill amber";
      }
      if (output && !output.querySelector(".stale-output-note")) {
        const note = document.createElement("p");
        note.className = "stale-output-note";
        note.textContent = cell.output.stale_reason;
        output.querySelector(".output-heading")?.after(note);
      }
      output?.querySelector(".cell-repair")?.remove();
    }
  });
}

export {
  canLine,
  chartOptions,
  lineChart,
  markLaterOutputsStale,
  notebookCell,
  notebookOutput,
};
