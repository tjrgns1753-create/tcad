#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_doping() must report what the canonical WaferStateV2 actually did, never what the recipe asked for.

Contract (Tier 1 + Batch 7C):
  * Uniform / Step Junction = a user-DECLARED analytic, electrically ACTIVE profile (log: ACTIVE ANALYTIC PROFILE DECLARED /
    DECLARED ANALYTIC ACTIVE PROFILE). Success = every requested profile has a NEW ACTIVE attachment and there is no new refusal event or
    unresolved-inventory entry; only then last_doped_result, history, overlay, True.
  * donor and acceptor stay two separate canonical attachments: N_D == N_A != 0 is a compensated profile (net 0), not a no-op.
  * Gaussian Implant / Implant Windows = process-like implant inputs; there is no implantation or activation model, so they are recorded
    CHEMICAL only: CHEMICAL PROFILE RECORDED; ELECTRICAL ACTIVATION UNSUPPORTED, False, last_doped_result/history/overlay untouched, the
    electrical query is None + UNSUPPORTED_BY_MODEL, DevSim is never written or solved.
  * refused = no attachment: the new state (refusal provenance + ledger) is kept, nothing is reported as applied, False, and no blocking modal
    (the notifier is forced "visible" here so a modal error WOULD be recorded).
  * reattach = succeeds only when the canonical state holds THIS request's own attachment(s) (same instance, model, params, polarity,
    species, chemical state); an unrelated attachment, or a stale numeric DopingProfile, is no reason.
  * zero     = every requested concentration is 0 -> known physical no-op.

Unit test: the REAL TCADApplication (window withdrawn), the REAL run_doping()/run_measurement(), the REAL recipe helpers, advance_wafer_state
and WaferStateV2. Only the ViennaPS mesh reader is replaced (a ProcessResult with no mesh read), and the DevSim boundary (apply_doping,
import_process_result) is a recording trap that must stay at 0 calls for every refused / chemical case. DevSim solve / write counts on a real
device are covered by the real-execution tests.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

REQ = "REQUESTED, NOT APPLIED"
REFUSED = "DOPING NOT APPLIED (UNSUPPORTED_BY_MODEL)"
NOOP = "NO DOPING ADDED: all requested concentrations are zero"
CHEM = "CHEMICAL PROFILE RECORDED; ELECTRICAL ACTIVATION UNSUPPORTED"
DECLARED = ("ACTIVE ANALYTIC PROFILE DECLARED", "DECLARED ANALYTIC ACTIVE PROFILE")
SUCCESS_WORDS = ("DOPING APPLIED", "profile attached", "Doping profile attached", "net_doping_cm3=")


def expect_fail(check, label, expected):
    """A mutant observation must fail `check`, and for the stated reason (str, tuple = all of them)."""
    try:
        check()
    except AssertionError as exc:
        text = str(exc)
        needed = (expected,) if isinstance(expected, str) else tuple(expected)
        missing = [n for n in needed if n not in text]
        assert not missing, f"WRONG FAILURE REASON for guard {label!r}: expected {missing} in {text!r}"
        return
    raise AssertionError(f"FALSE GREEN: guard {label!r} was accepted")


TRAP = {"writes": 0, "solves": 0, "imports": 0}
MODAL = []


# ---- observations and the contract checks (the same functions judge the real runs and the guards' mutants) ----------------------
def observe(app, fn):
    st0 = app.wafer_state
    o = {
        "att0": tuple(a.attachment_id for a in getattr(st0, "attachments", ())),
        "ev0": len(getattr(st0, "events", ())),
        "un0": len(getattr(st0, "unresolved_inventory", ())),
        "res0": app.last_doped_result, "hist0": list(app.history), "layer0": app.viewer_layer_var.get(),
        "log0": len(app.log.get("1.0", "end-1c")), "modal0": len(MODAL),
    }
    o["ret"] = fn()
    st = app.wafer_state
    o["att"] = tuple(a.attachment_id for a in getattr(st, "attachments", ()))
    o["new_att"] = [a for a in getattr(st, "attachments", ()) if a.attachment_id not in o["att0"]]
    o["new_events"] = list(getattr(st, "events", ())[o["ev0"]:])
    o["un"] = len(getattr(st, "unresolved_inventory", ()))
    o["res"], o["hist"], o["layer"] = app.last_doped_result, list(app.history), app.viewer_layer_var.get()
    o["log"] = app.log.get("1.0", "end-1c")[o["log0"]:]
    o["modal"] = len(MODAL) - o["modal0"]
    o["writes"], o["solves"], o["imports"] = TRAP["writes"], TRAP["solves"], TRAP["imports"]
    return o


