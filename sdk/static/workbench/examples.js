import {
  apiProject,
  base,
  esc,
  fmt,
  icon,
  pid,
  post,
  s,
  toast,
} from "./core.js";
import { drawChart, go, heading } from "./app.js";

const chartNames = {
  bar: "Bar chart",
  line: "Line chart",
  pie: "Pie chart",
  heatmap: "Heatmap",
};
const copyRequests = new Map();
const pendingCopies = new Set();

function exampleCards(items) {
  if (!items.length)
    return `<div class="example-empty"><h3>No matching examples yet</h3><p>You can still explore the fields or ask the assistant to help plan your analysis.</p><a class="btn" href="${base()}/dataset">Explore the data ${icon("arrow")}</a></div>`;
  return `<div class="example-grid">${items
    .map(
      (
        item,
        index,
      ) => `<a class="example-card" data-tour="example-card" data-example-id="${esc(item.id)}" href="${base()}/examples/${encodeURIComponent(item.id)}">
<div class="example-card-top"><span class="example-symbol">${icon(item.id === "dates" ? "trend" : item.id === "compare-groups" ? "layers" : "chart")}</span><span class="tiny muted">${index === 0 ? "Start here" : `${item.panels.length} charts`}</span></div>
<h3>${esc(item.title)}</h3><p>${esc(item.question)}</p><div class="example-fields">${item.fields.map((field) => `<code>${esc(field)}</code>`).join("")}</div>
<span class="example-card-link">View example ${icon("arrow")}</span></a>`,
    )
    .join("")}</div>`;
}

function examplesSection(items) {
  return `<section class="example-section"><div class="section-head"><div><h2>Start with an example</h2><p>See the charts and code, then make it your own.</p></div><a class="link-btn" href="${base()}/examples">All examples ${icon("arrow")}</a></div>${exampleCards(items)}</section>`;
}

function examplesPage(items) {
  return `<div class="page examples-page">${heading("Example analyses", "A starting point for your research, using this dataset’s fields.")}
<ol class="example-steps"><li><span>1</span>Explore an example</li><li><span>2</span>Make your own copy</li><li><span>3</span>Run and adapt the code</li></ol>
${exampleCards(items)}<p class="example-local-note">${icon("lock")}Previews use local synthetic data. No AI connection needed.</p></div>`;
}

function exampleBar(table) {
  const max = Math.max(...table.chart.values);
  return `<div class="example-bars" role="img" aria-label="Bar chart of displayed synthetic record counts; the table below provides all values">${table.rows.map((row) => `<div class="example-bar-row"><span title="${esc(row.group)}">${esc(row.group)}</span><div class="example-bar-track"><i style="width:${(100 * row.records) / max}%"></i></div><strong>${fmt(row.records)}</strong></div>`).join("")}</div>`;
}

function exampleLine(table) {
  const { values, labels, positions } = table.chart;
  const max = Math.max(...values),
    end = Math.max(...positions, 1);
  const x = (i) => 48 + (positions[i] / end) * 530;
  const y = (value) => 230 - (value / max) * 195;
  const path = values
    .map(
      (value, i) =>
        `${i && positions[i] === positions[i - 1] + 1 ? "L" : "M"}${x(i)},${y(value)}`,
    )
    .join(" ");
  return `<svg class="example-line" viewBox="0 0 620 320" role="img" aria-label="Line chart of displayed synthetic record counts; gaps are not connected. The table below provides all values.">
${[0, 0.5, 1].map((ratio) => `<line x1="48" x2="580" y1="${y(max * ratio)}" y2="${y(max * ratio)}" stroke="#e6e6e6"/><text x="40" y="${y(max * ratio) + 4}" text-anchor="end">${fmt(Math.round(max * ratio))}</text>`).join("")}
<path d="${path}" fill="none" stroke="#1481F1" stroke-width="3"/>
${values.map((value, i) => `<circle cx="${x(i)}" cy="${y(value)}" r="4" fill="#014FE9"><title>${esc(labels[i])}: ${fmt(value)} records</title></circle>${i % Math.ceil(values.length / 6) === 0 || i === values.length - 1 ? `<text transform="translate(${x(i)},250) rotate(35)">${esc(labels[i])}</text>` : ""}`).join("")}</svg>`;
}

