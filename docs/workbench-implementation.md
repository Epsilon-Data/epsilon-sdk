# Local research workbench implementation

Branch: `feat/local-research-workbench`, based on `feat/chainlit-chat` at `c88e321`.

## Accepted product decisions

- `epsilon start` opens our own local Epsilon interface.
- **Use legacy Epsilon credential sign-in.** The local UI accepts the same username and password as `epsilon login` and shares its saved access token. Keep the local launch capability separate. The authorization-code/PKCE implementation is retained for a future rollout; see [localhost SSO](localhost-sso.md) for its configuration and historical verification.
- **Choose an approved dataset before creating a project.** The homepage shows the account's approved dataset list, followed by existing local projects under Continue work. Selecting a dataset opens the name/folder form; confirmation creates and initializes that local project using the shared `epsilon init` service. Dataset and project counts remain distinct. See [dataset setup](dataset-setup.md).
- Keep dataset authentication and the researcher's AI provider configuration separate. Passwords are used for authentication only; API keys and access tokens are never returned to frontend storage.
- Project management, initialisation, available analyses, conversations, code, saved results and notebook editing belong to the Epsilon interface.
- Keep the overview brief: predefined example analyses with visible field bindings, one question box, and recent work. Examples show local charts and code before an explicit copy creates a notebook. Use the existing Epsilon frontend's charcoal, blue and grey palette. See [example analyses](example-analyses.md) for the current onboarding flow; starter notes below describe the earlier iteration and retained template API.
- One workspace offers **Assistant / Both / Notebook** modes and resizable panes. Chat prepares code cards; the researcher chooses **Add to notebook**, or explicitly **Update cell N** for a refinement. Execution is separate and applied changes can be undone.
- Preserve the Chainlit path as a legacy launch option during migration. (Done: it has since been removed; its history remains importable from `chat.db`.)

## Implementation sequence

1. **Shared credentials and project setup.** Extract noninteractive authentication and initialisation services. Both CLI and browser call them. Preserve CSV/schema/version verification and make setup failure recoverable without overwriting existing research files.
2. **Authenticated local APIs.** Single-use launch bootstrap, local session and CSRF/host/origin checks. Every research route carries a project ID. Resolve registered directories explicitly, without changing process working directory or relying on a global active project.
3. **Owned frontend.** Package the interface assets in the Python wheel. Implement credentials sign-in, project creation, authorised dataset choice, setup progress, schema/capabilities, model settings and real error/empty/loading states. No demo fixtures or registration controls in the product UI.
4. **Guided research and durable work.** Immediate catalogue suggestions, optional model phrasing, validated plans, controlled synthetic previews and code generation. Store project-scoped conversations, code and chart/table artifacts in SQLite so results survive reload and resume. Keep audit records separate.
5. **Code and notebook workspace.** Durable editable source and notebook export. Optional isolated execution must have explicit lifecycle, cancellation and resource/network/filesystem controls; never silently fall back to executing arbitrary user/model Python on the host.
6. **Checks, packaging and validation.** Surface SDK code checks and reproducible export. Exercise CLI compatibility, credentials handling, project isolation, plan validation, path restrictions, output handling, browser flows and wheel asset inclusion. Document any environmental prerequisites for optional runtime execution.

## Safety contract for this branch

- A localhost interface is not an identity boundary. Unlock the browser through the CLI launch capability, then require the local session for project APIs and CSRF protection for mutations.
- Reuse the configured Epsilon API endpoint; do not let model output choose credential destinations.
- Store the access token in the existing credentials file with restricted permissions and atomic replacement. Never persist the account password.
- The deterministic catalogue decides feasibility. Validate field bindings again before generating or running an analysis; model-proposed titles and code do not grant capability.
- Model context uses explicit schema metadata and bounded, reviewed tool results. Do not offer arbitrary filesystem reads, raw rows, credentials, shell commands or unrestricted stdout to the model.
- Synthetic preview execution must use a controlled implementation. A generated module on disk is editable and therefore cannot be treated as a trusted template merely because of its filename.
- Charts, tables, exports and model summaries share the same checked artifact. Withheld values are absent from frontend payloads. A local preview is not TRE output approval.
- Notebook isolation protects the host; it does not itself authorise disclosure of arbitrary outputs. Keep unreviewed notebook output local and out of model context and reviewed result artifacts.

