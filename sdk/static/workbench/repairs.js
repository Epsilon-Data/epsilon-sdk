import {
  apiProject,
  close,
  dialog,
  esc,
  parts,
  pid,
  post,
  s,
  showError,
} from "./core.js";
import { render } from "./app.js";
import { flushNotebook } from "./interactions.js";
import { watch } from "./jobs.js";
import { selectWorkspaceLayout } from "./workspace.js";

async function requestCellRepair(button) {
  button.disabled = true;
  const projectId = pid(),
    notebookId = s.notebook.id,
    cellId = button.dataset.cellId;
  try {
    await flushNotebook();
    const review = await post(
      apiProject(projectId) +
        "/notebooks/" +
        encodeURIComponent(notebookId) +
        "/cells/" +
        cellId +
        "/repair-preview",
    );
    if (
      pid() !== projectId ||
      s.notebook?.id !== notebookId ||
      !["assistant", "notebook"].includes(parts()[2])
    )
      return;
    s.repairReview = review;
    const destination =
      [review.connection.provider, review.connection.model]
        .filter(Boolean)
        .join(" · ") || "Your configured model";
    dialog(
      "Fix cell " + review.cell_number + " with AI",
      destination,
      `<p>${esc(review.sharing)}</p>
<p class="tiny muted repair-sharing">Check the selected code for sensitive values before sharing. A proposed fix will appear in chat for you to review.</p>
<div class="repair-diagnostic">
<strong>${esc(review.diagnostic.category)}</strong>
<p>${esc(review.diagnostic.summary)}</p>
</div>
<details class="repair-source" open>
<summary>Selected code · cell ${review.cell_number}</summary>
<pre>
<code>${esc(review.source)}</code>
</pre>
</details>${review.connection.base_url ? `<p class="tiny muted repair-endpoint">Endpoint: ${esc(review.connection.base_url)}</p>` : ""}<p id="repair-error" class="form-error" role="alert">
</p>`,
      '<button class="btn" data-action="close">Cancel</button><button class="btn primary" data-action="send-repair">Send this cell to AI</button>',
    );
  } finally {
    if (button.isConnected) button.disabled = false;
  }
}

async function sendCellRepair(button) {
  const review = s.repairReview;
  if (!review) return;
  button.disabled = true;
  try {
    const job = await post(
      apiProject(review.project_id) +
        "/notebooks/" +
        encodeURIComponent(review.notebook_id) +
        "/cells/" +
        review.cell_id +
        "/repair",
      { confirmed: true, context_digest: review.context_digest },
    );
    close();
    s.jobs[job.id] = job;
    if (pid() === review.project_id && s.notebook?.id === review.notebook_id) {
      selectWorkspaceLayout("both");
      await render();
    }
    watch(job).catch(showError);
  } catch (error) {
    const node = document.getElementById("repair-error");
    if (node) node.textContent = error.message;
    else showError(error);
  } finally {
    if (button.isConnected) button.disabled = false;
  }
}

export { requestCellRepair, sendCellRepair };
