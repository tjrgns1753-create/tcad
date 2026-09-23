#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-step process-flow -> WaferStateV2 sequencing, pure-Python part.

No ViennaPS, no DevSim, no Tk -- every ProcessResult here is a directly
constructed `tcad.mesh.interface.ProcessResult`, never a real exported
mesh. This is possible because `advance_wafer_state_sequence()`
(tcad_2d_stagewise.py) never reads a mesh file itself: it takes
already-built `(category, ProcessResult)` pairs and calls
`advance_wafer_state()` once per pair, in order -- the one thing this
file exists to prove.

Covers required tests 1, 6, 10 from the WaferStateV2 sequencing task.
Tests 2-5, 7-9 (real ViennaPS/DevSim/GUI) are in
tests/integration/test_waferstate_sequential_flow_real.py.
"""
import ast
import copy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tcad.mesh.interface import ProcessResult
from tcad.physics.wafer_state_accumulation import advance_wafer_state, initial_wafer_state_from_recipe
from tcad.physics.wafer_state_v2 import attach_dopant, uniform_inventory_integral
import tcad_2d_stagewise as gui_mod

ROOT = Path(__file__).resolve().parents[2]


def _pr(state_transition=None):
    """A directly-built ProcessResult -- volume_mesh_path is never read
    for a non-"doping" category (advance_wafer_state only reads
    .metadata/.doping), so a fake path is safe here."""
    return ProcessResult(
        volume_mesh_path="unused.vtu",
        metadata={"state_transition": state_transition},
    )


# ---------------------------------------------------------------------------
# 1. per-step ordering mock
# ---------------------------------------------------------------------------
def test_1_per_step_ordering_mock():
    """etch -> deposition -> remesh: advance_wafer_state() must be called
    exactly 3 times, in that category order, never collapsed to the
    last step alone -- and the resulting event order must match."""
    seed_state = initial_wafer_state_from_recipe({
        "x_extent_um": 2.0, "silicon_depth_um": 1.0, "grid_delta_um": 0.05,
    })
    events_before = len(seed_state.events)

    calls = []
    orig = gui_mod.advance_wafer_state

    def _spy(state, result, category, *a, **k):
        calls.append(category)
        return orig(state, result, category, *a, **k)

    entries = [
        ("etching", _pr(None)),
        ("deposition", _pr(None)),
        ("remesh", _pr(None)),
    ]
    with patch.object(gui_mod, "advance_wafer_state", side_effect=_spy):
        final_state = gui_mod.advance_wafer_state_sequence(seed_state, entries)

    assert calls == ["etching", "deposition", "remesh"], (
        f"advance_wafer_state call order does not match execution order: {calls}")
    # Not collapsed to the last step alone: 3 real calls, not 1.
    assert len(calls) == 3, f"expected exactly 3 advance_wafer_state calls, got {len(calls)}: {calls}"

    new_events = final_state.events[events_before:]
    assert len(new_events) == 3, (
        f"expected 3 new SpatialEvents (one per step, none collapsed/merged), "
        f"got {len(new_events)}: {[e.process_category for e in new_events]}")
    assert [e.process_category for e in new_events] == ["etching", "deposition", "remesh"], (
        f"event order does not match execution order: "
        f"{[e.process_category for e in new_events]}")
    assert all(e.category == "UNSUPPORTED_BY_MODEL" for e in new_events), (
        "every entry here has transform=None (no caller in this project "
        "builds a real GeometryTransform yet), so every event must be the "
        "fail-closed UNSUPPORTED_BY_MODEL kind")
    print(f"PASS test_1: advance_wafer_state called 3x in order "
          f"{calls}, event order {[e.process_category for e in new_events]} "
          f"matches exactly, not collapsed to the last step")


# ---------------------------------------------------------------------------
# 6. first uncertainty provenance
# ---------------------------------------------------------------------------
def test_6_first_uncertainty_provenance_mock():
    """exact/modelled state -> transform-less etch (via
    advance_wafer_state_sequence) -> deposition (a genuinely new,
    explicitly-authored ACTIVE cell -- never inferred from a mesh):
    the FIRST uncertainty event must be attributed to the etch step;
    deposition's real new cell must not resurrect the etch-orphaned
    dopant; and the old region stays numerically UNSUPPORTED since no
    new material instance was ever exactly attached there."""
    from tcad.physics.wafer_state_v2 import GeometryTransform

    state = initial_wafer_state_from_recipe({
        "x_extent_um": 2.0, "silicon_depth_um": 1.0, "grid_delta_um": 0.05,
    })
    si_instance = state.cells[0].material_instance_id
    state = attach_dopant(
        state, species="P", polarity="donor",
        concentration_at=lambda x, y: 1e17,
        support_instance_id=si_instance, support_region_um=(-1.0, 1.0, -1.0, 0.0),
        model="uniform_v1", inventory_integral=uniform_inventory_integral(1e17), chemical_state="ACTIVE",
    )
    q_before = state.net_doping_at(0.0, -0.5)
    assert q_before.donor_concentration == 1e17, (
        f"sanity: dopant should be a real, queryable number before any "
        f"uncertainty step, got {q_before}")
    assert not any(e.category == "UNSUPPORTED_BY_MODEL" for e in state.events), (
        "sanity: no uncertainty should exist yet")

    # Step 1: a transform-less etch, via the new sequencing wrapper --
    # this is the FIRST step that can't be modelled (no GeometryTransform
    # exists for it anywhere in this project today).
    state = gui_mod.advance_wafer_state_sequence(state, [("etching", _pr(None))])
    unsupported_events = [e for e in state.events if e.category == "UNSUPPORTED_BY_MODEL"]
    assert len(unsupported_events) == 1, (
        f"expected exactly 1 uncertainty event after the etch, got "
        f"{len(unsupported_events)}")
    assert unsupported_events[0].process_category == "etching", (
        f"the FIRST uncertainty event must be attributed to the etch step "
        f"that caused it, got process_category="
        f"{unsupported_events[0].process_category!r}")
    q_after_etch = state.net_doping_at(0.0, -0.5)
    assert q_after_etch.net_doping is None, (
        f"dopant must be UNSUPPORTED (not resurrected, not silently kept) "
        f"right after the fail-closed etch: {q_after_etch}")

    # Step 2: deposition adds a genuinely NEW, concrete ACTIVE cell at a
    # DIFFERENT location -- hand-authored here exactly like this
    # project's existing test_wafer_state_v2_fail_closed_no_resurrection_
    # mock.py already does (never inferred from a mesh comparison; a
    # real caller would need this from a genuine, explicit process-layer
    # GeometryTransform, which does not exist for any category in
    # production yet -- see the investigation table).
    dep_transform = GeometryTransform(
        process_category="deposition", representable=True,
        added_cells=(("SiO2", (-1.0, 1.0, 0.0, 0.1), "sio2#dep1"),),
        output_instance_ids=("sio2#dep1",),
    )
    state = advance_wafer_state(state, _pr(None), "deposition", transform=dep_transform)

    # The new SiO2 cell is real and queryable (net 0, no attachment there
    # -- not an UNSUPPORTED region).
    q_new_cell = state.net_doping_at(0.0, 0.05)
    assert q_new_cell.net_doping == 0.0, (
        f"the new deposition cell should be a real, known-undoped region, "
        f"got {q_new_cell}")

    # The OLD (etch-orphaned) Si region must STILL be unsupported --
    # deposition adding an unrelated cell elsewhere must never resurrect
    # it, and no new material instance was ever exactly attached there.
    q_old_region_after_dep = state.net_doping_at(0.0, -0.5)
    assert q_old_region_after_dep.net_doping is None, (
        f"deposition must not resurrect the etch-orphaned dopant in the "
        f"OLD region: {q_old_region_after_dep}")
    assert (q_old_region_after_dep.physics_status or {}).get("resolution") == "UNSUPPORTED_BY_MODEL"
    # Still exactly 1 uncertainty event -- deposition of an UNRELATED
    # cell does not create a second one for the old region, and does not
    # remove the first.
    unsupported_events_after = [e for e in state.events if e.category == "UNSUPPORTED_BY_MODEL"]
    assert len(unsupported_events_after) == 1, (
        f"deposition must not add or remove the etch's own uncertainty "
        f"event: {len(unsupported_events_after)}")
    print("PASS test_6: first uncertainty event attributed to the etch step; "
          "deposition's real new cell is queryable but does not resurrect "
          "the old orphaned dopant; old region stays UNSUPPORTED_BY_MODEL")


# ---------------------------------------------------------------------------
# 10. static regression
# ---------------------------------------------------------------------------
def _iter_py_files():
    for path in ROOT.rglob("*.py"):
        parts = path.parts
        if any(p in (".venv", "venv", ".git", "__pycache__", "node_modules") for p in parts):
            continue
        yield path


def test_10_static_regression():
    """Production code must never (a) reference `last_step_category` or
    an equivalent single-flat-field heuristic, (b) build a
    GeometryTransform from a mesh comparison, or (c) contain a
    final-step-only WaferState sync path -- and per-step arrays that
    disagree in length must fail loudly, not silently misalign."""
    production_files = [
        ROOT / "tcad_2d_stagewise.py",
        *((ROOT / "tcad").rglob("*.py")),
    ]

    last_step_category_hits = []
    for path in production_files:
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8")
        if "last_step_category" in text:
            last_step_category_hits.append(str(path.relative_to(ROOT)))
    assert not last_step_category_hits, (
        f"production `last_step_category` reference(s) found (OPEN item 5 "
        f"must not be reintroduced as a new heuristic): {last_step_category_hits}")

    # final-step-only WaferState sync path: the retired
    # `_sync_wafer_state_geometry(last_executed_recipe, result)` call
    # site inside run_process_flow() must be gone -- the multi-step
    # flow's own sync now goes through advance_wafer_state_sequence().
    gui_source = (ROOT / "tcad_2d_stagewise.py").read_text(encoding="utf-8")
    tree = ast.parse(gui_source)
    run_process_flow_src = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_process_flow":
            run_process_flow_src = ast.get_source_segment(gui_source, node)
            break
    assert run_process_flow_src is not None, "run_process_flow() not found"
    assert "_sync_wafer_state_geometry" not in run_process_flow_src, (
        "run_process_flow() must not use the single final-step-only "
        "_sync_wafer_state_geometry() sync path any more -- it must "
        "advance WaferState once per real executed step")
    assert "advance_wafer_state_sequence" in run_process_flow_src, (
        "run_process_flow() must call advance_wafer_state_sequence() to "
        "advance WaferState per-step, in execution order")

    # mesh-derived GeometryTransform: no production code may build a
    # GeometryTransform by reading/diffing an exported mesh file. Every
    # real GeometryTransform() construction site in production code is
    # a hand-authored, explicit call (none exist in production yet --
    # this asserts none were added as a mesh-diff shortcut for this task).
    transform_ctor_files = []
    for path in production_files:
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8")
        if "GeometryTransform(" in text and path.name != "wafer_state_v2.py":
            transform_ctor_files.append(str(path.relative_to(ROOT)))
    assert not transform_ctor_files, (
        f"production code outside wafer_state_v2.py constructs a "
        f"GeometryTransform -- this task must not invent one from a mesh "
        f"comparison; found in: {transform_ctor_files}")

    # Codex P0-1 correction: the final-step-only compatibility fallback
    # ("if step_results is None: build one synthetic entry from the
    # last step's top-level fields") must be completely gone --
    # run_process_flow() must call the explicit validator and fail
    # closed on any schema/alignment problem, never quietly fall back
    # to a single synthetic entry.
    assert "steps_run_this_click[-1].get(\"_process_category\")" not in run_process_flow_src, (
        "the retired final-step-only synthetic-entry fallback must not "
        "be reintroduced into run_process_flow()")
    assert "validate_step_results" in run_process_flow_src, (
        "run_process_flow() must call validate_step_results() before "
        "adopting any per-step WaferState data")
    assert "FLOW_STEP_SEQUENCE_METADATA_INVALID" in run_process_flow_src, (
        "run_process_flow() must fail-close with the "
        "FLOW_STEP_SEQUENCE_METADATA_INVALID reason_code when "
        "validate_step_results() rejects the payload")

    print("PASS test_10: 0 `last_step_category` references, "
          "run_process_flow() uses advance_wafer_state_sequence() (not the "
          "final-step-only sync) and validate_step_results() (not the "
          "retired synthetic-entry fallback), 0 mesh-derived "
          "GeometryTransform construction sites in production code")


# ---------------------------------------------------------------------------
# P1-1. malformed step_results payloads (A-J) -- each must be rejected by
# validate_step_results(), never silently accepted or partially trusted.
# ---------------------------------------------------------------------------
def _valid_payload(n=2):
    """A structurally-valid worker `_flow_steps` payload, PLUS the
    `expected_steps` this session actually requested (Codex's own
    cross-layer provenance requirement) -- real files on disk for the
    final_mesh/domain_state existence checks (criteria 8, C), but no
    ViennaPS/mesh CONTENT is ever read by the validator. Top-level
    step_count/final_mesh/state_transition/physics_status/
    numerical_status are built to agree with the TERMINAL step_results
    entry, and domain_state points at a real file -- matching what a
    genuine worker payload always produces."""
    files = [tempfile.NamedTemporaryFile(delete=False, suffix=".vtu").name for _ in range(n)]
    domain_state_file = tempfile.NamedTemporaryFile(delete=False, suffix=".vpsd").name
    expected_steps = [
        {"_process_category": "etching" if i == 0 else "deposition", "_process_model_key": "isotropic"}
        for i in range(n)
    ]
    step_results = [
        {
            "index": i,
            "category": expected_steps[i]["_process_category"],
            "model_key": expected_steps[i]["_process_model_key"],
            "final_mesh": files[i],
            "state_transition": None, "physics_status": None,
            "numerical_status": None, "executed": True,
        }
        for i in range(n)
    ]
    terminal = step_results[-1]
    payload = {
        "success": True,
        "requested_step_count": n, "executed_step_count": n,
        "stopped_unsupported": False, "stopped_step_index": None,
        "step_results": step_results,
        "step_meshes": [sr["final_mesh"] for sr in step_results],
        "step_physics_status": [sr["physics_status"] for sr in step_results],
        "step_numerical_status": [sr["numerical_status"] for sr in step_results],
        "step_count": n,
        "final_mesh": terminal["final_mesh"],
        "state_transition": terminal["state_transition"],
        "physics_status": terminal["physics_status"],
        "numerical_status": terminal["numerical_status"],
        "domain_state": domain_state_file,
    }
    return payload, expected_steps


def test_P1_1_malformed_step_results_payloads():
    """22 malformed step_results payload variants (A-V, Codex's own
    list -- A-J structural/schema, K-V cross-layer physical provenance):
    each must be rejected by validate_step_results() with a diagnosis
    naming the broken field -- never silently accepted, never partially
    trusted, and a category/model_key mismatch is never "recovered" as
    an alias or typo. The production consequence of a rejection (0
    final-step-only fallback calls, 0 normal per-step advance calls, a
    single explicit FLOW_STEP_SEQUENCE_METADATA_INVALID fail-closed
    event, doping query None, 0 DevSim solve/write) is proven end to
    end for a representative cross-layer case (K's shape) by
    test_P1_1_gui_malformed_payload_e2e() in the real-execution test
    file -- every case here funnels through the exact same
    `if not is_valid: ...` branch in run_process_flow(), so re-proving
    the GUI consequence for every case would be redundant with that one
    E2E proof (using the ACTUAL, non-monkeypatched validator, per
    Codex's own requirement)."""
    base, expected_steps = _valid_payload()
    is_valid, _ = gui_mod.validate_step_results(base, expected_steps)
    assert is_valid, "sanity: the baseline payload must itself be valid"

    cases = {}

    p = copy.deepcopy(base)
    p["step_results"] = None
    cases["A_step_results_none"] = p

    p = copy.deepcopy(base)
    p["executed_step_count"] = 3  # step_results still has 2 entries
    cases["B_length_mismatch"] = p

    p = copy.deepcopy(base)
    p["step_results"][1]["index"] = 0  # duplicates step_results[0]'s index
    cases["C_duplicate_index"] = p

    p = copy.deepcopy(base)
    p["step_results"][1]["index"] = 5  # not contiguous with 0
    cases["D_index_gap"] = p

    p = copy.deepcopy(base)
    p["step_results"][0]["category"] = None
    cases["E_category_none"] = p

    p = copy.deepcopy(base)
    p["step_results"][0]["final_mesh"] = None
    cases["F_final_mesh_missing"] = p

    p = copy.deepcopy(base)
    p["step_results"][0]["executed"] = False
    cases["G_executed_false"] = p

    p = copy.deepcopy(base)
    p["step_meshes"][0] = "definitely_the_wrong_path.vtu"
    cases["H_step_meshes_mismatch"] = p

    p = copy.deepcopy(base)
    p["step_physics_status"][0] = {"resolution": "bogus_not_in_step_results"}
    cases["I_physics_status_mismatch"] = p

    p = copy.deepcopy(base)
    p["step_numerical_status"][1] = {"under_resolved_x": [1.0]}
    cases["J_numerical_status_mismatch"] = p

    # K. The user requested "etching" at index 0 (expected_steps[0]);
    # the worker's OWN record at that index is rewritten to "deposition"
    # -- a fully plausible, internally self-consistent entry (its own
    # model_key "isotropic" is a real deposition model too), never a
    # garbage string. Only cross-checking against expected_steps (what
    # was ACTUALLY requested) catches this -- no purely-internal
    # consistency check can.
    p = copy.deepcopy(base)
    p["step_results"][0]["category"] = "deposition"
    cases["K_requested_etch_recorded_as_deposition"] = p

    # L. The user requested model_key "isotropic" at index 0; the
    # worker's own record is rewritten to a different, still-valid-
    # looking model string ("directional"), category left correct.
    p = copy.deepcopy(base)
    p["step_results"][0]["model_key"] = "directional"
    cases["L_requested_isotropic_recorded_as_directional"] = p

    # M. top-level step_count disagrees with executed_step_count.
    p = copy.deepcopy(base)
    p["step_count"] = p["executed_step_count"] + 1
    cases["M_step_count_mismatch"] = p

    # N. top-level final_mesh disagrees with the terminal step's own mesh.
    p = copy.deepcopy(base)
    p["final_mesh"] = "definitely_not_the_terminal_mesh.vtu"
    cases["N_top_level_final_mesh_mismatch"] = p

    # O. top-level state_transition disagrees with the terminal step's own.
    p = copy.deepcopy(base)
    p["state_transition"] = {"kind": "bogus_not_from_any_step"}
    cases["O_top_level_state_transition_mismatch"] = p

    # P. top-level physics_status disagrees with the terminal step's own.
    p = copy.deepcopy(base)
    p["physics_status"] = {"resolution": "bogus_not_from_any_step"}
    cases["P_top_level_physics_status_mismatch"] = p

    # Q. top-level numerical_status disagrees with the terminal step's own.
    p = copy.deepcopy(base)
    p["numerical_status"] = {"under_resolved_x": [9.9]}
    cases["Q_top_level_numerical_status_mismatch"] = p

    # R. stopped_unsupported=False but the terminal entry claims
    # unsupported (top-level state_transition updated to match, so this
    # isolates criterion D specifically -- not accidentally caught by
    # the separate top-level/terminal agreement check, criterion B).
    p = copy.deepcopy(base)
    bogus_unsupported = {"kind": "unsupported", "category": "deposition", "reason": "bogus"}
    p["step_results"][-1]["state_transition"] = bogus_unsupported
    p["state_transition"] = bogus_unsupported
    cases["R_terminal_unsupported_but_flag_false"] = p

    # S. stopped_unsupported=False but stopped_step_index is not None.
    p = copy.deepcopy(base)
    p["stopped_step_index"] = 0
    cases["S_stopped_index_set_but_flag_false"] = p

    # T. requested_step_count disagrees with what this session actually
    # sent the worker (len(expected_steps)).
    p = copy.deepcopy(base)
    p["requested_step_count"] = len(expected_steps) + 5
    cases["T_requested_count_disagrees_with_expected_steps"] = p

    # U. domain_state is empty.
    p = copy.deepcopy(base)
    p["domain_state"] = ""
    cases["U_domain_state_empty"] = p

    # V. domain_state points at a path that does not exist.
    p = copy.deepcopy(base)
    p["domain_state"] = str(Path(tempfile.gettempdir()) / "definitely_does_not_exist_p1_1.vpsd")
    cases["V_domain_state_nonexistent_path"] = p

    for name, payload in cases.items():
        is_valid, reason = gui_mod.validate_step_results(payload, expected_steps)
        assert is_valid is False, (
            f"{name}: expected validation FAILURE, got valid (reason={reason!r})")
        assert reason, f"{name}: expected a non-empty diagnosis"
        print(f"  [{name}] rejected: {reason}")

    print(f"PASS test_P1_1: all {len(cases)} malformed step_results "
          f"variants (A-V) rejected by validate_step_results(), each "
          f"with its own diagnosis")


def main():
    test_1_per_step_ordering_mock()
    test_6_first_uncertainty_provenance_mock()
    test_10_static_regression()
    test_P1_1_malformed_step_results_payloads()
    print("\nALL WAFERSTATE SEQUENTIAL ADVANCE (MOCK) TESTS PASS")


if __name__ == "__main__":
    main()
