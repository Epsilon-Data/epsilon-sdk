# Epsilon SDK - CLI Commands

## Quick Start

```bash
# 0. Install SDK (includes the browser workspace and its AI assistant)
pip install epsilon-sdk

# 1. Login to Epsilon
epsilon login

# 2. View available datasets
epsilon datasets

# 3. Initialize project with a dataset
epsilon init <dataset_id>

# 4. Write your analysis in main.py
# (Edit the generated main.py file)

# 5. Test locally with the downloaded synthetic data
epsilon run

# 6. Build for server deployment
epsilon build
```

## Project Workflow

The Epsilon SDK uses a **project-based workflow**:

### 1. Project Structure
After `epsilon init`, you get a clean project structure:
```
your-project/
├── main.py              #  Your analysis script
├── project.yml          #  Project configuration
├── generated/           #  SDK files (auto-generated)
│   ├── archetype.json   #  Dataset schema
│   ├── models.py        #  Python data models
│   └── data.csv         #  Synthetic dataset (for local testing)
└── .gitignore          # Git configuration
```

By default, `epsilon init` downloads the synthetic dataset attached to the
dataset and verifies that its columns and schema hash match the archetype.
The dataset version and schema hash it was verified against are pinned in
`project.yml` (`dataset_version`, `schema_hash`).

To generate random dummy data locally instead (e.g. when no synthetic
dataset is attached), use:

```bash
epsilon init <dataset_id> --dummy-data
```

### 2. Development Flow
1. **`epsilon init <dataset_id>`** - Sets up complete project
2. **Edit `main.py`** - Write your data analysis
3. **`epsilon run`** - Test locally with the synthetic data
4. **`epsilon build`** - Package for server deployment

### 3. Example Analysis
```python
# main.py
from generated.models import create_dataset

def main():
    # Load the dataset
    dataset = create_dataset()
    print(f"Analyzing {len(dataset)} records")

    # Your analysis code
    for record in dataset:
        print(f"Patient {record.patient.id}: age {record.patient.age}")
        print(f"Heart rate: {record.vitals.heartrate}")

    return {"average_age": 45.2, "total_patients": len(dataset)}

if __name__ == "__main__":
    result = main()
    print(result)
```

## Research copilot

### `epsilon start` -- the workspace

```bash
epsilon start
```

On a new project, the overview includes **Run your first analysis**. This is an
interactive four-step guide: choose an example, make an editable copy, run the
notebook, and ask the assistant for a change. It highlights the actual control
for each step, stores progress only in this browser for that project, and can be
paused, skipped, or reopened from **Help & guide**. It does not make an AI call
until the researcher sends a question.

The owned Epsilon interface runs at `127.0.0.1:7878`. Install the SDK in the
Python environment used to launch it:

```bash
pip install epsilon-sdk
epsilon start
```

From a source checkout, use `pip install -e .` instead.

No environment variables are needed for normal use. `epsilon start` uses the
production API at `https://app.epsilon-data.org`, the current user's
`~/.epsilon_sdk/credentials.ini`, and the username/password sign-in form.
There is no need to set or unset `EPSILON_SSO_ISSUER` for this sign-in flow.
The server and credentials environment overrides are only needed when explicitly
connecting to a different environment, such as a developer's local platform.

Enter your Epsilon username and password in the local **Sign in** form. It uses
the same authentication service and saved access-token format as `epsilon login`.
An existing valid CLI token is recognised automatically. The SDK does not save
your password, and the UI has no account-creation form or browser sign-in redirect.
The launch URL contains a single-use browser unlock token, removed from the
address bar immediately. Use the printed link when running with `--no-browser`.
Reopening a used launch link in an unlocked browser reuses its existing session.
If the link has expired or you need another browser, run `epsilon start` again.
It prints a fresh link for the running workspace, preserving notebook kernels and
saved work. The link is valid for ten minutes and one browser unlock.
An expired 24-hour browser session renews using its existing local cookie and
CSRF token for up to seven days. After a server restart or that recovery window,
use a fresh CLI launch link; account sign-in does not unlock the local server.

