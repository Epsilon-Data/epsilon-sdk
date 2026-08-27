# Dataset Card

The card is the semantic layer over an archetype. The archetype says which
columns a researcher may touch; the card says what those columns *mean*.

The SDK reads it from `generated/card.json`, downloaded by `epsilon init` from
`GET /api/v1/hub/analysis/datasets/{datasetId}/card`. **The endpoint does not
exist yet** — until it does, the SDK derives a degraded card from the archetype
alone and says so. This document is the contract it will be built against.

## Why it is needed

The archetype JSON served today carries no semantics. A real example from the
MIMIC-IV demo project:

```json
"icd_code":    { "type": "object",  "description": "Icd Code" },
"icd_version": { "type": "integer", "description": "Icd Version" }
```

Every `description` is the column label title-cased by codegen. Types collapse
to `"object"` wherever the Atlas `data_type` did not map. Nothing states the
coding system, the value domain, the missingness, or — most consequentially —
the **grain** of a row.

That archetype emits one row per `hosp.diagnoses_icd` row. Measured against the
live demo database: 100,000 rows describing 275 admissions and 100 patients,
between 69 and 9,848 rows per patient. Gender is 57/43 across patients but
51.6/48.4 across rows; mean age is 61.75 per patient and 62.71 per row. An
analysis that ignores this produces a wrong number that runs cleanly, passes
the submission gate, and returns attested.

The card is what lets the SDK refuse that analysis instead.

## Trust model

The card is **authored and attested by the data owner**, exactly like the
synthetic dataset. The platform verifies structure, never truth. `attestedBy`
records who stood behind it and when.

## Shape

```jsonc
{
  "cardVersion": 1,
  "title": "MIMIC-IV — Diagnoses, Admissions & Demographics",
  "datasetId": "0c706732-…",
  "archetype": "hmmUmI1bgOv8",
  "schemaHash": "4f2a91c0b3de…",     // pins the card to a synthetic version
  "datasetVersion": 3,
  "attestedBy": { "owner": "mimic-demo", "at": "2026-08-27T00:00:00Z" },

  "grain": {
    "unit": "diagnosis_record",
    "statement": "One row per diagnosis code recorded against an admission.",
    "rows": 100000,
    "entityCounts": { "admissions": 275, "patients": 100 },
    "dedupeKey": null,               // null => per-entity analysis is refused
    "known": true
  },

  "leaves": {
    "<dot.path matching the archetype>": {
      "source": "hosp.patients.anchor_age",
      "type": "integer",             // see Types
      "accessLevel": "DETAILED",     // or HIGH_LEVEL
      "description": "…",
      "unit": "years",
      "categories": ["M", "F"],
      "cardinality": 2,
      "nullRate": 0.0,
      "range": [21, 91],
      "releasableAs": ["month", "quarter", "year"],   // HIGH_LEVEL only
      "comparableAcrossEntities": false,              // see below
      "codeSystem": {
        "discriminator": "diagnoses.icd_version",
        "systems": { "9": "ICD-9-CM", "10": "ICD-10-CM" },
        "mixed": true,
        "split": { "9": 0.487, "10": 0.513 }
      },
      "caveats": ["Ages above 89 are recorded as 91 (de-identification cap)."]
    }
  },

  "excluded": ["No discharge date, so no length-of-stay or survival analysis."],
  "policy": { "minCell": 10, "allowAiProfiling": true }
}
```

## The four fields that carry the most weight

**`grain.dedupeKey`** — the leaf path that groups rows back to the entity of
interest. `null` means there is none, and every per-entity analysis
(prevalence, per-patient means, comorbidity counts) is refused with an
explanation and a route to request a pseudonymised key. This is the single
highest-value field in the card.

**`type: "duration"`** — a time-to-event measure. Survival analysis requires
one, or two temporal leaves to difference. It deliberately does *not* accept a
numeric field whose unit happens to be `years`: an age is not a time to event,
and treating it as one is exactly the error the catalogue exists to prevent.

**`comparableAcrossEntities: false`** — values are shifted per entity, so they
cannot be pooled onto one axis. De-identified health data is routinely
date-shifted (MIMIC-IV spans 2110–2201), which makes a calendar trend describe
the shifting rather than the data. Trend analysis is refused when this is
false.

**`codeSystem.mixed`** — one column holding codes from more than one system,
with `discriminator` naming the leaf that says which. Hypertension is `4019`
under ICD-9 and `I10` under ICD-10; in the demo database, matching only `4019`
undercounts it by 32%.

## Types

`integer`, `number`, `categorical`, `code`, `timestamp`, `date`, `duration`,
`string`, `unknown`.

Wider than JSON Schema's set because the distinctions decide which analyses are
offered. `unknown` is honest and safe — it simply makes the leaf ineligible
wherever a type matters.

## Generating one

Everything except owner prose is derivable:

| Field | Source |
|---|---|
| `source`, `type`, `accessLevel` | Atlas `rdbms_column` + the archetype node classification |
| `grain.rows`, `entityCounts` | the projection query, counted |
| `cardinality`, `nullRate`, `range`, `categories` | the validated synthetic CSV |
| `codeSystem.split` | the synthetic CSV, grouped by the discriminator |
| `description`, `caveats`, `unit`, `dedupeKey` | the owner, optionally drafted from an uploaded codebook |

The codebook route the frontend already POSTs to
(`/archetype/{projectId}/upload-codebook`) is unimplemented; wiring it is the
natural place for the LLM-assisted first draft, with the owner approving before
anything is attested.

## Compatibility

- A card whose `cardVersion` this SDK does not know is rejected with an upgrade
  message rather than silently misread.
- A missing card is normal: the SDK derives one, marks it `derived`, sets
  `grain.known` to false, and the catalogue refuses anything whose correctness
  depends on knowing the grain.
- When card and archetype disagree on which fields exist, the drift is recorded
  as a caveat rather than raising — the card is still mostly useful.

A worked example against the live demo project is in
[`examples/cards/mimic-iv-hmmUmI1bgOv8.card.json`](../examples/cards/mimic-iv-hmmUmI1bgOv8.card.json).
Every figure in it was measured with read-only queries against the demo
database.