## Acceptance criteria

- A valid `epsilon login` is recognised by the web app. The local sign-in form uses the same credential service and clears the password after each attempt. Invalid/expired credentials have usable recovery. No sign-up control appears in the SDK UI.
- A researcher can create a project, select a real authorised dataset and initialise it without another CLI command. Failed downloads leave no accepted partial project.
- Two project tabs cannot cross conversations, data, artifacts or execution jobs.
- Catalogue cards render without waiting for a model. Unsupported or forged analyses cannot run.
- A supported synthetic preview produces an artifact containing the actual result, reproducible code and provenance. Reopening the thread restores the chart without another model call.
- Chat can assist with methods and code through constrained tools. Provider failures do not erase history or prevent deterministic workflows.
- Assistant and notebook share a persistent conversation. Switching views preserves unsaved source. Preparing a code suggestion does not change the notebook. Explicit updates may replace unchanged AI cells or a failed cell explicitly shared for repair; concurrent manual edits must survive. New charts default to new cells.
- Notebook edits and exports persist; optional execution reports its actual readiness and never substitutes simulated results.
- Clean installation includes the web assets and optional dependencies are explicit. Existing CLI tests remain meaningful.

## Validation record

Verified on macOS with Python 3.11 on 8 September 2026. The subsequent browser SSO
iteration passed **771 Python tests**, **19 JavaScript tests** and **15 browser
SSO checks**; see [the SSO verification and deployment status](localhost-sso.md).
The review-fix record below describes the preceding iteration. This document supersedes
the prototype's proposed registration/PKCE flow. The [review fix record](workbench-review-fixes.md)
maps the reported operational and UX issues to their implementation and evidence.

- **736 Python tests passed** with `EPSILON_TEST_NOTEBOOK=1 .venv/bin/python -m pytest tests -q --tb=short`. This includes both local-server smoke tests, actual Docker/Jupyter execution, credential and request boundaries, temporary starters, concurrent edits/output, audit consistency, runtime caching and session recovery.
- **19 JavaScript tests passed** with `npm test`; ESLint and formatting checks passed. CI runs the module lint and interaction regressions.
- **39 browser checks passed** across two review runs: 27 starter/interaction checks and 12 repair/concurrency/result/reconnection checks. The runs cover generated-wrapper pandas starters, no durable work on opening, real execution, explicit model suggestions, visible field bindings, duplicate actions, benign saves, stable output DOM, archive/restore, mobile keyboard controls, reviewed repairs, completed output after a save race, local result tabs and connection recovery. There were no browser runtime exceptions.
- Earlier browser runs covered code placement, libraries, rich MIME output, setup, provider failures and shared workspace layouts. They remain historical evidence; the 28-check starter run and screenshots 28–30 predate temporary pandas drafts and are superseded for that flow.
- Browser verification uses an isolated synthetic dataset, fixture Epsilon authentication/download responses and scripted model responses through the existing AI wrapper. The server, store and Docker/Jupyter execution are real. These checks do not certify production hub access or a paid model account.
- The real notebook tests cover persistent variables, PNG figures, pandas HTML, Markdown/JSON, output ordering, display handles, non-root configuration, read-only projection, no external network access or inherited host model key, stop and fresh restart. Remote/TCP Docker contexts are rejected.
- Wheel and sdist builds passed. Isolated wheel imports verify every native UI module, the new backend modules, runtime sources, optional dependencies, Python >=3.9 metadata, local browser bootstrap and project APIs. No Chainlit import occurs; tests are excluded from the wheel.
- CI installs the SDK in its Python 3.9–3.12 matrix. A separate Linux job builds and tests the notebook runtime. These workflow changes are local; remote CI awaits a push/PR.
- One upstream Starlette test-client deprecation warning remains in this development environment.

## What ships in this branch

