# Workbench review fixes

Implemented on `feat/local-research-workbench`, verified on 8 September 2026.
Existing research and audit records are preserved. Nothing has been pushed,
merged or published.

## Starting a notebook

The overview now offers **Notebook starters** with visible field bindings. A
starter opens a temporary notebook with a short explanation, a small loader cell
and editable pandas analysis/chart code. Projects with generated models load
through `generated.models.create_dataset()`; older projects use the projection
CSV. The host does not import those editable generated models.

Opening or leaving an untouched starter creates no conversation, plan, notebook,
or synthetic user message. Editing, saving, running, exporting or asking the
assistant to continue saves the draft. There is one notebook execution workflow.
The deterministic counting engine remains available through the explicit
**Results → New preview → Run preview** flow.

Numeric starter summaries use bands appropriate to the synthetic values instead
of always using width ten. The cells remain method-development examples, not
scientific findings. Their local figures and tables do not become controlled
preview artifacts or model context.

**Ask AI for ideas** is an explicit action. Tailored questions and chosen fields
are both displayed. The Data page and empty Results view no longer repeat the
overview starter cards. **History → Archive** hides existing conversations and
notebooks; **Archived → Restore** brings them back without deleting content.

## Operational fixes

| Reported issue | Implemented behavior |
| --- | --- |
| Secret false positives prevent every save | Local notebook saves do not run outbound credential checks. Outbound checks use boundaries and recognise documentation placeholders; actual key patterns and known credentials remain rejected when sharing. |
| Keychain reads on every cell and in error handling | Credential resolution is cached for the current settings, CLI configuration and environment. Local saves and public-error handling do not read the keyring. |
| Orphaned credentials when changing settings | Superseded workspace-owned entries are removed when changing configuration or returning to CLI credentials. Cleanup failure is reported; unrelated credentials are untouched. Configuration and credential resolution are locked together so concurrent changes cannot combine the wrong endpoint and key. |
| Cold kernel startup blocks chat/status | Per-notebook startup reservations coordinate creation. Docker startup and shutdown run outside the shared kernel registry lock; status and stop remain responsive. |
| Repeated Docker subprocesses in chat | A single background probe serves concurrent callers and caches status for 30 seconds. Chat/status polling does not wait for that probe. Starting a kernel requires a fresh runtime check. |
| Repeated full-file hashing | A bounded cache stores digests against file identity, size, nanosecond modification and change times. Controlled previews reuse the bytes they loaded. Notebook snapshots hash while copying and verify the source fingerprint before/after; cached entries contain no dataset rows. |
| Completed output lost during a save race | Execution results are recorded atomically with their executed source. Matching cells receive the output without replacing newer edits elsewhere; changed executed cells keep their newer source and expose the completed output in paginated Run history. |
| Unexpected exceptions expose paths or become 404s | Authored public errors determine user-facing statuses. Unexpected KeyError/ValueError failures are server errors with fixed messages; raw host and provider diagnostics do not enter API/SSE error text. Local notebook tracebacks remain local notebook output. |
| Private Starlette body replay | A public ASGI receive/send middleware validates and bounds request bodies, then replays them using the documented protocol. It does not mutate private Request attributes. |
| UI plans skip promised audit records | API and model plan creation share the validated service path and its audit event. They do not fabricate a researcher message. |
| 24-hour session expiry strands the researcher | The existing local cookie plus CSRF token can renew an expired session within seven days. The client retries after renewal. Missing/older sessions and server restarts request the CLI launch link, rather than sending users into an account sign-in loop. |
| Python version, cell identity and misleading startup errors | Package minimum is Python 3.9, matching CI. Missing cell IDs receive stable UUIDs. Only address-in-use errors produce the busy-port message; state-directory permission errors have separate fixed text. |

## Interaction and maintenance fixes

