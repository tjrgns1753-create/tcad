# Evidence Integrity Notice — Batch 7D `REPORT.md` byte-hash discrepancy

Filed by Batch 7G Phase 1 per its own section 4 requirement. This file records a real,
already-disclosed incident from Batch 7F; it does not attempt to fix or restore anything.

## What happened

During Batch 7F's mutation-test 10 ("기존 Batch 7D raw 파일을 수정" false-green check), the
test script temporarily appended a line to
`docs/audits/2026-09-21-batch7d-step-junction-convergence/REPORT.md`, then restored it by
writing back the previously-read Python string content. On Windows, Python's default TEXT-mode
file write translates `\n` -> `os.linesep` (`\r\n`), so the restore silently changed the file's
line endings even though the restore's own `restored_string == original_string` assertion
passed (Python's text-mode READ also normalizes `\r\n` -> `\n`, so that assertion cannot detect
a line-ending change at all). The mistake was caught and disclosed in the Batch 7F chat report
(section 20) at the time it happened, not discovered later.

## SHA-256 before and after

| | SHA-256 |
|---|---|
| Reported original (Batch 7F's own pre-existing-file snapshot, `batch7d_pre_existing_hashes.txt`) | `aaff8b6e41a7300031b7e30b72292e1877afb4439e9f49bd3f913aa1dc6b8be7` |
| Current, on disk now | `d091f54e3ccc4953de2a6c78acd0094dfc94e5023fe495b083d628bb16055fc8` |

## Content identity vs. byte identity — these are NOT the same claim

The current file's TEXT content matches, word-for-word, the original text this same
conversation read directly from the file (via the Read tool) earlier in the Batch 7D Rev.2 /
Batch 7E investigation, before any mutation test ran. That is a **content-identity** claim,
verified by direct human-readable comparison, not a cryptographic one. It is explicitly **not**
the same as byte identity: the SHA-256 mismatch above is real, reproducible, and not explained
by content differing — only by a line-ending (LF -> CRLF) transcription during the restore.

## No byte-level recovery is possible

`docs/audits/2026-09-21-batch7d-step-junction-convergence/` was never tracked by git
(`git status` reports the whole `docs/audits/` tree as untracked, confirmed both in Batch 7F
and again in this Batch 7G session) and no separate binary backup of this one file was made
before the mutation test ran. Multiple reconstruction attempts (original line endings, CRLF,
LF, with and without a trailing blank line) were tried in Batch 7F and none reproduced the
original SHA-256. This notice does not attempt another reconstruction — per this batch's own
instruction 4 ("이전 파일을 다시 복원하려 시도하거나 수정하지 마라"), the file is left exactly
as Batch 7F left it.

## Permanent exclusion from future mutation testing

`docs/audits/2026-09-21-batch7d-step-junction-convergence/REPORT.md` (and, out of caution, every
other `REPORT.md`/`SHA256SUMS.txt` under any existing audit directory) is permanently excluded
from any future "does the checker detect a modified pre-existing file" mutation test in this or
any later batch. Such a test must use a throwaway copy in a temp directory (as Batch 7G's own
`mutation_tests_7g.py` does — see its own docstring), never a real existing audit file, even
with a binary-safe read/write path.

## Batch 7D JSON/CSV/raw data hash status

Every OTHER file under `docs/audits/2026-09-21-batch7d-step-junction-convergence/` — every
`data/*.json`, `data/*.csv`, `raw/*.txt`, `scripts/*.py`, `patches/*` and the `rev2/` subtree in
full, **134 of the 135 files** in Batch 7F's own pre-existing-file snapshot
(`docs/audits/2026-09-22-batch7f-step-junction-root-cause/data/batch7d_pre_existing_hashes.txt`)
— was re-hashed fresh at the start of this Batch 7G session and matches that snapshot exactly.
Only `REPORT.md` (1 of 135) differs, for the reason above.

## This batch's own judgments are computed from raw data, not from the altered REPORT.md

Batch 7G Phase 1's own analysis (Delaunay/circumcenter/T-junction/overlap checks, and every
number in this batch's report) is computed FRESH from the raw imported ViennaPS meshes
this session builds directly via `tcad.backends.viennaps`/`tcad.device.devsim.mesh_refine`
(read-only production calls) and from Batch 7F's own `data/*.json` files (never from
`REPORT.md`'s prose, which is never parsed or read as a data source by any script in this
batch). The altered `REPORT.md` byte content therefore cannot have influenced any conclusion in
this report — it is Batch 7D's own summary text, unrelated to Batch 7G's or Batch 7F's actual
measurement pipeline.
