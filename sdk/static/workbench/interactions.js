import { parts, s, labelControls } from "./core.js";
import { saveNotebook } from "./app.js";
import { artifactMarkup } from "./pages.js";

// All source-dependent actions pass through this one persistence boundary.
async function flushNotebook({ persistDraft = false } = {}) {
  if (persistDraft && s.notebook?.temporary) s.notebookDirty = true;
  while (s.notebookDirty || s.notebookSaving) await saveNotebook();
}

const pendingActions = new Set();
async function once(key, operation, button = null) {
  if (pendingActions.has(key)) return;
  pendingActions.add(key);
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
  try {
    return await operation();
  } finally {
    pendingActions.delete(key);
    if (button?.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
}

function updateNavigation(open = false, restore = false) {
  const sidebar = document.getElementById("workspace-navigation");
  if (!sidebar) return;
  const mobile = matchMedia("(max-width: 720px)").matches;
  s.mobile = mobile && open;
  sidebar.classList.toggle("is-open", s.mobile);
  sidebar.inert = mobile && !s.mobile;
  document
    .querySelector(".mobile-overlay")
    ?.classList.toggle("visible", s.mobile);
  const toggle = document.querySelector('[data-action="menu"]');
  toggle?.setAttribute("aria-expanded", String(s.mobile));
  document.querySelector(".main-shell")?.toggleAttribute("inert", s.mobile);
  if (s.mobile) sidebar.querySelector("a,button")?.focus();
  else if (restore) toggle?.focus();
}

document.addEventListener("keydown", (event) => {
  if (!s.mobile || document.getElementById("modal")?.open) return;
  if (event.key === "Escape") {
    event.preventDefault();
    updateNavigation(false, true);
  }
  if (event.key === "Tab") {
    const targets = [
      ...document.querySelectorAll(
        "#workspace-navigation a[href],#workspace-navigation button:not([disabled])",
      ),
    ];
    const first = targets[0],
      last = targets.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
});
window.addEventListener("resize", () => updateNavigation(s.mobile));

const viewMemory = new Map();
function viewNodes() {
  const counts = new Map();
  return [
    ...document.querySelectorAll("details,.table-scroll,.rich-output"),
  ].map((node) => {
    const scope =
      node.closest("[data-draft-id]")?.dataset.draftId ||
      node.closest(".notebook-cell")?.querySelector(".cell-editor")?.dataset
        .cellId ||
      "page";
    const prefix =
      scope + "|" + node.tagName + "|" + (node.id || node.className);
    const occurrence = counts.get(prefix) || 0;
    counts.set(prefix, occurrence + 1);
    return { node, key: prefix + "|" + occurrence };
  });
}
function rememberView() {
  const path = location.pathname;
  const saved = viewMemory.get(path) || new Map();
  for (const { node, key } of viewNodes())
    saved.set(key, {
      open: node.open,
      top: node.scrollTop,
      left: node.scrollLeft,
    });
  viewMemory.set(path, saved);
  if (viewMemory.size > 20) viewMemory.delete(viewMemory.keys().next().value);
  return saved;
}
function restoreView(previous) {
  if (!(previous instanceof Map)) return;
  for (const { node, key } of viewNodes()) {
    const item = previous.get(key);
    if (!item) continue;
    if (typeof item.open === "boolean") node.open = item.open;
    node.scrollTop = item.top;
    node.scrollLeft = item.left;
  }
}

function paintResult() {
  const artifact = s.artifacts.find((a) => a.id === parts()[3]);
  const card = document.querySelector(".artifact-card");
  if (!artifact || !card) return;
  const previous = rememberView();
  const wrapper = document.createElement("div");
  wrapper.innerHTML = artifactMarkup(artifact);
  card.replaceWith(wrapper.firstElementChild);
  restoreView(previous);
  labelControls();
}

export {
  flushNotebook,
  once,
  paintResult,
  rememberView,
  restoreView,
  updateNavigation,
};