The authorization-code/PKCE implementation remains available for a future browser
SSO rollout, but the UI currently uses legacy credential sign-in. Its callback
registration is not required for this form. See the
[localhost SSO implementation notes](https://github.com/Epsilon-Data/epsilon-sdk/blob/main/docs/localhost-sso.md).

For the existing local Docker platform, use `EPSILON_SERVER_URL`
and a separate `EPSILON_CREDENTIALS_PATH` as shown in the
[local Docker setup](https://github.com/Epsilon-Data/epsilon-sdk/blob/main/docs/localhost-sso.md#use-the-existing-local-docker-platform).
This keeps local development sign-in separate from your production credentials.
When a legacy access token expires, sign in again in the UI or run `epsilon login`.

After sign-in, the homepage lists the datasets approved for your Epsilon account.
Select a dataset, choose a project name and local folder, then click **Initialize
project**. Setup downloads the synthetic projection and archetype, generates the
models, and opens the project overview with example analyses. Existing local projects appear under **Continue
work**; that count is separate from the approved dataset count.

The CLI and browser share the same staged download, CSV/schema verification and
model generation service. Existing entry points are preserved, and a failed
initialisation can be retried without accepting a partial project.

New projects lead with **Start with an example**. The **Examples** library offers
up to three analyses matched to the dataset's permitted fields: measurement
distributions, category comparisons, and date trends or category distributions.
Open an example to see its question, learning outcomes, field bindings, two charts,
count tables and readable pandas code. Previews are computed locally from the
synthetic CSV using fixed grouping rules. Browsing creates no research history,
executes no notebook Python, and makes no model request.

Choose **Use this example** to create an independent notebook beside the assistant.
The original example stays unchanged. Copies load the generated dataset wrapper
when available, with a CSV fallback for older projects, and start without outputs.
Choose **Run all** to create your notebook's charts, then edit the fields/grouping
or select **Use with AI** on a cell for help. Docker is needed for running cells;
browsing previews and copying code work without it. See the
[example library and demo walkthrough](https://github.com/Epsilon-Data/epsilon-sdk/blob/main/docs/example-analyses.md).
Open **Workspace** to work with the assistant and notebook side by side.
Choose **Assistant**, **Both** or **Notebook**; the app remembers your choice, and
you can resize the two panes. **Continue work** reopens your latest conversation or
notebook, including work without a saved preview. **Data** has searchable field
names/types and copies the exact names used in code; rules and version details
remain available in an expandable section. **History** can archive and restore
conversations and notebooks without deleting their content.
AI assistance starts when you ask a question; visiting a project or browsing an
example never sends its metadata or preview counts to a model.
The server revalidates every proposed method and field binding. For a controlled
count preview, use **Results → New preview → Run preview**. Those previews
(describe, composition, cross-tabulation and trends) save charts/tables with code
and input fingerprints. Notebook output remains in the notebook. Reopening a
conversation restores its saved artifacts without another model request.

Configure your existing AI wrapper in Settings or with `epsilon ai login`.
Use **Test connection** in Settings to send a short check without project data.
The header's **AI settings** link opens the saved configuration. Errors explain
exhausted credits, account limits, rejected credentials and connection problems;
billing failures are not retried automatically.
Failed or interrupted questions keep a **Retry** action in the conversation,
including after a reload or restart. Retry reuses the question and request ID.
Temporary connection/rate-limit errors receive bounded automatic retries;
credentials and billing problems offer **AI settings**. A retry never runs code
or places a suggestion in the notebook automatically.
Questions, an explicitly saved research goal, permitted schema metadata, template source, pending AI code suggestions
and unchanged AI-written notebook cells can go to that provider. Manual notebook edits, raw rows, observed
values and notebook outputs are excluded from automatic model context. A cloud
model still receives the permitted context. Credential scanning
checks outbound sharing, without blocking local notebook saves. It helps with
accidental key pasting but cannot classify every confidential fact in free text.
Only share questions and metadata allowed by your dataset policy.

Ask the assistant to write code and it prepares a Python or Markdown card in chat.
Choose **Add to notebook** to create a new cell. For a refinement, choose
**Update cell N** or **Add as new cell** to keep both versions. Nothing changes in
the notebook until you choose; the destination cell opens after placement. Each
change has **Undo**, repeated clicks cannot duplicate it, and concurrent manual
edits are preserved in their original cell. Standard Python code fences also
become addable cards. Choose **Run** separately when ready.

Choose **Use with AI** on a notebook cell to ask about code you wrote or edited.
Review the source and model destination. **Explain this cell** sends an explanation
question immediately and opens the reply beside the notebook. **Ask my own question**
attaches the cell to the composer; type your question and send it when ready.
An explanation request preserves any question already drafted in the composer.
The reviewed cell and any helper cells explicitly checked in the review are
shared for that request; outputs, unselected cells and earlier chat are
excluded. Changed source or a changed provider requires another review.
**Research goal** remembers a short question and chosen field names for ordinary
AI conversations in this project. The composer shows when that saved goal is in use.

Code cards show static feedback about explicit imports and detectable dataset
column names. The assistant can make up to two correction attempts before
presenting code with remaining warnings. Common count charts use shared pandas
templates with explicit field bindings, small-group suppression and bar, pie or
ordered line plots. Dynamic Python and method correctness still need review and execution.
After a cell fails, choose **Fix with AI** to review the selected code, error type
and model destination before sending. The request shares one failed cell and a fixed
error description, without the raw traceback, displayed values or other cells.
The proposed fix returns as a code card with **Compare**, **Update cell**, and
**Add as new cell** choices. Manually written or edited source shared this way,
and fixes derived from it, are excluded from later automatic model context.

See [assistant reliability and evaluations](https://github.com/Epsilon-Data/epsilon-sdk/blob/main/docs/assistant-reliability.md) for
request recovery, sharing rules, and the opt-in 30-task model evaluation suite.

Workspace always shows the live notebook and its cell outputs. Saved preview
snapshots open on the separate **Results** page. Editing an earlier Python cell,
rerunning it, or restarting the notebook marks prior affected outputs
**Needs rerun** until those cells run again. This is a conservative ordering
warning, not full Python dependency tracking. A run finishing while you edit
keeps your newer source. Its output attaches to the matching cell when possible;
the executed source and output are also retained in **Notebook options → Run
history**. An interrupted job connection offers **Reconnect** without losing edits.

Notebooks support Python and Markdown cells, formatted pandas tables, expandable
JSON and inline Matplotlib figures. Shift+Enter runs a code cell or renders a
Markdown cell. Source and rich outputs persist when you reopen a notebook; the
`.ipynb` export includes code and Markdown without unreviewed outputs. To enable real
Python execution, install/start Docker and build the optional runtime once:

```bash
epsilon notebook-build
```

The managed notebook image includes pandas, Matplotlib, Seaborn, SciPy and
statsmodels. If a reviewed project needs another package, put approved package
names (one per line, with optional version constraints) in a separate
`notebook-requirements.txt` file and rebuild explicitly:

```bash
epsilon notebook-build --requirements notebook-requirements.txt
```

The SDK rejects URLs, local paths, shell options and VCS requirements. Package
installation happens only during this explicit image build; notebook cells and
the assistant cannot install packages or access the network. Restart a running
notebook after the image is rebuilt.

The managed image includes NumPy, pandas, Matplotlib, Seaborn, SciPy and
statsmodels. **Settings → Notebook setup → Python libraries** shows versions
checked inside that image. The assistant receives the active notebook's package
inventory and is instructed to use available imports, with Matplotlib as a
fallback when Seaborn is absent. This is guidance, not a guarantee that generated
code will run. An existing kernel keeps its old environment after an image
rebuild; use **Restart notebook** to pick up new libraries.

Extra libraries remain separate from the SDK's own virtual environment. The
explicit requirements file above rebuilds the local image for this project, but
the coordinator's supported package policy and target runtime must be checked
before using that code for a TRE submission. The assistant reports only the
managed inventory, so custom packages should be described in the question when
asking for code help.

Cells run through Jupyter inside a non-root container with networking disabled,
resource limits and a read-only snapshot of the selected projection. Kernel state
persists across cells until stopped or the workspace exits. Notebook output is
unreviewed local output and is kept out of model context, checked artifacts and
source-only notebook exports. The app never falls back to executing edited code
in its host process. Docker must use a **local** daemon with bind-mount access to
the SDK state directory; kernel variables themselves do not survive a restart.

Saved analysis previews display as charts and tables in the notebook, including
older previews saved as printed JSON. Bar and pie charts remain available; line
charts support ordered numeric bands and time periods. Lines break across absent
or withheld intervals. The notebook uses the calculated values without changing
the analysis source or saved preview. Custom Matplotlib line plots also display
inline. HTML output is restricted to inert formatting and tables; JavaScript,
external resources and interactive widget execution are not supported.

Conversations, artifacts and notebooks persist in `~/.epsilon_sdk/workbench.db`.
`--no-record` disables the separate decision audit log, while workspace history
still persists. History from the earlier Chainlit interface (`chat.db`) can be
imported as display-only text; existing `chat.db` and `.epsilon/chat`
transcripts are preserved. The Chainlit interface itself has been removed.

Review ZIP exports contain source and provenance. They are **not TRE deployment
or approval bundles**. Local minimum-cell and complementary suppression do not
replace the TRE's output review or inference checks across repeated queries.

See [implementation and rollout plan](https://github.com/Epsilon-Data/epsilon-sdk/blob/main/docs/workbench-implementation.md) for
architecture, acceptance checks, screenshots and the next release stages.

### The commands underneath

Four commands help you choose and write an analysis that will actually clear
output review. They read the **dataset itself** -- `epsilon init` downloads the
archetype-scoped projection, and the SDK measures it. There is nothing for a
data owner to author and nothing to keep in sync.

```bash
epsilon start                         # all of the below, in a browser
epsilon explain                       # the dataset, and every analysis it does
                                      # and does not support
epsilon explain --brief               # dataset only
epsilon snippet <analysis>            # generate starter code under analyses/
epsilon snippet cross_tab --set rows=patient.gender --set cols=admissions.type
epsilon snippet describe --chart      # also generate a chart() -> SVG
epsilon check                         # run the submission rules locally
```

Fields are chosen for you; `--set` overrides one, validated against what was
measured. The command `epsilon explain` prints is the one that reproduces it.

### What is measured, and what cannot be

Types, distinct counts, ranges, categories and null rates are counted from the
projection. Two traps are inferred: a **top-coded maximum** (a pile-up at the
largest value, which is how age is capped for de-identification) and a **code
column beside a version column**, where one concept may carry a different code
per revision. Timestamps default to aggregate-only.

The important refusal needs no measurement at all: **an archetype has no key
that groups rows back to an entity**, because identifiers are stripped at
projection. So prevalence, regression and two-group comparison are blocked on
every archetype until one grants a pseudonymised key -- a property of the
platform, not something a dataset can get wrong.

What measurement cannot see is stated rather than guessed. Dates shifted per
entity look exactly like real dates, so trend analysis warns instead of
blocking. Survival is blocked outright: an archetype grants columns, not the
knowledge of which date starts a clock and which stops it.

### Feasibility is decided in code, not by a model

`epsilon explain` answers from the card using ordinary Python predicates, and
the assistant reaches those same predicates through a tool. A model never
decides a verdict, only how to say it. So the answers are reproducible, and
**every command above works with no API key at all.**

The refusals are the useful part. On an archetype with no key back to the
patient, prevalence comes back as:

```
[NO] Prevalence
     why not: Prevalence is a per-entity quantity, and this archetype has no
       key that groups rows back to an entity (identifiers are stripped at
       projection). Computing it anyway yields a figure weighted by row count.
     unlock: Ask the data owner for a pseudonymised entity key ...
```

That analysis would otherwise run cleanly, pass the submission gate and come
back attested — and be wrong.

### Charts draw the released result, never the records

`--chart` adds a `chart()` that renders the *same suppressed aggregate*
`main()` returns. A cell below the threshold is drawn as a suppressed marker
with no length, so it cannot be read back off the axis, and the figure states
how many levels were held back.

Output is SVG from a stdlib-only helper written to `analyses/_charts.py`. Two
reasons: the enclave's requirements carry no plotting library, and an SVG is
text a reviewer -- and `epsilon check` -- can actually read, unlike a PNG.
Importing matplotlib or seaborn is a warning pointing here, not a block.

### Generated code carries the rules

Snippets are fixed templates parameterised from the card, so the suppression
threshold, the stated unit of analysis and the absence of per-record output are
structural rather than advisory. They also pass `epsilon check`, which runs the
same static rules the coordinator applies: no raw records released, no network,
no subprocesses, dependencies pinned, no credentials in the packaged tree, and
no import of a local module that `epsilon build` would not package.
`epsilon build` runs those checks before packaging, and ships `analyses/`
alongside `generated/`.

### Configuring a model (optional)

Bring your own key. Calls go from your machine straight to the endpoint;
Epsilon never sees your prompts.

```bash
epsilon ai login      # stores settings in ~/.epsilon_sdk/config.ini,
                      # key in your OS keyring
epsilon ai status     # which model, and where its key came from
epsilon ai logout
```

For OpenAI:

```bash
epsilon ai login --provider openai --model gpt-4o --tier A
```

Key resolution: `EPSILON_LLM_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`,
then the OS keyring, then the config file.

Three provider names, two backends:

| `--provider` | Endpoint | Notes |
|---|---|---|
| `anthropic` | Anthropic Messages API | default `claude-sonnet-5` |
| `openai` | `https://api.openai.com/v1` | default `gpt-4o`; no `base_url` needed |
| `openai-compatible` | your `base_url` | vLLM, Ollama, llama.cpp, TGI, Together, Groq, OpenRouter |

`openai` and `openai-compatible` are the same backend — OpenAI's API is the
format the others imitate. Newer OpenAI models renamed `max_tokens` and refuse
a custom `temperature`; rather than track a model list that goes stale, the
client adapts to whatever the endpoint rejects and remembers it for the
session.

**Never put a key in your project directory.** `epsilon build` packages the
project and ships it to the coordinator; a key in `project.yml` or a `.env` is
an exfiltrated credential. `epsilon check` scans for credential shapes and
fails the build on a hit.

Models declare a capability tier (`A`/`B`/`C`) and features refuse below the
tier they need rather than degrading quietly — a model too weak to follow the
disclosure rules would produce code that leaks records, which is a policy
incident rather than a quality problem.

## Additional Commands

- **`epsilon status`** - Check login status and server
- **`epsilon doctor`** - Check local project, credentials, Docker and notebook readiness without changing anything
- **`epsilon ai status`** - Show the configured model and where its key comes from
- **`epsilon clean`** - Remove project files to start over
- **`epsilon change-server <url>`** - Switch to different server
- **`epsilon version`** - Show SDK version

## Installation

```bash
pip install epsilon-sdk
```

PyPI: https://pypi.org/project/epsilon-sdk/

## Release (for maintainers)

```bash
git checkout main
git pull origin main
bump-my-version bump patch   # or minor/major
git push origin main --tags
```

This triggers GitHub Actions → publishes to PyPI automatically.
