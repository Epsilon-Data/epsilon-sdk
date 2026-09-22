# Account setup and notebook build review

Reviewed 8 September 2026 on `feat/local-research-workbench`. This document records current behavior, reproduced build failures, and the proposed implementation. Application behavior has not been changed by this review.

The workspace should show projects associated with the signed-in Epsilon account. A researcher with no associated projects should see **Create project** and **Open existing project**, followed by a choice of local folder. Jupyter can remain the editor and local execution environment, while a reviewed Python entry point remains the input to `epsilon build`. All existing CLI commands, including password-based `epsilon login`, remain available.

## Current project and sign-in behavior

`sdk/workbench/service.py` reads one `~/.epsilon_sdk/projects.json`. Project entries contain a name, path and identifiers, but no account association. `Workbench._register_launch()` registers a recognized launch folder immediately, and `project_list()` returns the entire registry. Signing in changes the credentials used for API calls; it does not change which local projects are visible. Project lookup also uses the global registry, so filtering cards in JavaScript would not resolve access through project URLs.

The browser already uses the same initialization implementation as the CLI:

```text
epsilon init <dataset_id> ───────────────┐
                                       ├─ initialise_project(...)
Browser → choose dataset → initialise ──┘
```

`sdk/project_setup.py` downloads the archetype and synthetic projection, validates the CSV/schema, generates the typed models, and writes `project.yml`. It creates `main.py` and `.gitignore` when absent. Existing research files are preserved; conflicting generated files cause setup to fail rather than overwrite them. A missing synthetic projection currently produces dummy data with a warning. Folder creation alone is insufficient: initialization also needs the authorized dataset selection.

## Proposed signed-in flow

```text
epsilon start → Sign in with Epsilon → Your projects
                                          │
                           no projects / Create project
                                          ↓
                        Name + local folder + dataset
                                          ↓
                       Create project and initialize
                                          ↓
                           Assistant + Notebook
```

Returning researchers go straight to their associated projects. Ask for the folder when creating or opening a project, rather than on every login. Setup progress should say what is happening: downloading the synthetic dataset, preparing the models, and opening the workspace. A failed download should leave a retryable setup state, with no duplicate project or overwritten files.

Use the shared `initialise_project()` service from the UI instead of launching a shell command. **Open existing project** validates `project.yml` and its generated files and associates that folder explicitly; it does not run initialization again.

Account association requires more than an email field:

- Identify an account by verified identity-provider issuer and subject, scoped to the configured Epsilon server. SSO already saves verified issuer/subject information. The legacy password flow needs a trusted identity lookup or equivalent verified claims before associating projects; preserve the CLI flow without trusting a decoded, unverified JWT or treating an entered email as identity.
- Enforce association on every project API, including threads, notebooks, exports, jobs and kernel operations. Check the account before resolving or revealing a project path.
- Keep old registry entries and research files, but require an explicit **Open existing project** action to associate an unassigned folder. Do not assign every old folder to the first account that signs in. Do not silently reassign a folder associated with another account.
- Stop automatically presenting the launch folder as a project in the signed-in view. It can be the initial folder suggestion in the setup form.
- On account changes, clear the previous account's browser state and reject stale requests. Pin background work to the account and server that started it; it must not pick up another account's credentials when a download or model task starts later.
- Keep any optional offline UI separate from signed-in projects. Existing CLI commands continue to operate on the explicitly selected local project directory. UI account scoping does not provide filesystem isolation between people sharing an operating-system account.

## What build does today

The implementation is in `sdk/epsilon_cli.py`, in `build()`.

| Step | Current behavior |
| --- | --- |
| Select source | Read `entry_point` from `project.yml`, defaulting to `main.py`. |
| Check | Run static project and packaging checks, unless `--skip-checks` is supplied. |
| Copy | Copy the entry-point script, the whole `generated/` directory, and `analyses/` when present into `./build` or `--output-dir`. |
| Dependencies | Run `pip freeze` in the Python environment running the CLI and write that output to the package's `requirements.txt`. |
| Manifest | Write `build.yml` with the script filename, dataset/archetype references, wrapper import, and execution/privacy metadata. |
| Git | Attempt `git add` on the output directory. |

Build creates a directory. It does not execute the analysis, create a ZIP, upload it, or obtain TRE output approval. `epsilon run` executes the configured Python entry point in the CLI's host environment. The notebook Run button executes saved cell source in a separate Docker/Jupyter environment.

Typical current output:

```text
build/
  build.yml
  main.py
  requirements.txt
  generated/
    __init__.py
    models.py
    archetype.json
    data.csv
  analyses/                 # when present
```

The `privacy.epsilon: 1.0` manifest field is currently hardcoded. Writing that number does not apply differential privacy or establish that output is safe to release.

## Verified gaps

A disposable artificial project was built with the real CLI and real filesystem operations, with checks enabled. No researcher data or live API calls were used. The existing CLI/check suite also passed: **73 tests**.

