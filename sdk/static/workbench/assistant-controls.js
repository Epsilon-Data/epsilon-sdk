import {
  api,
  apiProject,
  close,
  dialog,
  esc,
  icon,
  pid,
  post,
  s,
  showError,
  toast,
} from "./core.js";
import { render, submitQuestion } from "./app.js";
import { flushNotebook } from "./interactions.js";
import { watch } from "./jobs.js";
import { selectWorkspaceLayout, workspaceJob } from "./workspace.js";

function selectedContext(value = s.selectedContext) {
  if (
    !value ||
    value.project_id !== pid() ||
    value.notebook_id !== s.notebook?.id
  )
    return null;
  const shared = value.shared_cells || [
    { cell_id: value.cell_id, source: value.source, kind: value.kind },
  ];
  return shared.every((item) => {
    const cell = s.notebook.cells.find((c) => c.id === item.cell_id);
    return (
      cell &&
      cell.source === item.source &&
      (cell.kind || "code") === (item.kind || "code")
    );
  })
    ? value
    : null;
}

function contextMarkup() {
  const selected = selectedContext();
  const stale = s.selectedContext;
  const research = s.project?.research_context;
  const hasGoal = research?.goal || research?.fields?.length;
  if (
    !selected &&
    stale?.project_id === pid() &&
    stale?.notebook_id === s.notebook?.id
  )
    return `<div class="assistant-context"><span>Selected cell changed</span><button class="link-btn tiny" type="button" data-action="use-cell-context" data-cell-id="${esc(stale.cell_id)}">Review again</button><button class="link-btn tiny" type="button" data-action="clear-cell-context">Remove</button></div>`;
  return `<div class="assistant-context"><span>${selected ? `Cell ${selected.cell_number}${selected.helper_cell_ids?.length ? ` + ${selected.helper_cell_ids.length} helper${selected.helper_cell_ids.length === 1 ? "" : "s"}` : ""} attached · type your question and send` : `Using dataset fields${hasGoal ? " · saved goal" : ""}`}</span>${selected ? '<button class="link-btn tiny" type="button" data-action="clear-cell-context">Remove cell</button>' : '<button class="link-btn tiny" type="button" data-action="research-context">Research goal</button>'}</div>`;
}

async function reviewCell(button, retry = null) {
  await flushNotebook({ persistDraft: true });
  const projectId = pid(),
    notebookId = retry?.metadata.request.notebook_id || s.notebook.id;
  const cellId =
    retry?.metadata.request.selection.cell_id || button.dataset.cellId;
  const repair = retry?.metadata.request.selection.purpose === "repair";
  const helperCellIds = retry?.metadata.request.selection.helper_cell_ids || [];
  const review = await post(
    `${apiProject(projectId)}/notebooks/${encodeURIComponent(notebookId)}/cells/${encodeURIComponent(cellId)}/${repair ? "repair-preview" : "context-preview"}`,
    repair ? {} : { helper_cell_ids: helperCellIds },
  );
  if (pid() !== projectId || s.notebook?.id !== notebookId) return;
  s.contextReview = { review, retry };
  dialog(
    retry ? "Review and retry" : `Use cell ${review.cell_number} with AI`,
    [review.connection.provider, review.connection.model]
      .filter(Boolean)
      .join(" · "),
    `<p>${esc(review.sharing)}</p><p class="tiny muted repair-sharing">Check this code for sensitive values before sharing.</p>${retry ? `<p class="context-question">${esc(retry.metadata.request.question)}</p>` : "<p>Get an explanation now, or attach this cell and write your own question in chat.</p>"}${!repair && s.notebook.cells.filter((cell) => cell.kind === "code" && cell.id !== review.cell_id).length ? `<details class="helper-share"><summary>Include helper cells (optional)</summary><p class="tiny muted">Select definitions this cell needs. Epsilon will show the combined source before anything is sent.</p>${s.notebook.cells.map((cell) => (cell.kind === "code" && cell.id !== review.cell_id ? `<label><input type="checkbox" data-helper-cell="${esc(cell.id)}" ${helperCellIds.includes(cell.id) ? "checked" : ""}>Cell ${cell.cell_number || s.notebook.cells.indexOf(cell) + 1} · ${esc(cell.source.split("\n")[0].slice(0, 90) || "empty cell")}</label>` : "")).join("")}</details>` : ""}<details class="repair-source" open><summary>Shared source · cell ${review.cell_number}${review.helper_cell_ids?.length ? ` + ${review.helper_cell_ids.length} helper${review.helper_cell_ids.length === 1 ? "" : "s"}` : ""}</summary><pre><code>${esc(review.source)}</code></pre></details>${review.diagnostic ? `<p>${esc(review.diagnostic.summary)}</p>` : ""}${review.connection.base_url ? `<p class="tiny muted repair-endpoint">Endpoint: ${esc(review.connection.base_url)}</p>` : ""}<p class="form-error" id="context-error" role="alert"></p>`,
    `<button class="btn" data-action="close">Cancel</button>${retry ? '<button class="btn primary" data-action="confirm-cell-context">Retry with this cell</button>' : '<button class="btn" data-action="confirm-cell-context">Ask my own question</button><button class="btn primary" data-action="explain-cell">Explain this cell</button>'}`,
  );
}