function exampleHeatmap(table) {
  const rows = [...new Set(table.rows.map((row) => row.row))].sort();
  const columns = [...new Set(table.rows.map((row) => row.column))].sort();
  const max = Math.max(...table.chart.values);
  return `<div class="table-scroll example-heatmap"><table><caption class="sr-only">Synthetic record counts for displayed category combinations</caption><thead><tr><th scope="col">Group</th>${columns.map((column) => `<th scope="col">${esc(column)}</th>`).join("")}</tr></thead><tbody>${rows
    .map(
      (row) =>
        `<tr><th scope="row">${esc(row)}</th>${columns
          .map((column) => {
            const cell = table.rows.find(
              (item) => item.row === row && item.column === column,
            );
            return cell
              ? `<td class="heat-${cell.records > max * 0.65 ? "high" : cell.records > max * 0.3 ? "mid" : "low"}">${fmt(cell.records)}</td>`
              : '<td aria-label="Not displayed">—</td>';
          })
          .join("")}</tr>`,
    )
    .join(
      "",
    )}</tbody></table></div><p class="tiny muted">Blank combinations are not displayed; they do not mean zero.</p>`;
}

function examplePanel(panel, table, index) {
  let chart;
  if (!table.rows.length)
    chart =
      '<div class="example-chart-empty">No groups meet the minimum size. Try coarser grouping in your own copy.</div>';
  else
    chart =
      panel.chart === "bar"
        ? exampleBar(table)
        : panel.chart === "line"
          ? exampleLine(table)
          : panel.chart === "heatmap"
            ? exampleHeatmap(table)
            : drawChart(table, "pie");
  return `<figure class="example-panel" aria-labelledby="example-panel-${index}"><figcaption id="example-panel-${index}"><span class="tiny muted">${esc(chartNames[panel.chart])}</span><h3>${esc(panel.title)}</h3></figcaption>${chart}
<details class="example-table"><summary>View counts${table.withheld_groups ? ` · ${fmt(table.withheld_groups)} groups withheld` : ""}</summary><div class="table-scroll"><table><caption class="sr-only">${esc(panel.title)}</caption><thead><tr><th scope="col">Group</th><th scope="col">Records</th></tr></thead><tbody>${table.rows.map((row) => `<tr><th scope="row">${esc(row.group)}</th><td>${fmt(row.records)}</td></tr>`).join("")}</tbody></table></div></details></figure>`;
}