| Finding | Observed result | Consequence |
| --- | --- | --- |
| Notebook edits are omitted | The packaged `main.py` retained its original source; notebook code was absent. | A researcher can build the initial template after doing all their work in Jupyter. |
| `.ipynb` is not a supported entry point | Changing `entry_point` to `analysis.ipynb` still reported success, copied notebook JSON into `analysis.py`, and left the manifest pointing to a nonexistent `analysis.ipynb`. | Changing `project.yml` is not a notebook conversion solution. |
| Local data is copied | `build/generated/data.csv` existed after a normal build. | The submitted folder can carry local input data. `.gitignore` does not filter `copytree`. |
| Old files survive rebuilds | A removed generated helper remained in the next build. | A package can contain obsolete source or other leftover files. |
| Dependencies come from the wrong environment | A fixture with a one-line project requirement produced 154 requirements from the CLI environment, including one editable/local reference. | Notebook library availability and package dependencies can disagree; local paths are not portable. |
| Dataset provenance is omitted | Dataset version and schema hash from `project.yml` were absent from the dataset manifest entry. | Build does not preserve the same pinned input identity used by initialization and local analysis. |

Additional code findings: dependency generation failure is handled by producing a comment-only requirements file and reporting build success; generated dependency output is not rechecked after assembly; and the existing output directory is not assembled through fresh staging. These should be corrected in a shared packaging service while retaining the existing command names and ordinary Python entry-point workflow.

## Notebook and enclave compatibility

Notebooks are stored in `~/.epsilon_sdk/workbench.db`. The browser's notebook export route emits a source-only `.ipynb`, without execution counts or outputs. It does not write an analysis script or update `project.yml`. The separate saved-preview ZIP is a review artifact, not an `epsilon build` package.

The local notebook container receives a read-only generated-data snapshot. It cannot silently update the host project's `main.py`. Its library environment includes pandas, matplotlib, seaborn, scipy and statsmodels, while build currently freezes the host environment.

The sibling `Epsilon/epsilon-enclave` source was also inspected. Its bundle executor runs a Python script, and can inject separately supplied CSV into `generated/data.csv`. The inspected execution path uses a fixed runtime rather than installing each bundle's requirements. Its import allowlist does not include matplotlib or seaborn. Its request handler does not supply the manifest's script filename to the executor, which instead searches for conventional script names. These are source-level integration findings; the deployed enclave version was not verified and no live enclave job was run.

Therefore a successful local notebook plot does not establish enclave compatibility. The package manifest, selected entry point, runtime dependencies and output format need an integration test against the actual server/enclave version. Charts can be rendered locally from permitted returned aggregates; a local `plt.show()` display is not itself a TRE output contract.

## Proposed notebook-to-build workflow

```text
Notebook → Prepare for build → Review Python source + dependencies
                                            ↓
                          Validate in a fresh compatible runtime
                                            ↓
                              Shared epsilon build service
                                            ↓
                                 Reviewable build folder
```

The workbench now provides **Notebook options → Prepare for build** as the first
step of this workflow. It concatenates the selected Python cells into a review
candidate, records the notebook revision, dataset/schema/input identity and
runtime inventory, and reports static findings such as secrets, unknown fields,
and notebook magics. It never overwrites `main.py`, executes the candidate on
the host, includes notebook outputs or submits a package. The existing
`epsilon build` command remains the explicit packaging step until the same
reviewed source and dependency contract is shared by both paths.

Keep notebook execution and packaging as distinct user actions. **Prepare for build** should:

1. Save and select an explicit notebook revision and code cells, then produce a plain Python entry point the researcher can inspect. Prefer the generated dataset wrapper and a clear `main()`/output contract. Preserve cell-to-source provenance and the existing `main.py`; replacing it requires a visible review of the change.
2. Validate selected code in order in a fresh runtime, so it cannot rely on hidden kernel state. Reject unsupported notebook magics and shell commands with a cell-specific explanation. Do not silently concatenate arbitrary notebook JSON or execute model-generated source on the host.
3. Resolve exact dependencies against a supported target runtime, including Python version. Notebook-only visualization libraries must not be presented as enclave-compatible merely because they are installed locally. Do not install arbitrary dependencies inside an enclave at job execution time.
4. Call one shared packaging service used by both the UI and `epsilon build`. Use fresh staging, restrict package files to reviewed source/schema/models/helpers/dependencies, validate the completed package, and preserve dataset/schema/runtime/source provenance. Exclude CSV inputs, notebook outputs, chats, credentials and stale artifacts.
5. Show the selected notebook revision and resulting script in the build summary. Subsequent notebook edits make the previous build out of date; they must not silently alter an already reviewed package.

An additive notebook selection option can be considered after this contract is implemented. Existing `epsilon login`, `epsilon init`, `epsilon run`, `epsilon build` and all other CLI commands remain usable for researchers who work in an editor or external Jupyter.

## Implementation order and acceptance checks

1. **Account-specific projects and onboarding.** Verify that account A cannot list or request account B's projects, notebooks, exports or jobs; an old unassigned folder stays hidden until opened explicitly; an account with no projects sees folder/dataset setup; returning users resume their own projects; legacy CLI login still works.
2. **Shared packaging corrections.** Keep existing command syntax, preserve supported Python projects, use fresh output and explicit included files, validate requirements and manifest after assembly, and reject unsupported entry-point formats. Test that deleting a source removes it from the next package, input CSV never enters a submission package, and no researcher source is overwritten by output-directory choices.
3. **Notebook preparation and UI build.** Compare the selected notebook revision with the generated script, verify behavior in a fresh supported runtime, and demonstrate that both the UI and CLI produce the same package for the same selected source/configuration. Verify the manifest and dependency contract with the actual coordinator/enclave before claiming deployment support.

Build remains preparation for submission. Data authorization, approved methods, disclosure controls and TRE release decisions remain independently enforced server-side.