def _no_devsim(o):
    assert o["writes"] == 0 and o["solves"] == 0, f"no DevSim write or solve may run: writes={o['writes']} solves={o['solves']}"


def check_supported(o, n_attachments=1):
    assert o["ret"] is True, f"supported doping must return True, got {o['ret']!r}"
    assert len(o["new_att"]) == n_attachments, f"exactly {n_attachments} new active attachment(s) expected, got {len(o['new_att'])}"
    assert all(a.chemical_state == "ACTIVE" for a in o["new_att"]), f"declared analytic profiles must be ACTIVE: {[a.chemical_state for a in o['new_att']]}"
    assert o["un"] == o["un0"], f"supported doping must not grow the unresolved ledger: {o['un0']} -> {o['un']}"
    assert not [e for e in o["new_events"] if e.model_status == "UNSUPPORTED_BY_MODEL"], "supported doping must not record a refusal event"
    assert o["res"] is not o["res0"] and o["res"] is not None, "supported doping must replace last_doped_result"
    assert o["hist"] == o["hist0"] + ["Doping: Uniform"], f"success history missing: {o['hist']}"
    assert "DOPING APPLIED: UNIFORM" in o["log"], "success log missing"
    for text in DECLARED:
        assert text in o["log"], f"the success log must say {text!r}"
    assert CHEM not in o["log"] and "simulated implant" in o["log"], "an analytic profile must never read as a simulated implant"
    assert o["layer"] == "doping", f"overlay must switch to the doping layer, got {o['layer']!r}"


def check_refused(o):
    assert o["ret"] is False, f"refused doping must return False, got {o['ret']!r}"
    assert o["att"] == o["att0"], f"refused doping must create no active attachment: {o['att0']} -> {o['att']}"
    assert o["res"] is o["res0"], "refused doping must leave last_doped_result untouched"
    assert o["hist"] == o["hist0"], f"refused doping must add no success history: {o['hist0']} -> {o['hist']}"
    assert o["layer"] == o["layer0"], f"refused doping must not switch the overlay: {o['layer0']} -> {o['layer']}"
    found = [w for w in SUCCESS_WORDS if w in o["log"]]
    assert not found, f"refusal log must not contain success wording {found}"
    assert REFUSED in o["log"], "refusal log must say DOPING NOT APPLIED (UNSUPPORTED_BY_MODEL)"
    assert REQ in o["log"], "requested values must be labelled REQUESTED, NOT APPLIED"
    assert "No DevSim write or solve is run" in o["log"], "refusal log must state that no DevSim write/solve runs"
    assert o["modal"] == 0, f"UNSUPPORTED_BY_MODEL must not raise a blocking modal, got {o['modal']}"
    _no_devsim(o)


def check_refused_recorded(o):
    """New-doping refusal: the state keeps its provenance -- one refusal event and one ledger entry per requested profile."""
    check_refused(o)
    refusals = [e for e in o["new_events"] if e.model_status == "UNSUPPORTED_BY_MODEL" and e.process_category == "doping"]
    assert len(refusals) == 1, f"one refusal doping event expected, got {len(refusals)}"
    assert o["un"] == o["un0"] + 1, f"one new unresolved-inventory entry expected: {o['un0']} -> {o['un']}"
    assert "1 refusal event(s) and 1 unresolved-inventory entr(ies)" in o["log"], "log must state what the WaferState recorded"