| Layer | Implementation | Responsibility |
| --- | --- | --- |
| CLI and shared services | `sdk/epsilon_cli.py`, `sdk/credentials.py`, `sdk/project_setup.py` | Existing credential authentication, staged initialisation, owned launch and optional runtime build |
| Local server boundary | `sdk/workbench/server.py`, `api.py`, `middleware.py`, `security.py`, `errors.py` | Loopback binding, one-use launch token, HttpOnly session, CSRF, host/origin checks, bounded input, explicit project routing |
| Research state | `service.py`, `store.py`, `jobs.py` | Project registry, SQLite conversations/artifacts/notebooks, revisions, background tasks, progress and cancellation |
| Analysis contract | `analysis.py`, `starters.py`, existing `sdk/catalogue.py` | Revalidated feasibility and fields; temporary pandas notebooks; separate controlled counts, suppression and provenance |
| AI wrapper integration | `assistant.py`, existing `sdk/llm` | Permitted schema/source context, checked plan proposals and unexecuted code suggestions with explicit placement |
| AI usage and model choice | `sdk/llm/pricing.py`, `Metered` in `sdk/llm/base.py`, `usage` table in `store.py`, `usage.js` | Tokens from the provider's own usage report per request, including failed and retried attempts; totals per conversation (workspace), project and computer; estimated cost from list prices or the researcher's own rates, never guessed for an unknown model or an institution endpoint; model switched from the chat or Settings without re-entering the key |
| Column grounding | `sdk/workbench/fields.py`, `resolve_fields` tool and confirmation gate in `assistant.py` | Local, deterministic matching of the researcher's words to real schema paths; the model cannot prepare a plan or code while a term is unconfirmed; suggestion buttons are built from the matcher, not model text; a confirmed word is remembered per project and can be removed from Research goal |
| Notebook execution | `kernel.py`, `libraries.py`, `display.py`, `runtime/` | Persistent isolated Jupyter kernel, actual package inventory, bounded and sanitised MIME displays, explicit shutdown |
| Owned interface | `sdk/static/workbench/` | Real project URLs, setup, research chat, results, notebook and settings |

The interface is packaged HTML/CSS/JavaScript using native ES modules with explicit imports and no frontend build dependency. Shared interactions and connection recovery live in dedicated modules. Optional development tools use `npm ci`, `npm run lint`, `npm test` and `npm run format`. This gives Epsilon ownership of the interface and API now. The project-scoped APIs and stored artifacts do not depend on Chainlit or the frontend framework; a later component-based frontend can reuse them without migrating research history.

The interface follows `frontend/tailwind.config.js` and `frontend/src/styles/GlobalStyle.ts` in the sibling Epsilon frontend: `#202020` header, `#3B3B3B` sidebar, `#1481F1` to `#014FE9` primary blue, `#F5F5F5` surfaces and `#E6E6E6` borders. Charts use the same blue palette. Dataset policy details remain available in Data, Privacy and expandable method details.

Assistant and Notebook URLs open the same workspace, linked by project, conversation and notebook IDs. A source-only three-way merge preserves unsaved local edits when a server update arrives. The model's `prepare_notebook_cell` tool stores code cards attached to the assistant response. Standard fenced Python also becomes a card; older direct-write history remains accessible through Open cell. Pending suggestions do not change source or execute anything.

The researcher chooses Add to notebook for new code, or Update cell N / Add as new cell for a refinement. Placement revalidates stored source and atomically records the notebook revision and applied draft; a retried request returns the original change. Replacement requires the target digest captured in permitted context. If a researcher edits or removes that target, placement appends separately. Undo checks the current source and change ID before restoring or removing a cell and makes the suggestion available again. It cannot overwrite a subsequent manual edit. No model tool runs notebook code.

The overview and History use a project-scoped recent-work index, grouping related conversations, notebooks and previews. Merely opening an empty notebook or an untouched starter does not create a recent-work entry. History can archive and restore conversations and notebooks without deleting their source or output. Continue work and the Workspace navigation reopen the latest actual work. Data shows searchable readable field names/types, with the literal dotted names available to copy. Unavailable methods and dataset policy/version details remain expandable. Pane widths and view preferences survive reload; chat follows new messages only when the researcher is already near the end.

