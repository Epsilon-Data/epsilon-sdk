# Epsilon SDK - CLI Commands

## Quick Start

```bash
# 0. Install SDK
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

Opens a browser on `127.0.0.1:7878` with three tabs.

**Set up** walks the five commands, detecting each from the machine rather than
remembering it -- run one in a terminal, reload, and it ticks. Every command has
a copy button.

**Dataset** shows what you actually have: what one row is, the columns that
reached this machine against what was stripped at projection, every column as
measured, and the feasibility verdicts at a glance. Generate, run and check are
buttons.

**Assistant** is where the model lives. It reads the measured dataset, checks
what is computable, writes code and runs it -- and cannot overrule a verdict,
read a record, or leave the project directory. There is no terminal chat; the
assistant is UI-only.

`epsilon start` works before `epsilon init`, because guiding set-up is half its
job. Only the Assistant tab needs a model.

It serves on loopback and runs beside your project, so the data and your key
never leave the machine. Standard library only -- no node toolchain.

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
                      # key in your OS keyring (pip install 'epsilon-sdk[copilot]')
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