function examplePage(example) {
  const provenance = example.provenance;
  const cells = example.cells.filter((cell) => cell.kind === "code");
  return `<div class="page example-detail"><a class="link-btn example-back" href="${base()}/examples">${icon("chevron")}All examples</a>
${heading(example.title, example.question, `<button class="btn primary" data-tour="use-example" data-action="use-example" data-id="${esc(example.id)}">${icon("plus")}Use this example</button>`)}
<div class="example-intro"><div><h2>What you’ll learn</h2><ul>${example.learn.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></div><div><h2>Fields in this example</h2><div class="example-fields">${example.fields.map((field) => `<code>${esc(field)}</code>`).join("")}</div><button class="link-btn" data-action="example-code">${icon("code")}See the code</button></div></div>
<section aria-labelledby="example-preview-heading"><div class="section-head"><div><h2 id="example-preview-heading">Synthetic preview</h2><p>${esc(provenance.dataset)}${provenance.dataset_version != null ? ` · version ${esc(provenance.dataset_version)}` : ""}</p></div><span class="pill soft">Local data</span></div>
${example.preview.status === "ready" ? `<div class="example-preview-grid">${example.panels.map((panel, index) => examplePanel(panel, example.preview.tables[panel.series], index)).join("")}</div>` : `<div class="notice"><span><strong>Preview unavailable</strong><p>${esc(example.preview.message)}</p><p>You can still inspect the code and make a copy.</p></span></div>`}
<p class="example-preview-note">These charts help you practice a method. They are not findings about real people. Groups below ${fmt(provenance.min_cell)} records are withheld.</p></section>
<details id="example-source" class="example-source"><summary>${icon("code")}Notebook code <span class="tiny muted">${cells.length} Python cells · pandas & matplotlib</span></summary><p>Use this example to get an editable copy. Run all cells in order to create your notebook outputs.</p>${cells.map((cell, index) => `<section class="example-source-cell"><h3>Python · cell ${index + 1}</h3><pre class="code"><code>${esc(cell.source)}</code></pre></section>`).join("")}</details>
<details class="example-method"><summary>Method and limitations</summary><p>These examples count records, not unique people. Numeric bands follow the field’s scale; invalid numeric values and dates are excluded. Long category labels are grouped. Dates may be shifted.</p><p>Only the first 20 eligible groups are displayed. A second group is withheld when needed; heatmaps and pies use only displayed groups. This local preview is not TRE output approval and does not assess inference across repeated queries.</p><p>Copying starts a new notebook without outputs. Your changes stay in your copy. Preview data is never sent to AI.</p></details>
<div class="example-next"><span><strong>Ready to try it?</strong><small>Make a copy, run the cells, then adapt them with the assistant.</small></span><button class="btn primary" data-tour="use-example" data-action="use-example" data-id="${esc(example.id)}">Use this example ${icon("arrow")}</button></div></div>`;
}

function showExampleCode() {
  const details = document.getElementById("example-source");
  if (!details) return;
  details.open = true;
  details.querySelector("summary")?.focus();
  details.scrollIntoView({ block: "start" });
}

async function useExample(id) {
  const example = s.example,
    projectId = pid(),
    routeVersion = s.routeVersion;
  if (!example || example.id !== id) return;
  const key = [projectId, id, example.version].join(":");
  if (pendingCopies.has(key)) return;
  if (!copyRequests.has(key)) copyRequests.set(key, crypto.randomUUID());
  pendingCopies.add(key);
  const buttons = [...document.querySelectorAll('[data-action="use-example"]')];
  buttons.forEach((button) => {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  });
  try {
    const notebook = await post(
      `${apiProject(projectId)}/examples/${encodeURIComponent(id)}/copy`,
      { version: example.version, request_id: copyRequests.get(key) },
    );
    copyRequests.delete(key);
    if (routeVersion !== s.routeVersion || projectId !== pid()) return;
    s.tutorialAdvance?.("copy", { notebookId: notebook.id });
    await go(
      `${base(projectId)}/notebook/${encodeURIComponent(notebook.id)}?layout=both`,
    );
    toast("Your copy is ready. Run all to see its charts.");
  } finally {
    pendingCopies.delete(key);
    buttons.forEach((button) => {
      if (button.isConnected) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
    });
  }
}

function exampleNotebookHint(notebook) {
  if (!notebook.example) return "";
  const ran = notebook.cells.some((cell) => cell.output);
  return `<div class="example-notebook-hint">${icon("notebook")}<span><strong>${ran ? "Your editable copy" : "Your copy is ready"}</strong><small>${ran ? "Select Use with AI on a cell for help adapting its code." : "Run all to create the charts. Then edit a cell or select Use with AI for help."}</small></span><a class="link-btn tiny" href="${base()}/examples/${encodeURIComponent(notebook.example.id)}">Original example</a></div>`;
}

export {
  examplesSection,
  examplesPage,
  examplePage,
  showExampleCode,
  useExample,
  exampleNotebookHint,
};
