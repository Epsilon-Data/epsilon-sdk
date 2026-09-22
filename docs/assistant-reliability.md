# Assistant reliability

The workbench keeps questions recoverable, makes shared notebook context explicit,
and checks generated code before offering it for placement. Existing CLI commands,
production API configuration and legacy Epsilon credential sign-in are preserved.

## Researcher workflow

1. Ask a question. The conversation shows progress while the assistant prepares
   its response. If the request fails, its error and **Retry** remain beside the
   question after reopening the conversation. Configuration and billing errors
   also offer **AI settings**.
2. For your own code, choose **Use with AI** on the cell, inspect the source and
   destination, then choose **Use for my next question**. The composer identifies
   the selected cell. You can remove it; editing it requires another review.
3. Review the returned code. **Add to notebook** creates a cell; **Update cell**
   compares and replaces the selected version when it still matches. **Add as
   new cell** keeps both versions. **Undo** remains available for an unchanged
   applied suggestion. Run the cell separately.
4. Optionally save a **Research goal** and field names for this project. A saved
   goal is included in ordinary questions and shown in the composer. Clear the
   form and save to remove it. Keep confidential data values out of this text.

If a launch link is expired or spent, rerun `epsilon start`. For a current running
workbench this issues a fresh one-use, ten-minute link without restarting its
kernels. Old servers that predate this capability still need one restart.

## Request recovery

New projects offer a local **Run your first analysis** guide. It highlights the
example, copy, Run all and assistant controls in sequence. Progress is stored in
browser storage per project only; pausing or skipping never sends metadata to a
provider. **Help & guide** reopens it later.

Requests have stable identifiers and persist in the local workbench SQLite
database. Duplicate submissions reuse the accepted request. User and assistant
messages are unique per request and role. An explicit retry keeps the original
question, reuses identical prepared code and plans, and records another attempt.
A retry may generate a different suggestion, which still needs review and explicit
placement. It does not rerun notebook code.

Only the latest question in a conversation can be retried, preserving message
order. A failed earlier question can be asked again as a new question. Selected
cell and repair retries require a fresh source/destination review; the server
does not silently replay stored private source.

Transient timeout, connection, rate-limit and service-unavailable failures get up
to three attempts per provider call with short backoff. The model/tool loop has a
120-second budget and a maximum of eight rounds. Each provider request has a
bounded timeout. Authentication, permissions, credit and quota errors require
researcher action and are not retried automatically. Cancellation is cooperative:
a provider call already in flight must return or time out before processing stops.

An interrupted process leaves a visible interrupted request; restart does not
resume model calls or execution automatically. Ownership and attempt checks keep
an old worker from overwriting a newer retry. Cancellation and status are shared
through SQLite if multiple local servers use the same state directory. Completed
notebook output remains in its run records rather than being copied into job logs.

## Context and checks

**Use with AI** first shows the chosen cell and model destination. **Explain this
cell** sends a plain-language explanation question with that reviewed cell and
opens the assistant beside the notebook. **Ask my own question** only attaches the
cell; the composer explicitly prompts the researcher to type and send a question.
The review can also include up to eight explicitly checked Python helper cells.
Epsilon revalidates every selected source and digest together; unselected cells
and outputs remain excluded. Repair requests continue to share one failed cell.
The explanation action preserves existing composer drafts and shares no additional
cells to resolve dependencies. Missing helper definitions are called out in the
question. Both actions keep the same source/destination validation and retry rules.

Ordinary requests may include questions, permitted schema, saved research goals,
pending AI suggestions and unchanged AI-written cells. A selected-cell request
instead includes the current question, reviewed cell, permitted schema/capabilities
and notebook package inventory. Earlier conversation, other cells and notebook
outputs are excluded. The selected source and code derived from it are excluded
from subsequent automatic context. Provider settings and source digests are
checked again before queuing the request.

Static feedback covers Python syntax, explicit imports and detectable CSV column
references. The assistant can attempt two corrections. Syntactically valid code
with unresolved field or library warnings can still be shown as needing attention;
an unanswered correction request is a failed task rather than a claim of success.
Checks do not execute generated Python, prove statistical validity or identify all
dynamic imports and column references.

