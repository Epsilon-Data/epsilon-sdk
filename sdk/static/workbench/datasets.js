import {
  api,
  apiProject,
  base,
  dialog,
  esc,
  icon,
  pid,
  post,
  s,
  toast,
} from "./core.js";
import { go } from "./app.js";
import { watch } from "./jobs.js";

let choices = { status: "idle", items: [] };

function resetDatasetChoices() {
  choices = { status: "idle", items: [] };
}

function datasetName(item) {
  return (
    choices.items.find((choice) => choice.id === item.id)?.name || item.name
  );
}

function datasetChoicesMarkup() {
  if (!s.session?.account?.authenticated)
    return `<div class="notice info"><span>Sign in to see your approved datasets.</span>
<button class="btn" data-action="signin">Sign in</button></div>`;
  const header = `<div class="section-head"><h2>Approved for your account${choices.status === "ready" ? `<span class="section-count">${choices.items.length}</span>` : ""}</h2>
<button class="link-btn" data-action="refresh-datasets" ${choices.status === "loading" ? "disabled" : ""}>Refresh ${icon("refresh")}</button></div>`;
  if (["idle", "loading"].includes(choices.status))
    return `${header}<p class="dataset-loading" role="status">Loading your datasets…</p>`;
  if (choices.status === "error")
    return `${header}<div class="notice" role="alert"><span>${esc(choices.error)}</span>
<button class="btn" data-action="${choices.signin ? "signin" : "refresh-datasets"}">${choices.signin ? "Sign in" : "Retry"}</button></div>`;
  if (!choices.items.length)
    return `${header}<div class="empty-state"><h3>No approved datasets yet</h3><p>Ask your project coordinator for dataset access, then refresh this list.</p></div>`;
  return `${header}<div class="approved-dataset-list">${choices.items
    .map(
      (
        item,
      ) => `<article class="approved-dataset-card" data-dataset-id="${esc(item.id)}">
<span class="project-icon">${icon("database", "lg")}</span>
<div class="dataset-card-description"><h3>${esc(item.name === item.id ? "Dataset " + item.id.slice(0, 8) : item.name)}</h3>
${item.description ? `<p>${esc(item.description)}</p>` : ""}
<small>${item.details === "loading" ? "Loading dataset details…" : item.details === "error" ? "Dataset details could not be loaded." : item.synthetic_available ? "Synthetic data available" : "Synthetic data not attached"}</small></div>
<button class="btn ${item.details === "error" ? "" : "primary"}" data-action="${item.details === "error" ? "retry-dataset" : "choose-dataset"}" data-id="${esc(item.id)}" ${item.details === "loading" ? "disabled" : ""}>${item.details === "error" ? "Retry details" : "Select dataset"} ${icon("arrow")}</button>
</article>`,
    )
    .join("")}</div>`;
}

function paintDatasetChoices() {
  const container = document.getElementById("approved-datasets");
  if (container) container.innerHTML = datasetChoicesMarkup();
}

async function loadDetails(batch, item) {
  item.details = "loading";
  paintDatasetChoices();
  try {
    const details = await api("/api/datasets/" + encodeURIComponent(item.id));
    if (choices !== batch) return;
    Object.assign(item, details, { details: "ready" });
  } catch (error) {
    if (choices !== batch) return;
    item.details = "error";
    if (error.status === 401) {
      batch.status = "error";
      batch.signin = true;
      batch.error = "Sign in again to see your approved datasets.";
    }
  }
  if (choices === batch) paintDatasetChoices();
}

