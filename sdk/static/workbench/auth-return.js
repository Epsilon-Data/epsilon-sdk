// The callback commits a local document before returning to the Strict-cookie
// workspace. Drop the consumed authorization code from browser history first.
const destination = document.body.dataset.destination;
const next = new URL(destination || "/signin", window.location.origin);
if (next.origin === window.location.origin) {
  history.replaceState(null, "", next.pathname + next.search);
  window.location.replace(next.pathname + next.search);
}