async function confirmCellContext(intent = "attach") {
  const current = s.contextReview;
  if (
    !current ||
    pid() !== current.review.project_id ||
    s.notebook?.id !== current.review.notebook_id ||
    current.submitting
  )
    return;
  current.submitting = true;
  try {
    if (current.retry) {
      const job = await post(
        `${apiProject()}/threads/${encodeURIComponent(current.retry.metadata.request.thread_id)}/requests/${encodeURIComponent(current.retry.id)}/retry`,
        {
          selected_cell: {
            cell_id: current.review.cell_id,
            context_digest: current.review.context_digest,
            confirmed: true,
            helper_cell_ids: current.review.helper_cell_ids || [],
          },
        },
      );
      close();
      s.jobs[job.id] = job;
      await render();
      watch(job).catch(showError);
    } else {
      if (intent === "explain" && workspaceJob("chat"))
        throw new Error(
          "Wait for the current reply to finish, then try again.",
        );
      if (!selectedContext(current.review))
        throw new Error(
          "The cell changed. Close this dialog and review the cell again.",
        );
      if (intent === "explain") {
        selectWorkspaceLayout("both");
        const job = await submitQuestion(
          `Explain notebook cell ${current.review.cell_number} in plain language. Describe what it does, how to run it, and what I can change. Call out any dependencies whose definitions are not included.`,
          { preserveDraft: true, reviewedCell: current.review },
        );
        if (!job)
          throw new Error(
            "A question is already being sent. Wait for it to finish, then try again.",
          );
        // Sending renders the conversation; don't dismiss a newer dialog.
        if (
          s.contextReview !== current ||
          pid() !== current.review.project_id ||
          s.notebook?.id !== current.review.notebook_id
        )
          return;
        close();
        return;
      }
      s.selectedContext = current.review;
      close();
      selectWorkspaceLayout("both");
      await render();
      document.getElementById("chat-ask-input")?.focus();
      toast(
        `Cell ${current.review.cell_number} attached. Type your question and press Send.`,
      );
    }
  } catch (error) {
    const target = document.getElementById("context-error");
    if (target) target.textContent = error.message;
    else showError(error);
  } finally {
    current.submitting = false;
  }
}

async function refreshContextPreview() {
  const current = s.contextReview;
  if (!current || current.retry || !current.review?.cell_id) return;
  const helperCellIds = [
    ...document.querySelectorAll("[data-helper-cell]:checked"),
  ].map((input) => input.dataset.helperCell);
  try {
    const review = await post(
      `${apiProject(current.review.project_id)}/notebooks/${encodeURIComponent(current.review.notebook_id)}/cells/${encodeURIComponent(current.review.cell_id)}/context-preview`,
      { helper_cell_ids: helperCellIds },
    );
    if (s.contextReview !== current) return;
    current.review = review;
    const source = document.querySelector(".repair-source pre code");
    if (source) source.textContent = review.source;
    const summary = document.querySelector(".repair-source summary");
    if (summary)
      summary.textContent = `Shared source · cell ${review.cell_number}${review.helper_cell_ids?.length ? ` + ${review.helper_cell_ids.length} helper${review.helper_cell_ids.length === 1 ? "" : "s"}` : ""}`;
    const sharing = document.querySelector(".repair-sharing");
    if (sharing) sharing.textContent = review.sharing;
  } catch (error) {
    const target = document.getElementById("context-error");
    if (target) target.textContent = error.message;
    else showError(error);
  }
}