Automatic notebook context contains IDs and kinds, plus bounded source from unchanged AI-written cells whose provenance is validated against persisted changes. Up to three pending code suggestions from the same conversation and notebook are also included so follow-ups can refer to code awaiting placement. Manual source, edited AI source, outputs and undo snapshots remain outside that context. Questions and previously shared source still travel through the configured provider, so researchers must follow the dataset's metadata and free-text sharing policy.

### Ask, review, run and fix iteration

- **One notebook pane.** Workspace retains Assistant / Both / Notebook modes and no longer embeds a Saved results tab. Preview completion leaves the notebook visible and adds a link to `/projects/<id>/analyses/<artifact>`. Older `?artifact=` conversation links resolve to that Results page. Saved artifacts remain immutable; arbitrary notebook output is not promoted to a reviewed artifact.
- **Temporary, readable starters.** Clicking a catalogue or tailored card validates its displayed method/fields and opens a temporary notebook with `layout=both`. Short pandas cells load the generated dataset wrapper when available, with a CSV fallback. Opening the draft creates no conversation, plan or saved notebook. Editing, saving, running, exporting or continuing in chat persists it. The notebook provides its execution controls; the controlled count engine is separately available in Results through New preview / Run preview. Model-tailored ideas are requested only through Ask AI for ideas, and their questions remain visible.
- **Static code feedback.** `code_checks.py` checks explicit imports against the captured runtime inventory and follows simple pandas reads/aliases to detect unknown literal field names. It recognises newly assigned columns and avoids claiming columns are invalid for unrelated or dynamically constructed frames. Unknown third-party modules are reported as unverified, rather than necessarily missing. Tool responses and chat cards expose the findings. The checks do not execute source, guarantee package API compatibility, or certify statistical/disclosure correctness.
- **Explicit repair sharing.** A failed cell offers Fix with AI. The preview contains that cell, a fixed allowlisted error category/description and the configured model destination. Credential-bearing source is rejected. Confirmation is bound to the project, notebook revision, source digest, diagnostic and connection; changed context requires another review. The approved provider instance is captured before the request is queued. No raw traceback, displayed values, other notebook cells or earlier conversation enters a repair request.
- **Controlled placement and sharing scope.** Repairs return normal code cards with a current/proposed code comparison, Add, Update and Undo. Stored target digests preserve edits made during a model request. When the researcher shares manual or edited source, the resulting messages, pending drafts and applied cells are excluded from subsequent automatic context. This explicit sharing does not replace dataset-owner permission; dataset-specific institutional egress enforcement remains future platform work.
- **Output freshness and concurrent edits.** Editing/reordering Python cells, rerunning earlier cells and explicitly restarting a notebook conservatively marks affected prior outputs Needs rerun, without rebuilding their rich DOM on every keystroke. Completed runs attach atomically to matching cell source; newer source is preserved and the executed source/output remains available in paginated Run history. This uses execution order, not complete dependency analysis; automatic server/kernel restarts and dynamic state still require a fresh full run when reproducibility matters.

The controlled preview engine currently counts synthetic records for four methods: dataset description, composition by group, cross-tabulation and coarse trends. It does **not** compute chi-square tests, p-values, prevalence, logistic regression or survival models. Numeric descriptions use bands. Counts are bounded to one million records, 100 descriptive fields and 30 displayed groups per table; input files are limited to 256 MB each. Charts use the same saved payload as tables; a hidden group's label and value never enter that payload.