async function refreshDatasetChoices() {
  if (!s.session?.account?.authenticated) {
    resetDatasetChoices();
    paintDatasetChoices();
    return;
  }
  if (choices.status === "loading") return choices.pending;
  const batch = { status: "loading", items: [] };
  choices = batch;
  paintDatasetChoices();
  batch.pending = (async () => {
    try {
      const response = await api("/api/datasets");
      if (choices !== batch) return;
      batch.items = response.datasets.map((item) => ({
        ...item,
        details: "loading",
      }));
      batch.status = "ready";
      paintDatasetChoices();
      // Keep metadata requests bounded, and show each card as soon as it is ready.
      let next = 0;
      await Promise.all(
        Array.from({ length: Math.min(3, batch.items.length) }, async () => {
          while (
            choices === batch &&
            batch.status === "ready" &&
            next < batch.items.length
          )
            await loadDetails(batch, batch.items[next++]);
        }),
      );
    } catch (error) {
      if (choices !== batch) return;
      batch.status = "error";
      batch.signin = error.status === 401;
      batch.error = batch.signin
        ? "Sign in again to see your approved datasets."
        : "We couldn't load your datasets. Check your connection and retry.";
      paintDatasetChoices();
    }
  })();
  return batch.pending;
}

function ensureDatasetChoices() {
  if (choices.status === "idle") return refreshDatasetChoices();
}

async function retryDatasetDetails(id) {
  const item = choices.items.find((candidate) => candidate.id === id);
  if (item) await loadDetails(choices, item);
}

function selectDataset(id) {
  const selected = choices.items.find((item) => item.id === id);
  if (!selected || selected.details !== "ready")
    throw new Error(
      "Refresh the dataset list and select an available dataset.",
    );
  const name = selected.name.slice(0, 100);
  const folder =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60) || "research-project";
  dialog(
    "Set up your project",
    "Choose where to keep the code and notebooks.",
    `<form id="dataset-project-form" class="stack">
<div class="selected-dataset"><span class="project-icon">${icon("database")}</span><strong>${esc(selected.name)}</strong></div>
<input type="hidden" name="dataset_id" value="${esc(id)}">
<label class="field">Project name<input name="name" required maxlength="100" value="${esc(name)}"></label>
<label class="field">Local project folder<input name="path" required maxlength="500" value="~/Epsilon Projects/${esc(folder)}"><small>Epsilon creates this folder if needed and preserves existing research files.</small></label>
${selected.synthetic_available ? '<p class="tiny muted">The synthetic dataset and its field definitions will be downloaded to this folder.</p>' : '<div class="notice">This dataset has no attached synthetic data.</div><label class="row tiny"><input type="checkbox" name="dummy_data" required>Use generated sample data for development</label>'}
<p class="form-error" role="alert"></p></form>`,
    `<button class="btn" data-action="close">Cancel</button><button class="btn primary" type="submit" form="dataset-project-form">Initialize project ${icon("download")}</button>`,
  );
}

async function createDatasetProject(form) {
  const account = s.session?.account;
  if (!account?.authenticated)
    throw new Error("Sign in to initialize a project.");
  const datasetId = form.elements.dataset_id.value;
  if (!form.dataset.projectId) {
    const project = await post("/api/projects", {
      name: form.elements.name.value,
      path: form.elements.path.value,
      description: "",
      dataset_id: datasetId,
    });
    form.dataset.projectId = project.id;
    form.elements.name.readOnly = true;
    form.elements.path.readOnly = true;
  }
  if (s.session.account !== account)
    throw new Error(
      "The signed-in account changed. Select a dataset again before initializing.",
    );
  const projectId = form.dataset.projectId;
  const job = await post(apiProject(projectId) + "/initialise", {
    dataset_id: datasetId,
    dummy_data: Boolean(form.elements.dummy_data?.checked),
  });
  s.jobs[job.id] = job;
  await go(base(projectId));
  watch(job, async (result) => {
    if (pid() === projectId) await go(base(projectId));
    toast(result.warnings?.join(" ") || "Your project is ready.");
  }).catch((error) => toast(error.message));
}

export {
  createDatasetProject,
  datasetChoicesMarkup,
  datasetName,
  ensureDatasetChoices,
  refreshDatasetChoices,
  resetDatasetChoices,
  retryDatasetDetails,
  selectDataset,
};
