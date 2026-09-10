# GUI modal-dialog hang: root cause, fix, and verification

Supersedes, for the purpose of "why did the GUI hang", the open,
unresolved framing in `docs/investigation_log.md`'s "Investigation A"
(`tkinter.Tk()`-after-ViennaPS, later corrected to "non-deterministic,
not tied to composition") and "Investigation B"
(`test_gui_doping_survives_geometry_steps_real.py`, "hang point moves
between attempts"). Those entries stay in place as the historical
record of how this was investigated; this document records where that
investigation actually landed. Investigation-log discipline (prior
hypotheses / experiments / results / discarded hypotheses / confirmed
root cause) is followed below for each of A and B, kept separate as
the user's own process required, even though both share one fix.

## A. Root cause

**Confirmed by a live py-spy stack trace, captured from a genuinely
stuck process (not inferred, not guessed):**

```
Thread 8520 (idle): "MainThread"
    show (tkinter\commondialog.py:45)
    _show (tkinter\messagebox.py:76)
    showinfo (tkinter\messagebox.py:88)
    run_oxidation (tcad_2d_stagewise.py:2481)
```

`run_oxidation()` called `messagebox.showinfo(...)` unconditionally
immediately after a real ViennaPS run succeeded. `messagebox.showinfo`
is a genuine Tk modal dialog: internally it blocks the calling thread
in `wait_window()` until the dialog window is destroyed, which
normally happens when a human clicks "OK". Every test, CI run, and
diagnostic script in this project calls `app.withdraw()` to run the
GUI headless — but `withdraw()` only hides the ROOT window; it does
nothing to the new `Toplevel` dialog `messagebox.showinfo()` creates,
and nothing to `wait_window()`'s block. With no human present, the
call waits forever. Directly confirmed live: the stuck process's CPU
time was frozen at 4.3s for the full duration it was observed
(20+ minutes), decisive proof (per this project's own established
CPU-delta methodology) that it was genuinely blocked, not merely slow.

**Prior hypotheses this investigation had entertained, and why they
are now superseded, not merely dropped:**

- *Windows subprocess pipe-handle-inheritance deadlock* (parent
  `communicate()` blocked forever because a grandchild process
  inherited the capture pipe's write handle). This remains a
  theoretically real Windows hazard and was not falsified, but it is
  **not needed** to explain anything actually observed: every captured
  hang, once real forensics were available, showed the block inside
  `messagebox.showinfo()`/`_notify_error()` in the PARENT's own Tk
  thread — never inside a pipe read. Not re-tested further because the
  observed symptom is already fully explained.
- *`tkinter.Tk()` construction hanging after real ViennaPS work*
  (`docs/investigation_log.md`'s original Investigation A entry). A
  systematic A1–A7d bisection in that entry already found this was not
  a reproducible composition. In hindsight this is consistent with the
  present finding: those bisection scripts mostly called ViennaPS
  directly or constructed `Tk()` without going through the real
  `run_oxidation()`/`run_etch()` GUI methods, so most of them never
  reached the `messagebox.showinfo()` call at all — only the ones that
  called the real GUI dispatch path could reach it, and it is exactly
  those (`A7`, the original unmodified test file) that hung.
- *The "different-interpreter child process" anomaly* (an observed
  hang-time child process running under the SYSTEM
  `Python311\python.exe` instead of the venv's own `python.exe`,
  flagged as unexplained in this project's history). Independently
  root-caused during this same investigation, unrelated to the modal
  hang: this venv's `Scripts\python.exe` on Windows/Python 3.11 is a
  "venvlauncher" stub that always re-execs the base interpreter as a
  child process (confirmed with a trivial `python -c "..."` one-liner
  containing no project code at all, which reproduces the same
  parent/child split every time) — a standard CPython 3.11+ Windows
  mechanism, not a project bug. Recorded here so a future session does
  not re-open it as a mystery.

**What remains uncertain about A specifically.** The historical
record (`docs/investigation_log.md`, Investigation A's reproduction
matrix) shows some real, unmodified-file attempts passing cleanly
(trial 5 of that matrix) and, earlier in this same investigation
round, a fresh capture where three consecutive real
`app.run_oxidation()` dispatches inside one process all completed
before the hang was ever observed. If `messagebox.showinfo()`
genuinely blocks on every call with no human present, none of that is
obviously consistent with a single call already having occurred
successfully without one. This was not reconciled call-by-call before
the fix was applied — the fix removes the reachable code path
entirely (see below), so it does not depend on resolving this, but a
future investigation into exactly how many `showinfo()` calls a
withdrawn-root Tk session can absorb before blocking (if that number
is not simply "one, always") is flagged here as unfinished, not
hidden.

## B. Root cause

Same mechanism as A, confirmed by the same sweep (see Fix, below):
`run_etch()` (and `run_deposition()`, `run_metallization()`, and
every other `run_X()` success path) carried its own unconditional
`messagebox.showinfo()` call, each at its own line. This is the
precise reason Investigation B observed the hang POINT itself moving
between attempts of the identical, unmodified
`test_gui_doping_survives_geometry_steps_real.py`: whichever real
`run_X()` dispatch the test's own call sequence happened to reach
last is the one whose OWN success (or failure) notification blocked —
not a shared resource race across different dispatch calls, as the
"same broad class, not confirmed identical mechanism" framing in
Investigation B's own log entry left open. `run_doping()` never
hanging in any B trial is also now explained rather than merely
observed: it runs entirely in-process (per this project's own prior
finding) and, checked directly, has no `run_X()`-style unconditional
success dialog in its own body — nothing in its own path would have
blocked it.

## C. Code changes

**`tcad_2d_stagewise.py`** (`TCADApplication`):

- Added two notifier methods next to the existing `_log()`:
  - `_notify_info(title, message)` — always logs via the existing
    `_log()` (the real GUI log panel), never shows a dialog, in either
    an interactive or headless session. A purely-informational "it
    worked" popup is not worth forcing any user to dismiss before
    continuing (THE INVARIANT: a step must not wait on input it does
    not need), and doing so headless is a permanent hang.
  - `_notify_error(title, message)` — always logs via `_log()`; also
    raises a real `messagebox.showerror()`, but ONLY while
    `self.winfo_viewable()` is true right now. **This is a LIVE check,
    not a latched flag.** The first version of this fix used a
    persisted `self._interactive` flag set once by an overridden
    `withdraw()` and never restored — an independent review (Codex)
    correctly flagged that this would permanently and silently drop
    error dialogs for a real user who withdraws the window and later
    `deiconify()`s it (an ordinary Tk usage pattern, e.g.
    minimize/restore), since the flag never flips back. Fixed by
    dropping the flag and `withdraw()` override entirely and checking
    `self.winfo_viewable()` at the moment of the call instead —
    confirmed directly (not assumed): a fresh root is viewable(1),
    `withdraw()` makes it 0, `deiconify()` restores it to 1.
- **Full sweep, not just `run_oxidation()`** (the user's own
  instruction: investigate whether the same pattern is scattered
  across other `run_X()` methods): every `messagebox.showinfo(` call
  site in the file (17 total, confirmed by a balanced-paren scan, not
  a plain grep, so nested parens couldn't hide one) was replaced with
  `self._notify_info(`; every `messagebox.showerror(` call site (61
  total, same method) was replaced with `self._notify_error(`. All 78
  original calls were confirmed, before changing anything, to be
  simple two-positional-argument `(title, message)` calls with no
  `parent=`/`icon=`/`detail=` kwargs anywhere, so the rename is a pure
  identifier substitution — no call site's arguments changed. Exactly
  one real `messagebox.showerror(title, message)` call remains in the
  whole file, inside `_notify_error()` itself. No
  `messagebox.showwarning`/`ask*` calls exist in production code
  (confirmed by the same sweep) — THE INVARIANT already kept those out.

**`tests/unit/test_gui_no_forced_order_mock.py`:**

- Extended the session-wide messagebox trap list from
  `(showwarning, askyesno, askokcancel, askquestion, askretrycancel,
  askyesnocancel)` to also include `showinfo` and `showerror`, per the
  user's instruction to trap every messagebox function, not just the
  confirm/ask family THE INVARIANT already covered. Defense-in-depth:
  with the fix above, nothing in this test's own path should ever
  reach these anymore (`_notify_info`/`_notify_error` intercept before
  `messagebox` is touched), so this addition changes nothing about
  what the test currently observes — it exists so a FUTURE regression
  that reintroduces a raw `messagebox.showinfo()`/`showerror()` call
  fails this test immediately instead of hanging it.
- Removed a now-redundant, now-stale local trap-and-restore block
  around the electrode-panel check (it separately trapped
  `showinfo`/`showerror` for just two calls, with a comment claiming
  "they are not in the session-wide trap list above" — no longer true
  once the point above landed; flagged by the same independent
  review). Replaced with a before/after length check against the main
  session-wide `blocked` list, which now covers the same two calls for
  free.

**`tests/integration/test_gui_doping_donor_acceptor_real.py`** (real
regression found by running the FULL suite before committing, exactly
the discipline the review insisted on): this pre-existing test
asserted `len(doping_popups) == 1` and `len(measurement_popups) == 1`
— i.e. it pinned the OLD, unconditional-modal behavior as correct.
Updated both assertions to their mirror image (`not doping_popups`,
`not measurement_popups`) plus a check that the real result is still
reported, now in the log panel instead (`"Doping: Doping profile
attached"` / `"Measurement: Voltage source"` substring checks against
`app.log.get(...)`), matching every other real success-path assertion
in this fix. A full sweep of every other test file that traps
`showinfo` (7 files total) confirmed this was the only one asserting a
specific popup COUNT rather than trapping defensively — the others
either don't assert emptiness at all, or already expect zero.

**`tests/integration/test_gui_headless_no_modal_hang_real.py`** (new):

Real ViennaPS 4.6.2 throughout, no mocking. Traps all 8 messagebox
functions (recording calls rather than blocking) as a regression net,
then:

1. real headless oxidation (`run_oxidation()`),
2. real headless etch chained onto it (`run_etch()`, the panel's own
   default Bosch DRIE model, safe at its own default `cycles=2`),
3. real headless deposition chained onto that (`run_deposition()`,
   default Isotropic Deposition),
4. a real headless **worker FAILURE** — `grid_delta_um=-1.0` on a
   FRESH wafer (`app.reset()` first; confirmed by direct execution
   that this value only fails re-materialization from scratch, not a
   resumed domain — see Development Rules discipline: this was
   measured, not assumed) reliably makes ViennaPS itself raise
   `RuntimeError('Domain setup is not correctly initialized.')` inside
   the real `--worker` subprocess.

Each step asserts the real result exists (`app.last_final_mesh`,
`app.wafer.processed`) or, for step 4, that a real `ERROR` entry was
logged — and, at the end, that the messagebox trap recorded **zero**
calls across all four real steps.

**`tests/unit/test_gui_error_dialog_visibility_gate_mock.py`** (new,
per the independent review's explicit request for a regression test
covering the `winfo_viewable()` recovery behavior): no ViennaPS/DevSim
needed — the real error path exercised is `run_oxidation()`'s
pre-existing numeric-field validation (a non-numeric `ox_temp_var`
raises `ValueError`, caught and reported via `_notify_error`). Pins
BOTH halves, since either alone would have passed under the OLD,
buggy latch design too: (1) withdrawn — the error is logged, no dialog
raised; (2) `deiconify()`'d — the SAME error path raises a real dialog
again, proving the gate tracks live visibility rather than "was
`withdraw()` ever called."

**`tests/run_regression.py`:**

A single flat timeout was wrong (independent review, with a concrete
counter-example): this project's own real DevSim/MOSFET solves are
legitimately, not-hung, slow. Replaced the flat 1800s bound with:
`DEFAULT_TIMEOUT_S = 900` (15 min) for ordinary tests, and
`LONG_TIMEOUT_S = 3600` (1 hour) applied only to an explicit
`LONG_TIMEOUT_TESTS` set — every test in this project that does a real
MOSFET or full-device-fabrication DevSim solve
(`test_device_fabrication_to_dc_sweep_real.py`,
`test_device_lifecycle_repeat_real.py`, the six `test_mosfet_*_real.py`
files, `test_robust_iv_sweep_real.py`), grounded in real measurement
(`test_device_fabrication_to_dc_sweep_real.py` took 619.5s in this
project's own regression run this session) plus CLAUDE.md's documented
1400+s `test_mosfet_body_bias_real.py` run ("DevSim cross-solve
sensitivity"), with headroom above both.

Also fixed a real gap the review caught: `subprocess.run(...,
timeout=...)` on `TimeoutExpired` only kills the ONE immediate child it
tracks — but this project's own real dispatch path (confirmed this
investigation) spawns a "venvlauncher" stub → real-interpreter
grandchild for EVERY subprocess call on this machine (a standard
CPython 3.11+ Windows mechanism, see section A), and a test's own
`--worker` dispatch repeats that one level deeper again. Killing only
the tracked PID would leave the real work orphaned and still running.
Rewritten to track the process via `Popen` and, on timeout, kill the
FULL descendant tree with `taskkill /F /T /PID`. This is documented
here as best-effort, not a guarantee — a process that has already
detached from the tree, or one running under different privileges, can
still survive it; the docstring on `_kill_tree_windows()` says the same
thing, so this is not overstated to a future reader either.

## D. Reproduction evidence

**Before the fix** (this investigation round, corrected instrumentation
— `subprocess.run` monkey-patched to preserve the real dispatch path
while logging `[DISPATCH]`/`[PARENT]` markers, real
`gui.TCADApplication()` + `app.run_oxidation()`, real in-process
ViennaPS oxidation before the dispatch loop, matching the original
failing test's structure): stage A6 (3 repeated real `run_oxidation()`
dispatches per trial) stalled with the target process's CPU time frozen
for 20+ minutes straight (from `CPU_s=4.203` at first stall detection
to `CPU_s` still unmeasurable-as-different 400+ seconds later). A live
`py-spy dump --pid <target>` against the stuck process, taken directly
(not through the buggy first-pass watchdog automation, which itself hit
an unrelated `UnicodeDecodeError` — same missing-`encoding=` class of
bug this project's own CLAUDE.md already documents for
`subprocess.run(capture_output=True, text=True)` without an explicit
`encoding=`, this time in the diagnostic script, not production code),
produced the exact stack trace quoted in section A above.

**After the fix:** `tests/integration/test_gui_headless_no_modal_hang_real.py`
run standalone, real ViennaPS, wall-clock bounded by an explicit 180s
timeout (comfortably above its actual running time):

```
[1/4] real headless oxidation...
    OK: real oxidation completed, no modal wait
[2/4] real headless etch, chained onto the oxidized wafer...
    OK: real etch completed, no modal wait
[3/4] real headless deposition, chained onto the etched wafer...
    OK: real deposition completed, no modal wait
[4/4] real headless worker FAILURE path...
    OK: worker failure logged, no modal wait, no dialog raised

HEADLESS NO MODAL HANG: real oxidation -> etch -> deposition, and a real
worker failure, all completed with no dialog wait -- every messagebox call
this session could have made was trapped, and none fired.
EXIT=0
```

Every step is a real ViennaPS 4.6.2 run through the real
`subprocess.run` → `tcad_2d_stagewise.py --worker` dispatch path — the
same path that hung before the fix. Zero messagebox calls were
recorded across all four real steps (success ×3, failure ×1).

`tests/unit/test_gui_no_forced_order_mock.py`, with the extended trap
list, still passes cleanly (all 7 of its own checks, including "no
blocking dialog raised anywhere").

## E. GUI verification

Per this project's own standing rule (not just a backend/mesh check —
see CLAUDE.md, "Verifying a GUI-facing fix... check that the GUI's own
canvas rendering actually displays the corrected result"): each of the
three real success steps in the new integration test asserts
`app.wafer.processed` and a real `app.last_final_mesh` path exists
after the step — i.e. the same real-mesh state the canvas renderer
(`redraw()`/`_draw_real_mesh_result()`) reads from, unchanged by this
fix (no rendering code was touched; only the two notifier call sites
were, and the GUI log panel itself — `self.log` — is left carrying
exactly the same completion-message text that `messagebox.showinfo`
used to show, just never as a modal). A prior session already
established the mesh-vs-canvas bbox comparison technique for the
Bosch fix; that technique was not re-run here because this fix does
not touch geometry, mesh export, or canvas drawing at all — it only
changes whether/when a text notification is shown as a dialog versus
logged, so there is no rendering behavior for that technique to
compare against a "before" state; the log panel's own content (the
actual user-visible completion text) is asserted directly instead, and
matches what the dialog used to say.

## F. Regression

**Targeted (standalone):**

| test | result | time |
|---|---|---|
| `tests/unit/test_gui_no_forced_order_mock.py` | PASS | 0.9s |
| `tests/unit/test_gui_error_dialog_visibility_gate_mock.py` (new) | PASS | 0.8s |
| `tests/integration/test_gui_headless_no_modal_hang_real.py` (new) | PASS | 5.4s |
| `tests/integration/test_gui_doping_donor_acceptor_real.py` | PASS | 13.0s |

**Full suite** (`tests/run_regression.py`, real ViennaPS 4.6.2 + real
DevSim, per-test timeout table in place): **94 passed / 3 failed / 1
timed out / 0 skipped.**

The 3 FAIL are exactly the pre-existing failures CLAUDE.md already
documents (this fix touches no DevSim, doping, mesh, or
process-physics code, and none of these tests import
`tcad_2d_stagewise`):

| test | failure | pre-existing? |
|---|---|---|
| `test_device_lifecycle_repeat_real.py` | asserts two runs give byte-equal I-V; they differ at ~1e-27 A (solver noise around zero) | yes — CLAUDE.md, "Resolved investigations" |
| `test_gui_measurement_doping_kinds_real.py` | real `Convergence failure!` (implant_windows edge near an etched sidewall at 1e20) | yes — CLAUDE.md OPEN item 2 |
| `test_robust_iv_sweep_real.py` | real `Convergence failure!` in `run_pn_junction_iv_sweep` | yes — CLAUDE.md, "Resolved investigations". Re-run standalone this session: same `devsim_py3.error: Convergence failure!` at `pn_junction_iv_sweep.py:101`, 47s — reproduces deterministically, not flaky. |

No "4th slot" flaky failure this run — `test_bosch_drie_resist_mask_real.py`
(the usual flaky candidate) PASSED, 4.4s.

**The 1 TIMEOUT is a wall-clock artifact, not a hang and not a
regression.** `test_mosfet_id_vds_real.py` was recorded as
`[TIMEOUT] (40492.8s)` — but its captured output shows it printed its
own final success line (`MOSFET Id-Vds SWEEP VERIFIED against real
ViennaPS 4.6.2 + DevSim`), i.e. the test's real work finished. 40492.8s
is ~11.25 hours, which is not real compute: the machine slept during
the overnight run, `time.time()` (wall clock, sleep-inclusive)
inflated while the process was suspended, and the timeout deadline
eventually fired on wake. Re-run standalone this session: **PASS,
~258s, clean exit (no lingering process, no teardown hang)** — fully
consistent with its sibling MOSFET tests (`id_vgs` 300.9s,
`vth_extraction` 290.6s, `body_contact` 504.0s, all PASS this run).
Its budget in the timeout table (3600s) was already ~14× its real
runtime; only a suspended process on a sleep-inflated clock could
reach even that. A wall-clock timeout firing spuriously after a
system sleep is an inherent limitation of any wall-clock bound and is
documented under Remaining issues; it is not grounds to widen the
budget further (real runtime is 258s).

**Timeout-table self-check** (`_selftest_timeout_table()` in
`tests/run_regression.py`, runs at import — no subprocess, no real
test execution): PASS.

- `test_auto_refine_from_doping_real.py` → 5400s (see the timeout
  discrepancy note in section C and Remaining issues; this session's
  own two direct runs measured 26.4s and 10.7s).
- all 9 MOSFET/full-device DevSim tests → > `DEFAULT_TIMEOUT_S`.
- any test with no explicit override → `DEFAULT_TIMEOUT_S` (900s).

## G. Remaining issues

- The call-count-before-hang reconciliation noted at the end of
  section A (some historical/this-session captures show multiple real
  `run_X()` success dispatches completing before a hang was observed,
  which is not obviously consistent with "the very first
  `showinfo()` call under a withdrawn root always blocks
  immediately"). The fix removes the code path entirely, so this does
  not block calling A/B resolved, but the exact absorption behavior of
  a withdrawn-root Tk session facing repeated `showinfo()` calls was
  not independently characterized.
- The Windows subprocess pipe-handle-inheritance hypothesis (parent
  `communicate()` blocked by an inherited handle on a grandchild
  process) was never confirmed OR falsified with a dedicated
  experiment — it simply was not needed to explain anything actually
  observed once real forensics existed. If a future hang is captured
  that does NOT show a `messagebox`/Tk frame in its py-spy stack, this
  hypothesis is the documented next thing to test.
- `tests/run_regression.py`'s own pre-existing `UnicodeEncodeError`
  while printing a failing test's traceback under the Windows cp949
  console (documented in CLAUDE.md) is unrelated to this fix and was
  not addressed here. (Note: the child test's own stdout still needs
  `PYTHONIOENCODING=utf-8` in the environment that launches
  `run_regression.py` — the runner sets `encoding=` for how it DECODES
  child output, not for how the child ENCODES its own; this too is
  pre-existing and matches the CLAUDE.md guidance to run the suite
  with that env var set.)
- The per-test timeout is a wall-clock bound, so it can fire
  spuriously if the machine SLEEPS mid-suite: `time.time()` inflates
  during suspend while the test process is frozen, and the deadline
  can trip on wake even though little real compute happened. Observed
  once this session (`test_mosfet_id_vds_real.py`, recorded 40492.8s,
  real runtime ~258s — see section F). This is inherent to a
  wall-clock timeout and not worth engineering around here — the
  TIMEOUT is still reported distinctly (not as FAIL) and the runner
  exits non-zero, so a human/next-session check catches it; a spurious
  post-sleep TIMEOUT should be resolved by re-running that one test
  standalone, exactly as was done here.
- Bosch/`BoschRecipe.cycles`, `_note_if_bosch_cycles_risky()`, Bosch
  geometry rendering, and Bosch validation were explicitly out of
  scope for this investigation (per the user's own instruction) and
  were not touched — the new integration test relies on the etch
  panel's existing default (Bosch DRIE at `cycles=2`, already
  confirmed safe by the prior Investigation C fix) without modifying
  any of it.
