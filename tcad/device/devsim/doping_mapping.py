#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Write real per-node NetDoping into DevSim from a WaferState.

2026-09-03 dopant-state-unification, Task 8. `apply_doping()` used to
build one symbolic DevSim `node_model(equation=...)` string per doping
KIND ("uniform"/"step_junction"/"gaussian_implant"/"implant_windows"),
each its own branch. That kind-dispatch is retired for the real,
production per-node path below: WaferState.net_doping_at() (Task 2) is
evaluated in real Python at every REAL DevSim mesh node -- via
`get_node_model_values(name="x"/"y")`, the same real API
tcad/device/devsim/voltage_probe.py already uses -- and the results are
written back with `set_node_values`. This works identically regardless
of how many DopantProfiles WaferState carries, which models produced
them, or whether they came from one doping call or several accumulated
ones -- there is no longer a "kind" this module needs to know about at
all.

Classification, explicit (not physical validation -- see Task 1's own
tests/integration/test_dopant_profile_matches_devsim_real.py for that):
this module's own real-DevSim tests
(tests/integration/test_doping_mapping_per_node_real.py and the
pre-existing regression suite this task re-verified) are a
WaferState<->DevSim COUPLING / NUMERICAL-CONSISTENCY check -- they
confirm the write/read pipeline transports WaferState's own numbers
into DevSim without transcription or unit-conversion error, not that
the underlying Gaussian/step-junction/etc. formula is itself physically
correct (already established separately).

Real API used (verified against installed DevSim 2.10.1, already used
elsewhere in this project -- tcad/device/devsim/semiconductor_equation.py,
tcad/device/devsim/voltage_probe.py):

    devsim.get_node_model_values(device=, region=, name="x"/"y")
    devsim.node_model(device=, region=, name=<model>, equation="0")  # register before set
    devsim.set_node_values(device=, region=, name=<model>, values=[...])

`node_model(..., equation="0")` before `set_node_values` is required --
a node model must be REGISTERED before its values can be overwritten,
the same real DevSim requirement this project's own
semiconductor_equation.py already relies on.

Barrier exclusion (SiO2 blocking doping, "SiO2 no longer silently fails
to block doping") is kept as `apply_doping()`'s own explicit
`exclude_windows`/`exclude_axis` parameters, NOT folded into
WaferState's geometry gating. Investigated directly this task (not
guessed): WaferState.exposed_material_at() answers a different
question -- "what is the single TOPMOST material at this x right now"
-- with no thickness threshold, so a real barrier-windows test
(derive_barrier_covered_windows on an oxidation->litho->etch flow using
a "PHS" resist mask over the SiO2) shows exposed_material_at() reading
back "PHS" (whatever happens to be stacked on top -- here the leftover
resist), never "SiO2" itself, and moreover has no `min_barrier_
thickness_um` concept to reproduce at all -- confirmed by direct
execution, see docs/investigation_log.md. Even where the two happen to
agree numerically (host_material not exposed -> profile contribution
is 0 either way), WaferState's own `_polarity_sum()` additionally
attaches an UNSUPPORTED_BY_MODEL physics_status entry for any category
not classified in MATERIAL_CHANGE_KIND_BY_CATEGORY (which "doping"
never is) -- mislabeling a well-understood, deterministic effect (an
oxide barrier blocking ion implantation) as "no model exists for this"
would be actively wrong, not merely redundant. So exclusion stays a
device-layer masking concern here, applied as a real zero (matching
the old equation-string behavior exactly, no physics_status flag),
kept OUT of WaferState/DopantProfile deliberately (also documented on
DopantProfile's own module docstring).

RECOVERY, found necessary by real execution against this project's
existing regression suite (not guessed): calling
WaferState.net_doping_at() completely unconditionally at every node --
the literal, first-draft implementation of this task -- made EVERY
pre-existing doping regression test in this project fail, because
WaferState.exposed_material_at() is a column-max-at-x SURFACE
heuristic (it tracks only the single topmost material at each x,
ignoring a node's own depth) that gets "shadowed" by any co-located
surface feature -- most commonly a leftover litho Mask/resist this
project's own litho panel does not yet strip (CLAUDE.md OPEN item 3,
"PR Strip removes nothing") -- even for a BULK node that is still
genuinely the declared host_material. `apply_doping()` therefore
RECOVERS any profile whose own `host_material` equals the DevSim
`region` actually being written whenever the coarse surface heuristic
excluded it: DevSim's own region membership (every node here comes
from `get_node_model_values(..., region=region, ...)`) is definitive,
node-exact proof of that node's material, strictly stronger evidence
than the column-max approximation. This does not defeat the real
CE-1/CE-2 removal/conversion semantics (spec Sec3/Sec6, Tasks 6-7):
if `region`'s material had genuinely been removed or converted away at
this x by a later step, there would be no DevSim node here to iterate
over at all. Verified node-for-node (not merely "tests pass"): on the
project's own known-passing 4x3um implant_windows recipe, the RECOVERED
per-node NetDoping is bit-identical (0 of 11269 nodes differ) to
`apply_doping_symbolic()`'s original equation-string output on the
identical mesh.