The `prepare_notebook_analysis` tool requires explicit field bindings and uses the
same readable pandas templates as notebook starters. It supports count distributions,
group comparisons, cross-tabulations and date counts, using generated dataset
models when present. Bar, pie and ordered line charts share local suppression
steps. Withheld groups and labels are excluded; pie percentages are omitted when
groups are hidden; missing or withheld ordered intervals break lines. These local
templates do not provide repeated-query inference protection or TRE output approval.
Custom code remains a reviewable draft and runs only in the isolated notebook.

The launch-refresh control is separate from account login and browser sessions.
It is stored in an owner-only file under `~/.epsilon_sdk/servers/`, never exposed
to JavaScript. The loopback API validates that capability and continues to check
host and origin. Existing unlocked browser sessions remain valid.

## Evaluations

Inspect the 30 scenarios without a provider call:

```bash
python -m evaluation.assistant --list
```

The cases cover numeric line plots without dates, time gaps, pie and bar charts,
group comparisons, custom visualisations, explanations and disallowed requests.
Each case uses a fresh temporary project with fabricated records, a compiled
generated wrapper and private workspace state. No registered project, production
dataset or Epsilon API endpoint is opened.

Run selected cases through your configured model and the actual notebook API:

```bash
python -m evaluation.assistant --live \
  --cases age-bar,gender-pie,age-no-dates,year-line \
  --execute --output /tmp/epsilon-assistant-evaluation.json
```

`--live` is required and incurs normal provider charges. The runner reads only
saved AI connection settings from `~/.epsilon_sdk/workbench.db`, or the file passed
with `--settings-db`, and uses the existing credential source. An in-memory-only
key from another server is unavailable to the runner. `--execute` requires the
managed local Docker image; it applies and executes drafts only in disposable
evaluation notebooks. Omit `--cases` for all scenarios, or use `--runs 3` for
multiple trials. Reports contain task outcomes and timings, never credentials or
notebook output.

The automated checks measure request completion, unchanged source before review,
static feedback, requested field references, runtime errors and figure rendering.
No-code scenarios must leave neither code drafts nor analysis plans. Reports also
record advisory response-quality signals for boundary language and strong finding
claims. These are technical checks, not a semantic or statistical grader: a
rendered figure can still use a poor method, and a prose response can still need
expert review.
The suite does not certify disclosure safety or reproducibility of an arbitrary
analysis.

Offline regressions cover request deduplication, retries/restarts, ownership races,
explicit sharing, source/provider changes and bounded code correction. The optional
real-runtime template test inspects figures for withheld labels, pie percentages
and gaps in time-series lines:

```bash
python -m pytest tests/test_assistant_recovery.py tests/test_assistant_evaluations.py
EPSILON_TEST_NOTEBOOK=1 python -m pytest tests/test_assistant_evaluations.py
npm test
```

The notebook-to-`epsilon build` bridge is a separate follow-up. This change does
not turn a running notebook into a TRE submission; the existing CLI build workflow
continues to use its configured Python entry point.

## Verification on 10 September 2026

- All 823 Python tests passed with `EPSILON_TEST_NOTEBOOK=1`, including the server
  smoke tests and real Docker/Jupyter execution. All 38 Node tests and UI lint passed.
- A real Chromium run verified a failed question after reload, duplicate retry
  prevention, selected-source review, exclusion of other cells, explicit cell
  replacement, saved research goals and the mobile layout.
- Eight distinct live tasks were checked with the configured `openai` / `gpt-4o`
  connection on fabricated projects: four chart tasks and four disallowed-request
  cases. An initial pie-chart run selected the wrong field. Requiring explicit
  template bindings fixed that failure, and its repeat passed. The remaining
  22 scenarios have not yet been run against the live provider. These selected
  checks do not establish a general success rate or disclosure guarantee.
- Repeating `epsilon start --no-browser` issued a different launch link for the
  running production-configured local workspace without stopping its server.
