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

Four commands help you choose and write an analysis that will actually clear
output review. All of them read the **dataset card** — the data owner's
description of what a row means, what each field contains, and which traps the
dataset carries. `epsilon init` downloads it to `generated/card.json`.

```bash
epsilon explain                       # what this dataset can and cannot answer
epsilon suggest                       # every analysis available, and what is not
epsilon suggest "<your question>"     # route one question to a catalogue entry
epsilon snippet <analysis>            # generate starter code under analyses/
epsilon check                         # run the submission rules locally
```

### Feasibility is decided in code, not by a model

`epsilon suggest` answers from the card using ordinary Python predicates. A
model, if you configure one, only maps your question onto a catalogue entry and
phrases the reply — it cannot overturn a verdict. So the answers are
reproducible, and **every command above works with no API key at all.**

The refusals are the useful part. On an archetype with no key back to the
patient, asking for prevalence gets you:

```
[NO] Prevalence
     why not: Prevalence is a per-entity quantity, and this archetype has no
       key that groups rows back to an entity (identifiers are stripped at
       projection). Computing it anyway yields a figure weighted by row count.
     unlock: Ask the data owner for a pseudonymised entity key ...
```

That analysis would otherwise run cleanly, pass the submission gate and come
back attested — and be wrong.

### Generated code carries the rules

Snippets are fixed templates parameterised from the card, so the suppression
threshold, the stated unit of analysis and the absence of per-record output are
structural rather than advisory. They also pass `epsilon check`, which runs the
same static rules the coordinator applies: no raw records released, no network,
no subprocesses, dependencies pinned, no credentials in the packaged tree.
`epsilon build` runs those checks before packaging.

### Configuring a model (optional)

Bring your own key. Calls go from your machine straight to the endpoint;
Epsilon never sees your prompts.

```bash
epsilon ai login      # stores settings in ~/.epsilon_sdk/config.ini,
                      # key in your OS keyring (pip install 'epsilon-sdk[copilot]')
epsilon ai status     # which model, and where its key came from
epsilon ai logout
```

Key resolution: `EPSILON_LLM_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`,
then the OS keyring, then the config file. Two providers are supported —
`anthropic`, and `openai-compatible` for anything speaking
`/v1/chat/completions` (vLLM, Ollama, llama.cpp, TGI, Together, Groq,
OpenRouter). Set `base_url` for a self-hosted endpoint.

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