def check_chemical_recorded(o, n_attachments):
    """A process-like implant: recorded as CHEMICAL provenance, never reported as an electrical doping."""
    assert o["ret"] is False, f"a CHEMICAL-only request must not return True, got {o['ret']!r}"
    assert len(o["new_att"]) == n_attachments, f"{n_attachments} chemical attachment(s) expected, got {len(o['new_att'])}"
    assert all(a.chemical_state == "CHEMICAL" for a in o["new_att"]), f"states {[a.chemical_state for a in o['new_att']]}"
    assert not o["new_events"] or all(e.model_status != "UNSUPPORTED_BY_MODEL" for e in o["new_events"]), "a recordable chemical profile is not a refusal"
    assert o["un"] == o["un0"], "recording a chemical profile must not touch the unresolved ledger"
    assert CHEM in o["log"], f"log must say {CHEM!r}"
    found = [w for w in SUCCESS_WORDS + DECLARED if w in o["log"]]
    assert not found, f"a chemical record must not read as an applied/declared active doping: {found}"
    assert o["res"] is o["res0"] and o["hist"] == o["hist0"] and o["layer"] == o["layer0"], "last_doped_result / history / overlay must stay unchanged"
    assert o["modal"] == 0, f"no blocking modal, got {o['modal']}"
    _no_devsim(o)


def check_noop(o):
    assert o["ret"] is False, f"a zero request is not an applied doping; expected False, got {o['ret']!r}"
    assert o["att"] == o["att0"] and o["un"] == o["un0"], "zero request must create neither attachment nor ledger entry"
    assert not o["new_events"], f"zero request must not record any event (no false unsupported event): {o['new_events']}"
    assert NOOP in o["log"], "zero request must log the explicit no-op sentence"
    found = [w for w in SUCCESS_WORDS + (REFUSED, CHEM) if w in o["log"]]
    assert not found, f"zero request must not read as applied, refused or chemical: {found}"
    assert o["res"] is o["res0"] and o["hist"] == o["hist0"] and o["layer"] == o["layer0"], "zero request must change nothing in the GUI"
    _no_devsim(o)


