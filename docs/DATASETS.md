# Training datasets — provenance, licence, and what was actually downloaded

Required by Phase 2 §9 ("Do not ship a model whose training data licence you
cannot name") and §4.0 ("Record what you actually downloaded").

**This file is a record, not a plan.** Every row below is either marked
`VERIFIED` with a real download date, or `UNVERIFIED` — meaning the coordinates
in `models/training/taxonomy.yaml` are a search target that nobody has confirmed
yet. Do not quote an image count from this file that is still `UNVERIFIED`.

`prepare_datasets.py` prints the true per-class histogram after a merge. **That
output is the authority**, not this table and not `docs/TRAINING_PLAN.md` — both
were written before the data was fetched.

## How to fill a row in

```bash
export ROBOFLOW_API_KEY=...        # free account
python models/training/prepare_datasets.py --out data/training --datasets D1,D5,D8,D9,D10
```

Then for each source record: resolved project URL, licence as stated on the
dataset page, image count as reported by the prepare script, download date, and
the SHA256 of the downloaded archive.

```bash
sha256sum data/training/_downloads/<source>_*/*.zip 2>/dev/null | head
```

## Sources

| ID | Dataset | Licence | Images | Downloaded | Status |
|---|---|---|---|---|---|
| D1 | Roboflow — Construction Site Safety (`roboflow-universe-projects/construction-site-safety` v30) | CC BY 4.0 (**verify on page**) | — | — | UNVERIFIED |
| D2 | SH17 — 17-class fine-grained PPE | **verify** | — | — | UNVERIFIED · manual, needs `--d2-root` |
| D3 | MOCS — Moving Objects in Construction Sites | research-use (**verify**) | — | — | UNVERIFIED · manual |
| D4 | ACID — Alberta Construction Image Dataset | research-use (**verify**) | — | — | UNVERIFIED · manual |
| D5 | Roboflow — rebar detection/counting (2 projects) | **verify** | — | — | UNVERIFIED |
| D6 | CHV — Colour Helmet & Vest | **verify** | — | — | UNVERIFIED · manual |
| D8 | Roboflow — scaffolding + formwork | **verify** | — | — | UNVERIFIED |
| **D9** | **Roboflow — trench / excavation** | **verify** | — | — | **UNVERIFIED · coordinates are a guess** |
| **D10** | **Roboflow — ladder** | **verify** | — | — | **UNVERIFIED · coordinates are a guess** |

### D9 and D10 need the most scrutiny

They were added for Phase 2's Fatal Four coverage (classes 28 `trench`,
29 `ladder`), and unlike D1–D8 nobody has opened them. The
`workspace/project/version` triples in `taxonomy.yaml` are search targets
written from the class names, not confirmed coordinates. Roboflow Universe
projects get renamed, re-versioned and deleted, and **a wrong version number
silently fetches a different label set** rather than failing.

Before trusting a trained model on these classes:

1. Open each project on universe.roboflow.com and confirm it exists.
2. Confirm its label strings match the `mapping:` block — `prepare_datasets.py`
   raises on an unmapped label by design, so a mismatch fails loudly, but a
   *renamed* label that happens to collide with an existing key does not.
3. Record the licence. Several construction sets on Universe are non-commercial;
   that matters if FieldPilot is ever sold.
4. Note the count. Public trench and ladder data is scarce — both ids are in
   `known_sparse` for that reason. Low AP there is expected and must be
   **reported per-class**, never buried in a 30-class mean.

### Why shoring is mapped to `null`

D9's mapping sends `shoring`, `trench_box`, `shield` to `null` (dropped) rather
than to class 28. Mapping a *protective system* onto the *hazard* id would make
a properly shored trench indistinguishable from an unprotected one — inverting
the exact verdict Agent 11's caught-in rule exists to produce. When there is
enough shoring data, it earns its own class id; until then it is honestly absent
and the rule must say so.

## Licence obligations that follow the model

- **CC BY 4.0 (D1, and likely others) requires attribution.** Actually attribute
  it — in the README and anywhere model performance is quoted.
- **Research-use sets (MOCS, ACID) are not licensed for commercial deployment.**
  A model trained on them inherits that restriction. If FieldPilot is
  commercialised, either drop them and retrain, or license the data.
- The detector architecture carries its own licence, separate from the data —
  see the README's licence section for the Ultralytics AGPL-3.0 vs RF-DETR
  Apache-2.0 decision.