`apply_doping_symbolic()` below is the OLD kind-based equation-string
implementation, preserved VERBATIM under a new name -- not retired.
tcad.characterization.robust_iv_sweep.ramp_doping_to_equilibrium is a
real, separately-verified (test_robust_iv_sweep_real.py), out-of-scope-
for-this-task doping-LEVEL CONTINUATION strategy: it re-registers
NetDoping at a sequence of increasing `window_scale` multipliers
(1e-3 -> 1.0) and re-solves at each step, which is a SOLVE-STRATEGY
parameter, not part of what any DopantProfile/WaferState declares (see
dopant_profile.py's own module docstring: "window_scale ... a
solve-strategy detail, not part of what the process declares"). A
per-node WaferState evaluation has no way to express "the same profile,
scaled by 0.001" without WaferState itself gaining a solve-strategy
concept it was deliberately never given -- so that one real caller
keeps using the original symbolic mechanism under its own name, and
every OTHER caller (enumerated by `grep -rn "apply_doping(" tests/
tcad/`) moved to the new per-node `apply_doping()`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, TYPE_CHECKING

from tcad.device.devsim import backend
from tcad.mesh.interface import DopingProfile

if TYPE_CHECKING:
    from tcad.physics.wafer_state import WaferState


def _is_excluded(
    x_um: float,
    y_um: float,
    exclude_windows: Optional[List[Dict[str, float]]],
    exclude_axis: str,
) -> bool:
    """True inside any exclusion window -- same real windows
    derive_barrier_covered_windows() produces, same non-overlapping
    assumption the old `_exclusion_factor_expr` equation string relied
    on (only their union matters here)."""
    if not exclude_windows:
        return False
    value = x_um if exclude_axis == "x" else y_um
    return any(w["min_um"] <= value <= w["max_um"] for w in exclude_windows)


def apply_doping(
    device: str,
    region: str,
    state: "WaferState",
    length_scale_to_cm: float = 1.0,
    exclude_windows: Optional[List[Dict[str, float]]] = None,
    exclude_axis: str = "x",
) -> Optional[dict]:
    """Real per-node NetDoping (spec 2026-09-03 Sec10) -- replaces
    every prior kind-based symbolic-equation branch. Works identically
    regardless of how many DopantProfiles WaferState carries or which
    models produced them.

    device, region : the real DevSim device/region NetDoping is
        written into (e.g. from `import_process_result(...).device` /
        `.regions[0]`).
    state : the WaferState whose accumulated dopant_profiles are
        evaluated at every real mesh node.
    length_scale_to_cm : MUST match whatever value the device's own
        import_process_result() call used (this project's existing
        convention, already documented on the pre-existing
        apply_doping()'s own length_scale_to_cm parameter -- preserved
        here, not reinvented), so DevSim's own "x"/"y" node values
        convert back into the same um scale WaferState.net_doping_at()
        expects.
    exclude_windows, exclude_axis : real SiO2-barrier-exclusion window
        list (see derive_barrier_covered_windows() in
        tcad.device.devsim.mesh_import) and the axis it is measured
        along. When None (default), behavior is unchanged. See this
        module's own docstring for why this stays a parameter here
        rather than being folded into WaferState.

    Writes exactly ONE region per call (unlike apply_doping_symbolic()
    below, which loops over every `doping.regions` entry) -- safe today
    because every real DopingProfile in this project has exactly one
    region (confirmed by grep), but a future multi-region profile would
    need one apply_doping() call per region, not a single call.

    Returns the aggregated `physics_status` dict across every node that
    had a GENUINELY unresolved UNSUPPORTED_BY_MODEL gap (see
    WaferState.net_doping_at), or None if none did -- mirrors the
    existing project convention of surfacing `physics_status` from a
    doping-application call. A gap that the RECOVERY step below actually
    resolved (host_material == region) is never included here -- it
    would be factually wrong to flag a contribution as excluded when it
    was, in fact, written to the device.
    """
    module = backend.require_devsim()

    xs_native = module.get_node_model_values(device=device, region=region, name="x")
    ys_native = module.get_node_model_values(device=device, region=region, name="y")

    donors: List[float] = []
    acceptors: List[float] = []
    nets: List[float] = []
    all_entries: List[dict] = []

    # Any gap entry whose note reports THIS region as no-longer-exposed
    # is, by construction (see the RECOVERY loop below: it recovers
    # every profile with host_material == region whenever the exposure
    # gate excluded it -- the exact same condition net_doping_at() uses
    # to decide whether to emit such an entry in the first place), ALWAYS
    # recovered at that same node. Used only to drop those now-stale
    # entries (Important #2) -- an entry about some OTHER host_material
    # (a profile this call site cannot recover, since it never targets
    # `region`) is left untouched, since that one really is unresolved.
    region_gap_prefix = f"{region} no longer exposed"

    # Memoized across the whole node loop (Important #3):
    # state.exposed_material_at(x_um) depends only on x_um, not on which
    # profile is being checked, and is itself a linear scan over every
    # WaferState._Cell (one per mesh triangle -- tens of thousands on a
    # refined device). The old code called it once per (node, profile)
    # pair inside the RECOVERY loop below; hoisting it here computes it
    # once per DISTINCT x_um for the entire call. Keyed on a rounded x
    # rather than the raw float: many real DevSim mesh nodes down one
    # column share the same x, but this module has no guarantee their
    # float64 bit patterns are identical (an unstructured triangulation,
    # not a structured grid), so round to 9 decimals -- this project's
    # own established mesh-coordinate precision (see prepare_domain()'s
    # trenchWidth rounding, tcad/backends/viennaps/session.py).
    exposed_cache: Dict[float, Optional[str]] = {}

    for x_native, y_native in zip(xs_native, ys_native):
        x_um = x_native / length_scale_to_cm
        y_um = y_native / length_scale_to_cm

        if _is_excluded(x_um, y_um, exclude_windows, exclude_axis):
            donors.append(0.0)
            acceptors.append(0.0)
            nets.append(0.0)
            continue

        result = state.net_doping_at(x_um, y_um)
        donor = result.donor_concentration
        acceptor = result.acceptor_concentration

        cache_key = round(x_um, 9)
        if cache_key in exposed_cache:
            exposed = exposed_cache[cache_key]
        else:
            exposed = state.exposed_material_at(x_um)
            exposed_cache[cache_key] = exposed

        # RECOVERY, found necessary by real execution, not guessed:
        # every node here comes from devsim.get_node_model_values(...,
        # region=region, ...) -- so DevSim's OWN region membership is
        # already definitive, node-exact proof this node's material IS
        # `region`. That is strictly stronger evidence than
        # WaferState.exposed_material_at()'s check inside
        # net_doping_at() above, which tracks only the SINGLE topmost
        # material at this x (ignoring the node's own y/depth) -- so an
        # unrelated, co-located surface feature at the same x (a
        # leftover litho Mask/resist that was never stripped, see
        # CLAUDE.md OPEN item 3 "PR Strip removes nothing"; a thin
        # native oxide seed; any material merely stacked on top) can
        # "shadow" a BULK node that is still genuinely `region`'s
        # material, and net_doping_at() then wrongly zeroes it.
        # Confirmed by direct execution: routing every doping
        # regression test in this project through net_doping_at()
        # unconditionally, with no recovery, made EVERY ONE of them
        # fail against real, ViennaPS-masked meshes (materials list
        # always includes a leftover 'Mask' -- this project's litho
        # panel does not yet call domain.removeMaterial(), a separate,
        # already-tracked open item, not something this task fixes).
        # This does NOT defeat the real CE-1/CE-2 removal/conversion
        # semantics (spec Sec3/Sec6, Tasks 6-7): if `region`'s material
        # had genuinely been removed or converted away at this x by a
        # LATER step, there would be no DevSim node here to iterate at
        # all -- the node existing in the CURRENT mesh's `region` is
        # proof positive the material is still there RIGHT NOW,
        # independent of process history. It also does not reintroduce
        # SiO2-barrier-exclusion (a real, DIFFERENT masking concept,
        # see this module's own top docstring) -- that is handled
        # earlier, unconditionally, by exclude_windows/exclude_axis
        # above, which `continue`s before this point is ever reached.
        for p in state.dopant_profiles:
            if p.host_material != region:
                continue
            if exposed == p.host_material:
                continue  # net_doping_at() already included this one
            magnitude = p.concentration_at(x_um, y_um)
            if p.polarity == "donor":
                donor += magnitude
            else:
                acceptor += magnitude

        # Important #2: drop any gap entry that RECOVERY (just above)
        # actually resolved -- see region_gap_prefix's own comment.
        if result.physics_status is not None:
            all_entries.extend(
                e for e in result.physics_status["entries"]
                if not e.get("note", "").startswith(region_gap_prefix)
            )

        donors.append(donor)
        acceptors.append(acceptor)
        nets.append(donor - acceptor)

    module.node_model(device=device, region=region, name="Donors", equation="0")
    module.set_node_values(device=device, region=region, name="Donors", values=donors)
    module.node_model(device=device, region=region, name="Acceptors", equation="0")
    module.set_node_values(device=device, region=region, name="Acceptors", values=acceptors)
    module.node_model(device=device, region=region, name="NetDoping", equation="0")
    module.set_node_values(device=device, region=region, name="NetDoping", values=nets)

    if not all_entries:
        return None
    from tcad.physics.values import combine, Resolution

    resolutions = [Resolution(e["resolution"]) for e in all_entries]
    return {"resolution": combine(resolutions).value, "entries": all_entries, "notes": []}


def _exclusion_factor_expr(
    exclude_windows: Optional[List[Dict[str, float]]],
    axis: str,
    length_scale_to_cm: float,
) -> str:
    """DevSim equation string: 1 everywhere, 0 inside any exclusion
    window. Windows are assumed non-overlapping (derive_barrier_covered_
    windows() only ever emits merged, disjoint windows), so summing
    each window's step()*step() indicator and subtracting from 1 is
    safe -- same step()-based windowing mechanism implant_windows
    already uses (see apply_doping_symbolic's own docstring), reused
    rather than inventing a second one. Used only by
    apply_doping_symbolic() below.
    """
    if not exclude_windows:
        return "1"
    terms = []
    for w in exclude_windows:
        lo = w["min_um"] * length_scale_to_cm
        hi = w["max_um"] * length_scale_to_cm
        terms.append(f"step({axis}-({lo}))*step(({hi})-{axis})")
    return "(1 - (" + " + ".join(terms) + "))"


def apply_doping_symbolic(
    device: str,
    doping: DopingProfile,
    length_scale_to_cm: float = 1.0,
    window_scale: float = 1.0,
    exclude_windows: Optional[List[Dict[str, float]]] = None,
    exclude_axis: str = "x",
) -> None:
    """The ORIGINAL kind-based symbolic-equation NetDoping writer,
    preserved verbatim (only renamed) -- see this module's own top
    docstring for why. The ONLY real caller is
    tcad.characterization.robust_iv_sweep.ramp_doping_to_equilibrium,
    which needs `window_scale` (a solve-strategy doping-level
    continuation multiplier that has no WaferState/DopantProfile
    equivalent, deliberately). Every other real caller in this project
    uses `apply_doping()` (the new per-node WaferState path) instead.

    Real API used (verified against installed DevSim 2.10.1 — same
    node_model() used elsewhere in this project, confirmed here specifically
    for a constant-expression doping value by running it and reading back
    get_node_model_values(), and cross-checked physically: the resulting
    device solve's built-in potential matched the analytic
    V_t*ln(NetDoping/n_i) prediction for both signs of doping — see
    tests/test_phase7_doping_real.py):

        devsim.node_model(device=, region=, name="NetDoping", equation=str(value))

    Real API used (verified against installed DevSim 2.10.1 — confirmed
    here specifically for both a constant-expression doping value and a
    step-junction doping value, by running each and reading back
    get_node_model_values(), and cross-checked physically: the resulting
    equilibrium solve's potential spread matched the analytic
    V_t*ln(Nd*Na/n_i^2) built-in potential for a step junction to full
    floating-point precision — see tests/test_phase8_pn_junction_real.py):

        devsim.node_model(device=, region=, name="NetDoping", equation=str(value))
        # step junction (real DevSim built-in step() function, found by
        # reading devsim_data/examples/diode/diode_common.py's own
        # SetNetDoping(), not guessed):
        devsim.node_model(device=, region=, name="Donors",
                           equation=f"{donor}*step(x-({junction_position}))")
        devsim.node_model(device=, region=, name="Acceptors",
                           equation=f"{acceptor}*step(({junction_position})-x)")
        devsim.node_model(device=, region=, name="NetDoping",
                           equation="Donors-Acceptors")

    "uniform", "step_junction", "gaussian_implant", and "implant_windows"
    are implemented. gaussian_implant's equation ("exp"/"^" confirmed
    supported by DevSim's own equation parser:
    devsim/python_packages/simple_physics.py uses both, e.g.
    `"n_i*exp(Potential/V_t)"`, `"NetDoping^2"`) sets NetDoping directly to
    a Gaussian, the same way "uniform" sets it directly to a constant — no
    separate Donors/Acceptors split, since a Gaussian implant isn't a
    donor/acceptor pair the way a step junction is:

        devsim.node_model(device=, region=, name="NetDoping",
            equation=f"{peak}*exp(-(({axis}-({position}))^2)/(2*({straggle})^2))")

    implant_windows sets NetDoping to a background constant plus zero or
    more `step()*step()` window terms SUMMED on top — real DevSim
    `step(x)*step(-x)`-style windowing (the same `step()` function
    diode_common.py uses for the step junction above), confirmed by direct
    execution reading get_node_model_values() back and comparing to an
    independently-computed value per node (0.000e+00 max error across all
    nodes — see test_implant_windows_doping_real.py):

        devsim.node_model(device=, region=, name="NetDoping",
            equation=(
                f"{background}"
                f" + {conc_1}*step({axis}-({min_1}))*step(({max_1})-{axis})"
                f" + {conc_2}*step({axis}-({min_2}))*step(({max_2})-{axis})"
                " + ..."
            ))

    length_scale_to_cm : must match whatever
        tcad.device.devsim.mesh_import.import_process_result's
        length_scale_to_cm was for this device, so junction_position_um
        (given in the same "um" units as ProcessResult, see
        tcad/mesh/interface.py) converts into the same coordinate scale
        DevSim's own "x"/"y"/"z" node models use. Irrelevant for
        "uniform" doping, which has no position dependence. Default 1.0
        matches the default (and every Phase 7 caller's) import scale.

    window_scale : multiplies every implant WINDOW's concentration (not
        the background), for "implant_windows" only. Default 1.0 leaves
        every existing caller byte-identical. Its purpose is
        doping-level CONTINUATION: re-registering NetDoping at a
        sequence of increasing scales, re-solving at each, lets the
        equilibrium solve reach a heavily-doped target it cannot reach
        in one step — see
        tcad.characterization.robust_iv_sweep.ramp_doping_to_equilibrium,
        which is the only intended caller.

    exclude_windows, exclude_axis : see apply_doping()'s own docstring
        above -- identical real semantics, just expressed as an equation
        string here instead of a numeric mask.
    """
    module = backend.require_devsim()
    exclusion = _exclusion_factor_expr(exclude_windows, exclude_axis, length_scale_to_cm)

    if doping.kind == "uniform":
        for region_doping in doping.regions:
            module.node_model(
                device=device,
                region=region_doping.region,
                name="NetDoping",
                equation=f"({region_doping.net_doping_cm3})*{exclusion}",
            )
    elif doping.kind == "step_junction":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            position_native = region_doping.junction_position_um * length_scale_to_cm
            module.node_model(
                device=device, region=region_doping.region, name="Donors",
                equation=f"{region_doping.donor_conc_cm3}*step({axis}-({position_native}))",
            )
            module.node_model(
                device=device, region=region_doping.region, name="Acceptors",
                equation=f"{region_doping.acceptor_conc_cm3}*step(({position_native})-{axis})",
            )
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=f"(Donors-Acceptors)*{exclusion}",
            )
    elif doping.kind == "gaussian_implant":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            position_native = region_doping.peak_position_um * length_scale_to_cm
            straggle_native = region_doping.straggle_um * length_scale_to_cm
            gaussian_expr = (
                f"{region_doping.peak_conc_cm3}*exp(-(({axis}-({position_native}))^2)"
                f"/(2*({straggle_native})^2))"
            )
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=f"({gaussian_expr})*{exclusion}",
            )
    elif doping.kind == "implant_windows":
        for region_doping in doping.regions:
            axis = region_doping.junction_axis
            background = region_doping.net_doping_cm3 or 0.0
            terms = [str(background)]
            for window in region_doping.implant_windows or []:
                lo_native = window["min_um"] * length_scale_to_cm
                hi_native = window["max_um"] * length_scale_to_cm
                terms.append(
                    f"{window['conc_cm3'] * window_scale}*step({axis}-({lo_native}))"
                    f"*step(({hi_native})-{axis})"
                )
            windows_expr = " + ".join(terms)
            module.node_model(
                device=device, region=region_doping.region, name="NetDoping",
                equation=f"({windows_expr})*{exclusion}",
            )
    else:
        raise NotImplementedError(
            f"doping_mapping.apply_doping_symbolic supports kind in "
            f"('uniform', 'step_junction', 'gaussian_implant', "
            f"'implant_windows') so far, got {doping.kind!r}"
        )