Notebook execution uses a local Docker daemon, no host Python fallback, no published ports, no container network, a read-only root and projection snapshot, dropped capabilities, a non-root UID, and CPU/memory/PID limits. Jupyter state survives consecutive cells within a running session. Source and output persist separately; kernel variables do not survive stopping the server. Source-only notebook exports omit outputs. These controls follow Docker's [container execution options](https://docs.docker.com/engine/containers/run/) and Jupyter's [execution/message protocol](https://jupyter-client.readthedocs.io/en/stable/messaging.html).

The managed runtime requirements include NumPy, pandas, Matplotlib, Seaborn, SciPy and statsmodels. Seaborn's [installation documentation](https://seaborn.pydata.org/installing.html) identifies SciPy and statsmodels as optional dependencies for some advanced charts. A fixed, bounded metadata probe runs without network access, project mounts or user code and caches installed versions by immutable image ID. Settings displays the results. The assistant receives only package names/imports/versions and readiness, separate from research output. A running kernel retains its captured inventory if the tagged image changes; the UI offers Restart notebook to adopt the new environment. Source and prior output are preserved, while variables reset.

An explicit project requirements file can extend the local image:
`epsilon notebook-build --requirements notebook-requirements.txt`. The CLI accepts
package names with version constraints and rejects URLs, local paths, VCS sources
and installer options. Installation occurs only during this researcher-initiated
Docker build; notebook code and model tools cannot install packages or use the
network. Custom packages still need coordinator/runtime approval before a TRE
submission, and the model's verified inventory remains limited to the managed
packages until the runtime probe is extended.

The prompt instructs the model to use verified installed libraries and avoid notebook package downloads; it can still generate invalid code. Missing imports retain their local traceback and show a link to notebook library settings. Adding an unbundled library currently requires updating `runtime/requirements.txt` and rebuilding. A researcher-facing Add library flow with project dependency locks remains future work; there is no implicit or model-triggered package installation.

Notebook displays preserve MIME output ordering, execution counts, clear-output behaviour and display-handle updates within the same kernel session. The host rebuilds HTML from an inert allowlist, strips URLs, styles and event handlers, and validates bounded PNG images before persistence or rendering. Markdown is parsed with raw HTML disabled and then sanitised. Arbitrary JavaScript, SVG, external resources and interactive widgets are not executed. Notebook outputs remain unreviewed and are never promoted into model context or saved analysis artifacts.

The shared chart renderer supports bar, pie and ordered numeric/time line charts. Axis semantics come from the literal analysis specification; no code is executed to discover them. Line paths preserve absent intervals without filling zeroes or drawing through suppression gaps. Existing notebook JSON previews are recognised at display time, so their source, values, fingerprints and prior artifacts remain unchanged.

Model configuration reuses the existing provider wrapper. A workspace override stores nonsecret settings in SQLite and holds a key in memory or the OS keyring. An old key is not reused for a changed endpoint. Model tools have no raw-file, shell, network or execution capability. Legacy imported text is shown locally and excluded from automatic model history because it may contain observations generated under the earlier policy.

Settings includes a connection check using a fixed prompt and the tool definitions, without project metadata, conversation text or notebook source. It never executes returned tool calls. Provider exceptions expose a fixed public message selected by structured error category; raw HTTP bodies are not sent to the browser or history. Credit exhaustion, spending limits and quota failures are distinguished from temporary rate limits and are not automatically retried. This follows OpenAI's [documented error-code distinctions](https://developers.openai.com/api/docs/guides/error-codes). The header links to **AI settings** when configured, without claiming a verified connection.

## Review the interface

The review fixes are shown in these current fixture screenshots:

- [Readable temporary notebook](workbench/previews/31-readable-notebook-draft.png)
- [Executed pandas notebook](workbench/previews/32-readable-notebook-output.png)
- [Clean starters on mobile](workbench/previews/33-clean-starters-mobile.png)
- [Separate controlled preview results](workbench/previews/34-controlled-preview-results.png)

The following screenshots document earlier implementation stages:

- [Overview with Continue work](workbench/previews/15-resume-work-overview.png)
- [Searchable fields and expandable data rules](workbench/previews/16-searchable-data.png)
- [Review code before updating or adding a cell](workbench/previews/17-review-notebook-code.png)
- [Code workspace on mobile](workbench/previews/18-mobile-code-workspace.png)
- [Installed notebook libraries](workbench/previews/19-notebook-libraries.png)
- [Seaborn heatmap in the shared workspace](workbench/previews/20-seaborn-heatmap.png)
- [Notebook execution keeps fresh cell output visible](workbench/previews/21-notebook-run-stays-in-notebook.png)

Screenshots from the previous shared-workspace iteration:

- [Simplified overview in Epsilon colors](workbench/previews/10-simple-overview.png)
- [Assistant and notebook side by side](workbench/previews/11-assistant-notebook.png)
- [Notebook-only mode](workbench/previews/12-notebook-only.png)
- [Shared workspace on mobile](workbench/previews/13-mobile-workspace.png)
- [Connection check and specific account error](workbench/previews/14-connection-check.png)

Earlier screenshots document the preceding layout and rich-output implementation:

- [Credentials sign-in](workbench/previews/01-signin.png)
- [Project overview](workbench/previews/02-overview.png)
- [Assistant and saved chart](workbench/previews/03-assistant.png)
- [Notebook with real Python output](workbench/previews/04-notebook.png)
- [Notebook preview with an ordered line chart](workbench/previews/07-notebook-preview.png)
- [Notebook with pandas, Markdown and JSON](workbench/previews/08-notebook-rich-output.png)
- [Rich notebook on mobile](workbench/previews/09-notebook-rich-mobile.png)
- [Model settings](workbench/previews/05-settings.png)
- [Mobile overview](workbench/previews/06-mobile.png)

Earlier repair and starter iteration screenshots (28–30 are superseded above):

- [Review the cell and diagnostic before sharing](workbench/previews/22-review-cell-repair.png)
- [Review the proposed fix](workbench/previews/23-proposed-cell-fix.png)
- [Code-check feedback](workbench/previews/24-code-check-feedback.png)
- [Saved previews on the Results page](workbench/previews/25-separate-saved-results.png)
- [Assistant and live notebook](workbench/previews/26-clean-notebook-workspace.png)
- [Mobile workspace](workbench/previews/27-clean-workspace-mobile.png)
- [Starting point opens analysis code](workbench/previews/28-starter-loads-analysis-code.png)
- [Starting point produces notebook output](workbench/previews/29-starter-notebook-output.png)
- [Starting point on mobile](workbench/previews/30-starter-mobile.png)

## Run from this branch

Use Python 3.9 or newer for the workbench. Install into the environment that owns the `epsilon` executable, including a template project's separate virtual environment if applicable:

```bash
pip install -e '/absolute/path/to/sdk-epsilon'
epsilon start
```

Enter your Epsilon credentials in the local sign-in form, or reuse an earlier `epsilon login`. To run editable notebook cells, start a local Docker daemon and run `epsilon notebook-build`. The notebook image contains Python 3.11, Jupyter and the scientific libraries listed above; dependencies are installed during image build and the image digest is recorded with execution output. Rebuild after changing the managed requirements, then restart running notebooks from their options menu.

## Rollout and remaining platform work

1. **Review and pilot this branch.** Exercise the existing hub login, dataset entitlements, download/version headers and approved model endpoints in Epsilon's staging environment with real institutional accounts. Confirm metadata sharing rules with the relevant dataset owner. The browser and provider fixtures validate our code paths; they do not certify a deployed hub configuration.
   **Dependency management follow-up:** add a researcher-controlled Libraries → Add library flow, project-specific dependency declarations and locks, isolated image rebuilds, and an explicit restart action. The model may propose a dependency; package installation requires a separate researcher action and the configured package-source policy.
2. **Institutional policy and governed submissions.** Add dataset-specific provider/metadata policy enforcement, approved tool and package policies, disclosure accounting across repeated queries and a coordinator-backed review/submission API. The current review ZIP contains source and provenance and is deliberately not a deployment bundle. User-edited code remains unreviewed even when it ran in an isolated notebook.
3. **Expand reviewed analysis methods.** Add statistically reviewed implementations, explicit assumptions and end-to-end output tests before enabling inference or entity-level methods. The catalogue remains authoritative; model phrasing cannot supply missing entity keys, event definitions or denominators.
4. **Merge and release after review.** Choose the version and rollout policy, run staging acceptance, then merge/release with the template-environment installation instructions. No merge, push or PyPI publication has been performed as part of this implementation.

This is a single-researcher local workbench. It does not provide multi-user hosting, tenant RBAC, an institutional egress gateway or TRE output approval. Credential patterns cannot identify every confidential fact pasted into a research question. The UI and documentation make the cloud-provider context boundary visible; those institutional controls belong in the next integration stage.
