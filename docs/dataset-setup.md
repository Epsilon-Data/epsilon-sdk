# Dataset selection and local project setup

The browser now starts with datasets approved for the signed-in Epsilon account:

```text
Sign in → Approved datasets → Select dataset → Name and local folder
                                                      ↓
                                           Initialize project
                                                      ↓
                                            Assistant + Notebook
```

The configured Epsilon API is the source of dataset permissions. The production
dataset endpoint was verified to return two approved IDs for the researcher's
account while the local registry contained one project. Those counts describe
different objects and are displayed separately.

The API's dataset list contains IDs and modification timestamps. Display names,
descriptions and synthetic availability are loaded from the approved archetype
endpoint. The local UI loads that metadata in small concurrent batches, without
blocking access to existing local projects. Listing and selecting datasets do
not download CSV records, create folders, initialize projects, or call an AI model.

**Select dataset** opens a form with the dataset, project name and editable local
path. The default is `~/Epsilon Projects/<dataset-name>`. The user confirms before
files are created. If no synthetic projection is attached, the form requires an
explicit choice to use generated sample data.

Confirmation rechecks approval before registering the chosen folder. It retains
the selected dataset ID so interrupted setup can resume with that dataset
selected. The initialization endpoint checks approval again and captures the API
client before queuing work. A later account change cannot give an already queued
initialization another account's credentials. The browser also stops the next
setup request if the account changed while folder creation was pending.

The browser calls the shared `initialise_project()` implementation behind
`epsilon init`. That service stages and verifies the data and schema, generates
typed models, preserves existing research files, and creates `project.yml` and
an entry-point template. Initialization progress appears on the project page;
success opens its research workspace. Retrying a failed initialization request
from the setup form reuses the project already created by that form.

Existing local projects remain under **Continue work**, labeled as projects on
this computer. Their registry still represents local folders; this change does
not implement account ownership or filesystem isolation for those old projects.
The account-ownership migration and notebook build integration remain separate
items in [the build and account review](account-project-build-review.md).

All existing CLI commands remain available. Production API configuration and the
legacy username/password sign-in remain the current defaults.

Behavioral checks cover approved dataset counts versus local project counts,
metadata without record downloads, rejecting unapproved IDs before creating a
folder, expired credentials, approval revoked before initialization, the chosen
folder/dataset reaching the shared initialization service, and queued-client
identity. JavaScript checks cover display failures, stale responses after account
changes, selection without writes, setup ordering, and retry without creating a
second project.

Verification: 783 Python tests passed, with two optional checks skipped; all 26
JavaScript tests and frontend lint passed. A real browser using disposable sample
data verified the two-dataset/one-local-project page, selection and cancellation
without writes, the chosen dataset and folder reaching initialization, duplicate
submit protection, automatic workspace opening, reload, sign-out, and the mobile
layout. No production CSV was downloaded during this verification.
