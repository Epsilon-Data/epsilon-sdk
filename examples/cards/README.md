# Example dataset cards

`mimic-iv-hmmUmI1bgOv8.card.json` describes the live MIMIC-IV demo project
(dataset `0c706732-…`, archetype `hmmUmI1bgOv8`). Every statistic in it —
row and entity counts, the ICD-9/ICD-10 split, value ranges, the row-level
versus patient-level distortions quoted in its caveats — was measured with
read-only queries against the demo database, not estimated.

To try it against a project:

```bash
cp mimic-iv-hmmUmI1bgOv8.card.json <project>/generated/card.json
cd <project> && epsilon explain
```

See [`docs/dataset-card.md`](../../docs/dataset-card.md) for the format.
