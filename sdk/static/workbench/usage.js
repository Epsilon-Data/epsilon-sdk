import { api, base, esc, icon, post, s, showError, toast } from "./core.js";

// Token and cost figures are estimates from the provider's own usage report
// and list prices. Nothing here reads a conversation or notebook.
function formatTokens(value) {
  const n = Number(value) || 0;
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
  if (n >= 10_000) return (n / 1000).toFixed(1) + "k";
  return n.toLocaleString("en-GB");
}
function formatCost(cost) {
  if (cost === null || cost === undefined) return "cost unavailable";
  if (cost === 0) return "$0.00";
  return "≈ $" + (cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2));
}
function ratesText(rates) {
  return rates
    ? `$${rates.input.toFixed(2)} in / $${rates.output.toFixed(2)} out per 1M tokens · ${esc(rates.source)}`
    : "No rates known for this model. Add your own below to estimate cost.";
}
function costNote(usage) {
  // Some requests may have used a model with no known rates.
  return usage.unpriced && usage.cost !== null
    ? ` <span class="muted">(${usage.unpriced} without rates)</span>`
    : "";
}
function messageUsage(usage) {
  if (!usage) return "";
  if (!usage.total_tokens)
    return '<div class="message-usage">Token usage was not reported by this provider.</div>';
  const models = usage.models.map((m) => m.model).join(", ");
  return `<div class="message-usage" title="Estimated from the provider's usage report">
<span>${formatTokens(usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens)} in</span>
<span>${formatTokens(usage.output_tokens)} out</span>${usage.cache_read_tokens ? `<span>${formatTokens(usage.cache_read_tokens)} cached</span>` : ""}
<span><strong>${formatTokens(usage.total_tokens)} tokens</strong></span>
<span>${formatCost(usage.cost)}${costNote(usage)}</span>
<span class="truncate">${esc(models)}${usage.calls > 1 ? ` · ${usage.calls} model calls` : ""}</span>
</div>`;
}
function usageTotals(label, usage) {
  if (!usage?.requests) return "";
  return `<span class="usage-total">${esc(label)}: <strong>${formatTokens(usage.total_tokens)} tokens</strong> · ${formatCost(usage.cost)}${costNote(usage)}</span>`;
}
function workspaceUsage() {
  const thread = usageTotals("This workspace", s.thread?.usage),
    project = usageTotals("Project", s.project?.usage);
  return thread || project
    ? `<div class="usage-bar" role="status">${icon("chart")}${thread}${project}</div>`
    : "";
}
function usageTable(report) {
  if (!report?.total?.requests)
    return '<p class="tiny muted">No AI requests have been recorded yet.</p>';
  const row = (
    name,
    usage,
    strong = false,
  ) => `<tr${strong ? ' class="usage-total-row"' : ""}>
<th scope="row">${esc(name)}</th>
<td>${usage.requests}</td>
<td>${formatTokens(usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens)}</td>
<td>${formatTokens(usage.output_tokens)}</td>
<td>${formatTokens(usage.total_tokens)}</td>
<td>${formatCost(usage.cost)}${costNote(usage)}</td>
</tr>`;
  return `<div class="usage-table-wrap"><table class="usage-table">
<thead><tr><th scope="col">Project</th><th scope="col">Requests</th><th scope="col">Input</th><th scope="col">Output</th><th scope="col">Total tokens</th><th scope="col">Estimated cost</th></tr></thead>
<tbody>${report.projects
    .filter((p) => p.usage.requests)
    .map((p) => row(p.name, p.usage))
    .join("")}${row("All projects", report.total, true)}</tbody>
</table></div>
<details class="quiet-details"><summary>By model</summary><ul class="usage-models">${report.total.models
    .map(
      (m) =>
        `<li><code>${esc(m.model)}</code> · ${m.requests} requests · ${formatTokens(m.total_tokens)} tokens · ${formatCost(m.cost)}</li>`,
    )
    .join("")}</ul></details>`;
}

function modelPicker(disabled = false) {
  const ai = s.session?.ai;
  if (!ai?.configured) return "";
  const listed = s.models?.models || [{ id: ai.model, label: ai.model }];
  return `<label class="model-picker" title="AI model for your next question">
<span class="hidden">AI model</span>
<select data-model-picker ${disabled ? "disabled" : ""}>${listed
    .map(
      (m) =>
        `<option value="${esc(m.id)}" ${m.id === ai.model ? "selected" : ""}>${esc(m.label)}</option>`,
    )
    .join("")}<option value="">Other model…</option></select>
</label>`;
}
async function loadModels(refresh = false) {
  if (!s.session?.ai?.configured || (s.models && !refresh) || s.modelsLoading)
    return s.models;
  s.modelsLoading = true;
  try {
    s.models = await api(
      "/api/settings/ai/models" + (refresh ? "?refresh=true" : ""),
    );
    // Repaint only the pickers: a full render would disturb a half-typed question.
    document.querySelectorAll(".model-picker").forEach((el) => {
      const disabled = el.querySelector("select")?.disabled;
      el.outerHTML = modelPicker(disabled);
    });
  } catch {
    s.models = null;
  } finally {
    s.modelsLoading = false;
  }
  return s.models;
}
async function chooseModel(select, go) {
  if (!select.value) {
    select.value = s.session.ai.model;
    return go("/settings");
  }
  const previous = s.session.ai.model;
  try {
    s.session.ai = await post("/api/settings/ai/model", {
      model: select.value,
    });
    toast(
      `Model changed to ${select.value}. It applies to your next question.`,
    );
  } catch (error) {
    select.value = previous;
    showError(error);
  }
}

function fieldChoices(message) {
  const meta = message.meta;
  if (!meta || message.role !== "assistant") return "";
  // Only the latest reply can be answered; older choices stay as a record.
  const latest = s.thread?.messages?.at(-1)?.seq === message.seq;
  const choices = (meta.field_choices || [])
    .map(
      (choice) => `<div class="field-choice">
<p>Which column did you mean by <q>${esc(choice.term)}</q>?</p>
<div class="chat-chips">${choice.candidates
        .map(
          (c) =>
            `<button class="chat-chip field-chip" data-action="choose-field" data-term="${esc(choice.term)}" data-path="${esc(c.path)}" ${latest ? "" : "disabled"}><code>${esc(c.path)}</code><small>${esc(c.type)}</small></button>`,
        )
        .join("")}</div>
</div>`,
    )
    .join("");
  const missing = (meta.missing_fields || []).length
    ? `<p class="field-missing">${icon("info")}Not in this dataset: ${meta.missing_fields.map((t) => `<q>${esc(t)}</q>`).join(", ")}. <a href="${base()}/dataset">Browse the available columns</a></p>`
    : "";
  return choices || missing
    ? `<div class="field-choices">${choices}${missing}${choices ? '<p class="tiny muted">Your choice is remembered for this project, and sent with your next question.</p>' : ""}</div>`
    : "";
}

export {
  chooseModel,
  fieldChoices,
  loadModels,
  messageUsage,
  modelPicker,
  ratesText,
  usageTable,
  usageTotals,
  workspaceUsage,
};