async function retryRequest(button) {
  const request = s.thread?.requests?.find((r) => r.id === button.dataset.id);
  if (!request) return;
  if (request.metadata.request.selection) return reviewCell(button, request);
  const projectId = pid(),
    threadId = s.thread.id;
  const job = await post(
    `${apiProject(projectId)}/threads/${encodeURIComponent(threadId)}/requests/${encodeURIComponent(request.id)}/retry`,
  );
  s.jobs[job.id] = job;
  if (pid() === projectId && s.thread?.id === threadId) await render();
  watch(job).catch(showError);
}

function requestRecovery(message) {
  const request = s.thread?.requests?.find((r) => r.id === message.request_id);
  if (
    !request ||
    !["failed", "cancelled", "interrupted"].includes(request.status)
  )
    return "";
  const latest =
    s.thread.messages.filter((m) => m.role === "user").at(-1)?.seq ===
    message.seq;
  const busy = s.thread.requests.some((r) =>
    ["queued", "running"].includes(r.status),
  );
  const settings = [
    "configuration",
    "authentication",
    "permission",
    "credits",
    "spend_limit",
    "quota",
    "not_found",
    "request",
  ].includes(request.reason);
  return `<div class="assistant-recovery" role="status"><strong>${request.status === "interrupted" ? "Request interrupted" : request.status === "cancelled" ? "Request cancelled" : "Needs attention"}</strong><p>${esc(request.error || "The assistant did not finish. Your work is saved.")}</p><div class="row">${latest ? `<button class="btn small" data-action="retry-question" data-id="${esc(request.id)}" ${busy ? "disabled" : ""}>${icon("refresh")}${request.metadata.request.selection ? "Review & retry" : "Retry"}</button>` : '<span class="tiny muted">Continue with a new question below.</span>'}${settings ? '<a class="btn small" href="/settings">AI settings</a>' : ""}</div></div>`;
}

async function editResearchContext() {
  const projectId = pid(),
    [current, learned] = await Promise.all([
      api(apiProject(projectId) + "/research-context"),
      api(apiProject(projectId) + "/vocabulary"),
    ]);
  if (pid() !== projectId) return;
  const fields = s.project.dataset.fields || [],
    names = Object.entries(learned.vocabulary);
  dialog(
    "Research goal",
    "Remember the question and variables for this project.",
    `<form id="research-context-form" data-project="${esc(projectId)}" class="stack"><p class="tiny muted">This goal and the selected field names are included in ordinary AI questions. Keep data values and confidential notes out of this description.</p><label class="field">What are you investigating?<textarea name="goal" maxlength="2000" rows="3">${esc(current.goal)}</textarea></label><fieldset class="context-fields"><legend>Variables to focus on</legend>${fields.map((f) => `<label><input type="checkbox" name="fields" value="${esc(f.path)}" ${current.fields.includes(f.path) ? "checked" : ""}>${esc(f.path)}</label>`).join("")}</fieldset>${names.length ? `<fieldset class="learned-fields"><legend>Column names you confirmed</legend><p class="tiny muted">When you use these words, the assistant uses the column you chose. Remove one to be asked again.</p><ul>${names.map(([term, path]) => `<li><q>${esc(term)}</q> ${icon("arrow")} <code>${esc(path)}</code><button class="link-btn tiny" type="button" data-action="forget-field" data-term="${esc(term)}">Remove</button></li>`).join("")}</ul></fieldset>` : ""}<p class="form-error" role="alert"></p></form>`,
    '<button class="btn" data-action="close">Cancel</button><button class="btn primary" form="research-context-form" type="submit">Save goal</button>',
  );
}

async function saveResearchContext(form) {
  const value = await api(
    apiProject(form.dataset.project) + "/research-context",
    {
      method: "PUT",
      body: {
        goal: form.elements.goal.value,
        fields: [...form.querySelectorAll('input[name="fields"]:checked')].map(
          (el) => el.value,
        ),
      },
    },
  );
  if (pid() === form.dataset.project && s.project) {
    s.project.research_context = value;
    const context = document.querySelector(".assistant-context");
    if (context) context.outerHTML = contextMarkup();
  }
  close();
  toast("Research goal saved for this project.");
}

export {
  selectedContext,
  contextMarkup,
  reviewCell,
  confirmCellContext,
  retryRequest,
  requestRecovery,
  editResearchContext,
  saveResearchContext,
  refreshContextPreview,
};
