import { api, apiProject, pid, s, showError } from "./core.js";
import { progressMarkup, render } from "./app.js";
import {
  paintWorkspace,
  refreshLiveNotebook,
  researchWorkspace,
} from "./workspace.js";

function watch(job, onComplete = null) {
  if (s.watchers[job.id])
    return s.watchers[job.id].then(async (result) => {
      if (onComplete) await onComplete(result);
      return result;
    });
  const projectId = job.project_id;
  s.jobs[job.id] = job;
  s.watched.add(job.id);
  const stream = new EventSource(
    apiProject(projectId) + "/jobs/" + encodeURIComponent(job.id) + "/events",
  );
  let finished = false,
    timer,
    polling = false,
    failures = 0;
  const pending = new Promise((resolve, reject) => {
    const cleanup = () => {
      finished = true;
      clearTimeout(timer);
      stream.close();
      s.watched.delete(job.id);
    };
    const schedule = (delay) => {
      clearTimeout(timer);
      if (!finished) timer = setTimeout(poll, delay);
    };
    const receive = async (value) => {
      if (finished) return;
      failures = 0;
      s.jobs[job.id] = value;
      const writes = (value.events || []).filter(
        (e) => e.stage === "notebook",
      ).length;
      if (value.kind === "chat" && writes > (s.notebookWrites?.[job.id] || 0)) {
        s.notebookWrites = s.notebookWrites || {};
        s.notebookWrites[job.id] = writes;
        if (pid() === projectId) refreshLiveNotebook().catch(showError);
      }
      if (pid() === projectId) {
        const progress = document.getElementById(
          value.kind === "notebook" ? "notebook-progress" : "job-progress",
        );
        if (progress) progress.innerHTML = progressMarkup(value);
      }
      if (
        ["completed", "failed", "cancelled", "interrupted"].includes(
          value.status,
        )
      ) {
        cleanup();
        try {
          if (value.status === "completed") {
            if (onComplete) await onComplete(value.result);
            else if (pid() === projectId) await render();
            resolve(value.result);
          } else {
            if (pid() === projectId) await render();
            reject(new Error(value.error || "The task did not complete."));
          }
        } catch (error) {
          reject(error);
        }
      } else schedule(5000);
    };
    async function poll() {
      if (finished || polling) return;
      polling = true;
      try {
        await receive(
          await api(
            apiProject(projectId) + "/jobs/" + encodeURIComponent(job.id),
          ),
        );
      } catch (error) {
        if (error.status === 404 || error.status === 401 || ++failures >= 3) {
          cleanup();
          s.jobs[job.id] = {
            ...job,
            status: "disconnected",
            error: "Connection lost. Reconnect to check this run.",
          };
          if (pid() === projectId && s.notebook)
            paintWorkspace(researchWorkspace(), "Workspace");
          reject(
            new Error(
              "The server connection was lost. Your edits are still here. Reconnect to check the run.",
            ),
          );
        } else schedule(1000 * failures);
      } finally {
        polling = false;
      }
    }
    stream.onmessage = (event) => {
      try {
        receive(JSON.parse(event.data)).catch(reject);
      } catch {
        schedule(0);
      }
    };
    stream.onerror = () => {
      stream.close();
      schedule(0);
    };
    // Also recover a silent stream with no error event or terminal event.
    schedule(5000);
  });
  s.watchers[job.id] = pending.finally(() => {
    finished = true;
    clearTimeout(timer);
    stream.close();
    delete s.watchers[job.id];
    s.watched.delete(job.id);
  });
  return s.watchers[job.id];
}

function reconcileJobs(projectId, active) {
  const live = new Set(active.map((job) => job.id));
  for (const [id, job] of Object.entries(s.jobs)) {
    if (
      job.project_id === projectId &&
      ["queued", "running", "disconnected"].includes(job.status) &&
      !live.has(id) &&
      !s.watched.has(id)
    )
      delete s.jobs[id];
  }
  for (const job of active) {
    s.jobs[job.id] = job;
    if (!s.watched.has(job.id)) watch(job).catch(showError);
  }
}

export { reconcileJobs, watch };