| Reported issue | Implemented behavior |
| --- | --- |
| Dropped SSE connection leaves everything busy | Event streams have a status-poll fallback. Repeated failures release stale busy state and show a persistent Reconnect action. Reconciliation clears abandoned local jobs without dropping edits. |
| Enter/double clicks create duplicate work | Shared action guards cover submission, new conversations, imports, previews, undo, kernel controls and placement; notebook execution also tracks its running state. |
| Notebook IDs enter markup and paths unchecked | Client paths encode identifiers; project API path components are strictly validated. Dynamic display content is escaped. |
| Typing rebuilds every later rich output | Source changes mark stale badges once and retain the existing figure/table DOM. Autosave errors preserve source and offer an explicit retry without repeating the same toast on each keystroke. |
| Tabs/selectors refetch and reset the app | Result tabs and chart controls repaint locally with no project endpoint refetch. Same-route refreshes preserve expanded details and element scroll positions. Notebook selection uses explicit links in a picker, rather than navigating on select change. |
| Repeated save-before-action code | One save gate handles pending notebook edits before dependent navigation/actions, with an explicit option to persist a temporary draft. |
| Mobile drawer accessibility | The drawer exposes expanded state, moves/traps focus, closes with Escape and restores focus. Closed mobile navigation is inert and outside keyboard tab order. |
| Hard-to-read grey labels and nested headings | Light-background secondary text uses darker grey and small 9–10 px labels are raised to 12 px. Starter button titles use normal text structure. Existing Epsilon charcoal/blue colors are retained. |
| Implicit globals, load-order dependencies and oversized lines | Browser scripts use native ES modules with explicit imports/exports. Shared interaction/job logic has its own modules. HTML templates and source are formatted; no script line exceeds 1,000 characters. Unreferenced CSS selectors and shadowed declarations were removed, and base custom properties consolidated. |
| No automated frontend checks | Pinned development tools provide `npm run lint`, `npm test` and `npm run format`; CI installs them with `npm ci`. The shipped UI still needs no frontend build or Node runtime. |

## Verification

- **736 Python tests passed**, including real Docker/Jupyter execution and both
  local-server smoke tests:
  `EPSILON_TEST_NOTEBOOK=1 .venv/bin/python -m pytest tests -q --tb=short`.
- **19 JavaScript tests passed**, plus ESLint and formatting checks.
- **39 browser checks passed** in two review runs (27 starter/interaction checks
  and 12 repair/concurrency/result/reconnection checks), at desktop and mobile
  widths. These used a generated dataset wrapper and real Docker execution.
  There were no browser runtime exceptions.
- Wheel and sdist builds passed. An isolated wheel import verified every native
  JavaScript module, new Python modules, runtime sources, Python version metadata,
  browser bootstrap and authenticated project APIs, without importing Chainlit.

Regression cases live in `tests/test_workbench_reliability.py`,
`tests/test_workbench_starters.py`, the existing workspace suites and
`tests/workbench_reliability.test.cjs`. Browser evidence:

- [Readable temporary notebook](workbench/previews/31-readable-notebook-draft.png)
- [Executed pandas notebook](workbench/previews/32-readable-notebook-output.png)
- [Clean starters on mobile](workbench/previews/33-clean-starters-mobile.png)
- [Separate controlled preview results](workbench/previews/34-controlled-preview-results.png)

Browser runs used isolated fixture authentication and scripted model responses
through the existing wrapper. They verify our integration, not production hub
access or a paid provider account. One upstream Starlette test-client deprecation
warning remains. Remote CI has not run because this work has not been pushed.

## Practical limits

Archive is reversible; permanent deletion and retention policies are separate
product decisions. Kernel variables still reset when the server or kernel stops;
saved source and prior outputs persist. The digest cache assumes ordinary local
filesystem metadata semantics and is not a defense against a malicious host.

Library installation, dataset-specific provider policy, disclosure accounting
across repeated queries and TRE submission approval remain the platform follow-up
work described in [the implementation plan](workbench-implementation.md). These
fixes do not expand the catalogue into statistically reviewed inferential methods.