def main():
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui
    from tcad.device.devsim import backend as devsim_backend
    import tcad.device.devsim.mesh_import as mesh_import_mod
    import tcad.device.devsim.doping_mapping as doping_mapping_mod
    import tcad.physics.wafer_state_v2 as v2
    from tcad.mesh.interface import DopingProfile, DopingRegion, ProcessResult

    app = gui.TCADApplication()   # no usable Tk display -> this raises; it is never a silent skip

    real = {
        "bpr": gui.build_process_result, "avail": devsim_backend.is_available, "req": devsim_backend.require_devsim,
        "imp": mesh_import_mod.import_process_result, "bar": mesh_import_mod.derive_barrier_covered_windows,
        "apply": doping_mapping_mod.apply_doping, "mb": gui.messagebox, "vis": app.winfo_viewable,
        "uni": gui.apply_uniform_doping,
    }

    class _Recorder:
        def __getattr__(self, name):
            return lambda *a, **k: MODAL.append(name)

    try:
        app.withdraw()
        app.update_idletasks()
        mesh_a, mesh_b = str(Path(__file__).resolve()), sys.executable   # two existing paths standing in for "mesh before / after a step"

        gui.messagebox = _Recorder()
        app.winfo_viewable = lambda: True     # a modal error WOULD show now -- a refusal must therefore not use one
        gui.build_process_result = lambda step_result: ProcessResult(volume_mesh_path=app.last_final_mesh)
        mesh_import_mod.derive_barrier_covered_windows = lambda *a, **k: []
        devsim_backend.is_available = lambda: True
        devsim_backend.require_devsim = lambda: object()

        def trap_import(process_result, **kw):
            TRAP["imports"] += 1
            raise RuntimeError("test boundary -- stop before any real DevSim device")

        def trap_apply(*a, **k):
            TRAP["writes"] += 1
            raise RuntimeError("test boundary -- a doping write must never be reached")

        mesh_import_mod.import_process_result = trap_import
        doping_mapping_mod.apply_doping = trap_apply

        def reset(state, doped=None, mesh=mesh_a):
            app.wafer_state = state
            app.last_final_mesh = mesh
            app.last_doped_result = doped
            app.history.clear()
            app.viewer_layer_var.set("geometry")
            app.doping_kind.set("Uniform")
            app.dope_uniform_region_var.set("Si")
            app.dope_uniform_donor_var.set("1e16")
            app.dope_uniform_acceptor_var.set("0")
            TRAP.update(writes=0, solves=0, imports=0)
            MODAL.clear()

        def set_gaussian(donor, acceptor):
            app.doping_kind.set("Gaussian Implant")
            for name, value in (("dope_gauss_region_var", "Si"), ("dope_gauss_axis_var", "x"), ("dope_gauss_position_var", 0.0),
                                ("dope_gauss_straggle_var", 0.3), ("dope_gauss_donor_var", donor), ("dope_gauss_acceptor_var", acceptor),
                                ("dope_gauss_donor_species_var", "P"), ("dope_gauss_acceptor_species_var", "B")):
                getattr(app, name).set(value)

        def set_windows(bg_d, bg_a, src_d, src_a):
            app.doping_kind.set("Implant Windows")
            for name, value in (("dope_win_region_var", "Si"), ("dope_win_axis_var", "x"), ("dope_win_donor_bg_var", bg_d),
                                ("dope_win_acceptor_bg_var", bg_a), ("dope_win_src_min_var", -1.5), ("dope_win_src_max_var", -0.5),
                                ("dope_win_src_donor_var", src_d), ("dope_win_src_acceptor_var", src_a), ("dope_win_drn_min_var", 0.5),
                                ("dope_win_drn_max_var", 1.5), ("dope_win_drn_donor_var", 0.0), ("dope_win_drn_acceptor_var", 0.0)):
                getattr(app, name).set(value)

        def modelled():
            return v2.initialize_wafer_state(cells=[("Si", (-2.0, 2.0, -1.0, 0.0), "si#substrate")], grid_delta_um=0.2)

        def unresolved():
            return v2.advance(modelled(), None, step_seed="oxidation")

        def legacy():
            return v2.legacy_state_from_v1_cells([SimpleNamespace(material="Si", x_min=-2.0, x_max=2.0, y_max=0.0)], grid_delta_um=0.2)

        # ---- A. supported uniform doping (one polarity): a declared analytic ACTIVE profile ------------------------------------------
        reset(modelled())
        obs_a = observe(app, lambda: app.run_doping(silent=True))
        check_supported(obs_a)
        q = app.wafer_state.net_doping_at(0.0, -0.5)
        assert (q.donor_concentration, q.acceptor_concentration, q.net_doping) == (1e16, 0.0, 1e16), q
        assert q.physics_status is None, q.physics_status
        print("A supported uniform 1e16/0: True, +1 ACTIVE attachment, query donor 1e16 / acceptor 0 / net 1e16, declared-analytic log")

        # ---- A2. compensated uniform: N_D == N_A != 0 is NOT a zero net and NOT a no-op --------------------------------------------------
        reset(modelled())
        app.dope_uniform_donor_var.set("1e17")
        app.dope_uniform_acceptor_var.set("1e17")
        obs_comp = observe(app, lambda: app.run_doping(silent=True))
        check_supported(obs_comp, n_attachments=2)
        assert sorted(a.polarity for a in obs_comp["new_att"]) == ["acceptor", "donor"], [a.polarity for a in obs_comp["new_att"]]
        assert {a.polarity: a.model_params["conc_cm3"] for a in obs_comp["new_att"]} == {"donor": 1e17, "acceptor": 1e17}, \
            "both requested values must be kept in the canonical provenance"
        q = app.wafer_state.net_doping_at(0.0, -0.5)
        assert (q.donor_concentration, q.acceptor_concentration, q.net_doping) == (1e17, 1e17, 0.0), q
        # concentration preservation is not transport capability: the log says so (the central DevSim gate blocks the measurement)
        assert "COMPENSATED_TRANSPORT_MODEL_MISSING" in obs_comp["log"] and "UNSUPPORTED_BY_MODEL" in obs_comp["log"], obs_comp["log"]
        assert "COMPENSATED_TRANSPORT_MODEL_MISSING" not in obs_a["log"], "a single-polarity doping must not carry the compensation note"
        print(f"A2 compensated uniform 1e17/1e17: True, 2 ACTIVE attachments {[(a.polarity, a.model_params['conc_cm3']) for a in obs_comp['new_att']]}, "
              f"query donor {q.donor_concentration:g} / acceptor {q.acceptor_concentration:g} / net {q.net_doping:g}")

        # ---- B / C. UNRESOLVED and LEGACY_UNRESOLVED states ----------------------------------------------------------------------
        sentinel = SimpleNamespace(volume_mesh_path=mesh_a, marker="previous result")
        obs_refused = {}
        for tag, build, lifecycle in (("B", unresolved, "UNRESOLVED"), ("C", legacy, "LEGACY_UNRESOLVED")):
            reset(build(), doped=sentinel)
            assert {c.lifecycle for c in app.wafer_state.cells} == {lifecycle}, f"{tag}: setup is not a {lifecycle} state"
            obs_refused[tag] = observe(app, lambda: app.run_doping())     # non-silent = the APPLY DOPING button path
            check_refused_recorded(obs_refused[tag])
            assert "1.000e+16" in obs_refused[tag]["log"] and "net_doping_cm3" not in obs_refused[tag]["log"], f"{tag}: bad requested-value text"
            print(f"{tag} {lifecycle}: False, 0 attachments, refusal recorded, last_doped_result/history/overlay unchanged, no modal")

        # ---- D. refused reattach: a stale result exists, the canonical state holds no attachment ---------------------------------------
        stale = SimpleNamespace(volume_mesh_path=mesh_a, doping=SimpleNamespace(kind="uniform", regions=[SimpleNamespace(region="Si")]))
        reset(unresolved(), doped=stale, mesh=mesh_b)
        assert app._doping_is_stale() is True
        obs_d = observe(app, lambda: app.run_doping(silent=True, reattach=True))
        check_refused(obs_d)
        assert not obs_d["new_events"] and obs_d["un"] == obs_d["un0"], "a refused reattach must not add a new refusal record"
        reset(unresolved(), doped=stale, mesh=mesh_b)
        app.run_measurement()
        assert app.last_doped_result is stale, "a refused reattach must not replace the stale result"
        assert TRAP == {"writes": 0, "solves": 0, "imports": 0}, f"refused reattach must stop before import/write/solve: {TRAP}"
        print("D refused reattach (no attachment): False, stale result kept, measurement stopped before import/write/solve")

        # ---- E. supported reattach: THIS request's own canonical attachment exists -------------------------------------------------------
        reset(modelled())
        assert app.run_doping(silent=True) is True
        first_result = app.last_doped_result
        n_att = len(app.wafer_state.attachments)
        app.last_final_mesh = mesh_b            # a later step moved the mesh on; the doping is now stale
        assert app._doping_is_stale() is True
        TRAP.update(writes=0, solves=0, imports=0)
        app.run_measurement()
        assert TRAP["imports"] == 1, f"a supported reattach must proceed to the measurement import, got {TRAP['imports']}"
        assert app.last_doped_result is not first_result, "a supported reattach must use the refreshed result"
        assert len(app.wafer_state.attachments) == n_att, "reattach must not append a duplicate attachment"
        print("E exact reattach (same fingerprint): proceeds, refreshed result, no duplicate attachment")

        # ---- E2. reattach must be THIS request: every difference (or an unrelated attachment) refuses --------------------------------------
        def stale_state_with_uniform_1e16():
            reset(modelled())
            assert app.run_doping(silent=True) is True
            app.last_final_mesh = mesh_b
            TRAP.update(writes=0, solves=0, imports=0)
            assert app._doping_is_stale() is True

        negatives = []
        stale_state_with_uniform_1e16()
        app.dope_uniform_donor_var.set("2e16")                       # different concentration
        negatives.append(("different concentration", observe(app, lambda: app.run_doping(silent=True, reattach=True))))
        stale_state_with_uniform_1e16()
        app.dope_uniform_donor_var.set("0")
        app.dope_uniform_acceptor_var.set("1e16")                    # different polarity: only a donor attachment exists
        negatives.append(("different polarity (unrelated attachment only)", observe(app, lambda: app.run_doping(silent=True, reattach=True))))
        stale_state_with_uniform_1e16()
        app.doping_kind.set("Step Junction")                         # different model
        for name, value in (("dope_step_region_var", "Si"), ("dope_step_axis_var", "x"), ("dope_step_position_var", 0.0),
                            ("dope_step_donor_var", 1e16), ("dope_step_acceptor_var", 0.0)):
            getattr(app, name).set(value)
        negatives.append(("different model", observe(app, lambda: app.run_doping(silent=True, reattach=True))))
        stale_state_with_uniform_1e16()
        set_gaussian(1e16, 0.0)                                      # different chemical state (and model)
        negatives.append(("different chemical state", observe(app, lambda: app.run_doping(silent=True, reattach=True))))
        for label, o in negatives:
            assert o["ret"] is False, f"reattach with {label} must fail, got {o['ret']!r}"
            assert o["res"] is o["res0"], f"reattach with {label} replaced last_doped_result"
            assert o["hist"] == o["hist0"], f"reattach with {label} added a history entry"
            assert not o["new_att"] and o["writes"] == 0 and o["solves"] == 0, label
        assert all(REFUSED in o["log"] or CHEM in o["log"] for _, o in negatives), "each negative reattach must be explained in the log"
        print("E2 reattach negatives (all refused, nothing replaced): " + ", ".join(l for l, _ in negatives))

        # ---- G. Gaussian Implant: explicit compensation is two profiles, recorded CHEMICAL, never electrical ------------------------------
        reset(modelled(), doped=stale)      # an earlier, measurable (mesh-bound) result exists
        set_gaussian(1e18, 1e18)
        obs_g = observe(app, lambda: app.run_doping())
        check_chemical_recorded(obs_g, 2)
        assert sorted((a.polarity, a.species) for a in obs_g["new_att"]) == [("acceptor", "B"), ("donor", "P")], \
            [(a.polarity, a.species) for a in obs_g["new_att"]]
        assert {a.polarity: a.model_params["peak_conc_cm3"] for a in obs_g["new_att"]} == {"donor": 1e18, "acceptor": 1e18}, "equal peaks must not collapse"
        qg = app.wafer_state.net_doping_at(0.0, -0.25)
        assert (qg.donor_concentration, qg.acceptor_concentration, qg.net_doping) == (None, None, None), qg
        assert qg.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL", qg.physics_status
        assert app.last_doped_result is stale, "a CHEMICAL record must not become the measurable doping result"
        app.run_measurement()
        assert TRAP["writes"] == 0 and TRAP["solves"] == 0, f"CHEMICAL must never reach DevSim write/solve: {TRAP}"
        print(f"G Gaussian donor=acceptor=1e18 (GUI): False, 2 CHEMICAL attachments {[(a.polarity, a.species) for a in obs_g['new_att']]}, "
              f"query {(qg.donor_concentration, qg.acceptor_concentration, qg.net_doping)} UNSUPPORTED_BY_MODEL, last result/history/overlay unchanged")

        # ---- G2. Implant Windows (GUI) is CHEMICAL as well ---------------------------------------------------------------------------------
        reset(modelled(), doped=sentinel)
        set_windows(0.0, 0.0, 1e19, 1e18)
        obs_w = observe(app, lambda: app.run_doping())
        check_chemical_recorded(obs_w, 2)
        qw = app.wafer_state.net_doping_at(-1.0, -0.25)
        assert (qw.donor_concentration, qw.acceptor_concentration, qw.net_doping) == (None, None, None), qw
        print("G2 Implant Windows (GUI): False, 2 CHEMICAL attachments, query None/None/None")

        # ---- G3. partial application is atomic: one attachable + one refused profile -> NO new attachment, prior one preserved -------------------
        reset(modelled())
        assert app.run_doping(silent=True) is True                   # a real prior ACTIVE attachment (uniform 1e16)
        prior_att = tuple(app.wafer_state.attachments)

        def two_profile_request(process_result, donor_by_region_cm3=None, acceptor_by_region_cm3=None, chemical_state=None):
            return ProcessResult(volume_mesh_path=app.last_final_mesh, doping=DopingProfile(kind="uniform", regions=[
                DopingRegion(region="Si", donor_conc_cm3=2e17, acceptor_conc_cm3=0.0, chemical_state="ACTIVE"),      # attachable
                DopingRegion(region="SiO2", donor_conc_cm3=1e16, acceptor_conc_cm3=0.0, chemical_state="ACTIVE")]))  # no SiO2 instance

        gui.apply_uniform_doping = two_profile_request
        try:
            obs_p = observe(app, lambda: app.run_doping(silent=True))
        finally:
            gui.apply_uniform_doping = real["uni"]
        assert obs_p["ret"] is False and obs_p["new_att"] == [], f"a partly refused request must keep NO new attachment: {obs_p['new_att']}"
        assert tuple(app.wafer_state.attachments) == prior_att, "the prior attachment must be preserved exactly"
        assert sum(e.model_status == "UNSUPPORTED_BY_MODEL" for e in obs_p["new_events"]) == 2 and obs_p["un"] == obs_p["un0"] + 2,             "refusal provenance + ledger must be recorded for BOTH profiles of the request"
        assert obs_p["res"] is obs_p["res0"] and obs_p["hist"] == obs_p["hist0"] and obs_p["layer"] == obs_p["layer0"], "last result/history/overlay must not change"
        check_refused(obs_p)
        print("G3 partial application (1 attachable + 1 refused profile): False, 0 new attachments, prior attachment preserved, 2 refusal events + 2 ledger entries")

        # ---- F. zero concentration, every kind, on a supported and on an unresolved state ----------------------------------------------
        zero_fields = {
            "Uniform": (("dope_uniform_donor_var", 0.0), ("dope_uniform_acceptor_var", 0.0)),
            "Step Junction": (("dope_step_region_var", "Si"), ("dope_step_donor_var", 0.0), ("dope_step_acceptor_var", 0.0)),
            "Gaussian Implant": (("dope_gauss_region_var", "Si"), ("dope_gauss_donor_var", 0.0), ("dope_gauss_acceptor_var", 0.0)),
            "Implant Windows": (("dope_win_region_var", "Si"), ("dope_win_donor_bg_var", 0.0), ("dope_win_acceptor_bg_var", 0.0),
                                ("dope_win_src_donor_var", 0.0), ("dope_win_src_acceptor_var", 0.0),
                                ("dope_win_drn_donor_var", 0.0), ("dope_win_drn_acceptor_var", 0.0)),
        }
        zero = None
        for state_label, build in (("MODELLED", modelled), ("UNRESOLVED", unresolved)):
            for kind, fields in zero_fields.items():
                reset(build(), doped=sentinel)
                app.doping_kind.set(kind)
                for name, value in fields:
                    getattr(app, name).set(value)
                zero = observe(app, lambda: app.run_doping(silent=True))
                check_noop(zero)
        print("F zero concentration: known no-op for all 4 kinds on MODELLED and UNRESOLVED states (False, no attachment/ledger/event)")

        # ---- guards: each mutant observation must fail the SAME check, for the stated reason ----------------------------------------------
        def mut(o, **kw):
            m = dict(o)
            m.update(kw)
            return m

        ref, sup = obs_refused["B"], obs_a
        expect_fail(lambda: check_refused(mut(ref, ret=True)), "attachment 0 but True returned", "must return False")
        expect_fail(lambda: check_refused(mut(ref, log=ref["log"] + "DOPING APPLIED: UNIFORM")), "refusal printed DOPING APPLIED", "success wording")
        expect_fail(lambda: check_refused(mut(ref, res=object())), "refusal replaced last_doped_result", "last_doped_result untouched")
        expect_fail(lambda: check_refused(mut(ref, layer="doping")), "refusal switched the overlay", "must not switch the overlay")
        expect_fail(lambda: check_refused(mut(ref, hist=ref["hist0"] + ["Doping: Uniform"])), "refusal added success history", "no success history")
        expect_fail(lambda: check_refused(mut(ref, writes=1)), "refusal wrote doping", "writes=1")
        expect_fail(lambda: check_refused(mut(ref, solves=1)), "refusal solved", "solves=1")
        expect_fail(lambda: check_refused(mut(ref, att=("att:doping:1:2",))), "refusal created an attachment", "no active attachment")
        expect_fail(lambda: check_refused(mut(ref, modal=1)), "refusal raised a blocking modal", "must not raise a blocking modal")
        expect_fail(lambda: check_refused(mut(ref, log=ref["log"].replace(REQ, "value"))), "requested values not labelled", REQ)
        expect_fail(lambda: check_supported(mut(sup, ret=False)), "supported attachment judged a failure", "must return True")
        expect_fail(lambda: check_supported(mut(sup, new_att=[])), "supported without an attachment", "new active attachment")
        expect_fail(lambda: check_supported(mut(obs_comp, new_att=obs_comp["new_att"][:1]), n_attachments=2), "compensation collapsed to one attachment",
                    "exactly 2 new active attachment(s) expected, got 1")
        expect_fail(lambda: check_supported(mut(sup, log=sup["log"].replace("DECLARED ANALYTIC ACTIVE PROFILE", "profile"))),
                    "the success log does not say DECLARED ANALYTIC ACTIVE PROFILE", "DECLARED ANALYTIC ACTIVE PROFILE")
        expect_fail(lambda: check_chemical_recorded(mut(obs_g, ret=True), 2), "a CHEMICAL record returns True", "must not return True")
        expect_fail(lambda: check_chemical_recorded(mut(obs_g, res=object()), 2), "a CHEMICAL record replaces last_doped_result", "last_doped_result / history / overlay")
        expect_fail(lambda: check_chemical_recorded(mut(obs_g, layer="doping"), 2), "a CHEMICAL record switches the overlay", "last_doped_result / history / overlay")
        expect_fail(lambda: check_chemical_recorded(mut(obs_g, log=obs_g["log"] + "DOPING APPLIED"), 2), "a CHEMICAL record logs DOPING APPLIED", "applied/declared active doping")
        expect_fail(lambda: check_chemical_recorded(mut(obs_g, new_att=obs_g["new_att"][:1]), 2), "chemical compensation collapsed to one", "2 chemical attachment(s) expected")
        expect_fail(lambda: check_chemical_recorded(mut(obs_g, writes=1), 2), "a CHEMICAL record wrote to DevSim", "writes=1")
        expect_fail(lambda: check_noop(mut(zero, ret=True)), "zero request reported as applied", "expected False")
        expect_fail(lambda: check_noop(mut(zero, un=zero["un0"] + 1)), "zero request judged unsupported (ledger)", "neither attachment nor ledger")
        expect_fail(lambda: check_noop(mut(zero, new_events=list(ref["new_events"]))), "zero request judged unsupported (event)", "false unsupported event")
        expect_fail(lambda: check_noop(mut(zero, log=zero["log"] + REFUSED)), "zero request logged as refused", "applied, refused or chemical")
        print("GUARDS: 24 mutant observations were rejected for the stated reason")
    finally:
        gui.build_process_result = real["bpr"]
        devsim_backend.is_available, devsim_backend.require_devsim = real["avail"], real["req"]
        mesh_import_mod.import_process_result, mesh_import_mod.derive_barrier_covered_windows = real["imp"], real["bar"]
        doping_mapping_mod.apply_doping, gui.messagebox = real["apply"], real["mb"]
        gui.apply_uniform_doping = real["uni"]
        app.winfo_viewable = real["vis"]
        app.destroy()

    print("DOPING APPLICATION TRUTHFULNESS: supported / compensated / refused / chemical / reattach / zero-concentration contracts hold")


if __name__ == "__main__":
    main()
