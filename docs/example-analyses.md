# Example analyses

The project overview now introduces examples before the empty question box when
there is no prior work. The **Examples** navigation item opens the same library.
Successful dataset setup lands on this overview. Existing projects keep
**Continue work**, the assistant/notebook layouts, and their saved research.

## Demo walkthrough

1. Start Docker Desktop, then run `.venv/bin/epsilon start` from the SDK checkout
   (or `epsilon start` from an environment with this branch installed).
2. Sign in with the existing Epsilon credentials. Select an approved dataset and
   a local folder, or open an initialized project.
3. Choose an example. Point out its question, **What you’ll learn**, exact fields,
   and two charts. **View counts** opens the underlying displayed values.
4. Choose **See the code**, then **Use this example**. This creates a new notebook
   and its conversation, without copying preview outputs or inventing a user message.
5. Choose **Run all**. The same count tables and chart types render in the notebook.
   Edit a field or band width and rerun, or select **Use with AI** on an analysis
   cell, review the source, and choose **Explain this cell** for a reply immediately
   or **Ask my own question** to request a change. Applying an AI suggestion and
   running it remain separate actions.

No AI configuration is required to browse, copy, or run the predefined examples.
The managed notebook image supplies pandas, matplotlib, and IPython. Browsing
also works with Docker stopped; execution requires Docker and the notebook image.

## Available examples

| Example | Requirements | Views |
| --- | --- | --- |
| Explore measurements | At least one permitted numeric field | Two field distributions; for a single field, bars and a line across its ordered bands |
| Compare categories | Catalogue-approved cross-tabulation fields | Counts by combination and a heatmap of the same displayed cells |
| Explore records over time | Permitted dates with year grouping | Year counts as bars and a line, preserving gaps |
| Explore a category | A permitted categorical field, when fewer than three examples above apply | Bars and a pie of the same displayed groups |

The library offers up to three examples, rather than filling missing capabilities
with unsupported methods. These are record-count methods for practicing analysis
code. They do not estimate prevalence, causal effects or patient-level outcomes.

## Preview and copy behavior

`sdk/workbench/examples.py` selects fields through the existing catalogue and
starter validators. List/detail routes create no notebook, conversation, plan,
job or saved result. The preview reader never imports generated models or runs
researcher/AI Python. It reads the bounded synthetic CSV and uses the same
grouping helpers embedded in the notebook cells. Docker parity tests execute the
pandas notebooks and compare every displayed row to the preview.

Previews show their dataset/version and minimum cell size. They retain only the
first 20 eligible groups in sorted order, omit groups below the threshold, and
withhold a second group when needed. Hidden labels/counts are absent from the
response. Numeric/date gaps break lines, heatmaps leave hidden combinations blank,
and pies omit hidden slices and percentages. Invalid numeric/date values are
excluded; long category labels are grouped. These local rules do not assess
inference across repeated queries and are not TRE output approval.

At most eight displayed preview results are cached in process memory. Filesystem
identity, dataset metadata, template version and generated source invalidate the
cache. Previews never enter AI context or personal Results. If a preview exceeds
the row/group limits, the detail page still offers its code and a copy action.
The existing 256 MB workspace input limit also applies.

Copy requests contain an example ID, version and idempotency key, never arbitrary
source or field overrides. The server revalidates the current example and inputs.
One SQLite transaction creates the notebook, linked empty conversation, and
request record. Retrying returns the same copy, preserving later manual edits.
A separate intentional copy receives new notebook and cell IDs. Notebook saves
retain the original example provenance; they never update the library template.

All existing CLI commands remain unchanged. A copied notebook is development
source, not an `epsilon build` submission or a TRE-approved output.

## Checks

```bash
.venv/bin/python -m pytest tests/test_workbench_examples.py -q
EPSILON_TEST_NOTEBOOK=1 .venv/bin/python -m pytest tests/test_workbench_examples.py -k docker -q
npm test
npm run lint
```

The API tests cover read-only browsing, validated copying, concurrent/retried
copies, manual-edit preservation, input changes, field feasibility, suppression,
cache invalidation, and avoiding generated-model imports on the host. Browser
logic tests cover escaping, duplicate clicks, retry IDs, late responses, and
line gaps. The desktop/mobile walkthrough additionally checks navigation, code
disclosure, copying into both panes, and running all cells through the real UI.

## Screens

- [Project overview](workbench/previews/37-example-library.png)
- [Example with charts and code](workbench/previews/38-example-detail.png)
- [Example on mobile](workbench/previews/39-example-mobile.png)
