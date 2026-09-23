#!/usr/bin/env python3
"""Question A (preflight capability inventory) + Question D (SiO2-material-
exists-but-insufficient counterexamples) + the .vpsd reload persistence
check. Single process (no solver hang risk -- most of this is either no
solve at all, or one bounded t=0.5hr solve on a small domain)."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_common import (  # noqa: E402
    capture_native_stdout, parse_native_log, snapshot_plain, build_model, session,
)
import viennaps as vps  # noqa: E402
import viennals as vls  # noqa: E402
from tcad.backends.viennaps.io import (  # noqa: E402
    is_locos_registered, register_locos_export, save_volume_mesh, _locos_export_hint,
)

OUT_DIR = Path(sys.argv[1]).resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)
results = {}


# ---------------------------------------------------------------------------
# A: what preflight information is actually available, natively, before
# ever calling Process().apply()?
# ---------------------------------------------------------------------------
def question_A():
    out = {}
    grid = 0.02
    domain = session.create_domain(grid, 2.0, 1.0)
    vps.MakePlane(domain, 0.0, vps.Material.Si).apply()
    vps.MakePlane(domain, 0.02, vps.Material.SiO2, True).apply()

    out["A1_grid_delta"] = {
        "available": True, "value": domain.getGridDelta(),
        "note": "domain.getGridDelta() -- reliable, always available.",
    }
    out["A2_materials_present_domain_wide"] = {
        "available": True,
        "value": sorted(str(m).split("'")[1] for m in domain.getMaterialsInDomain()),
        "note": "domain.getMaterialsInDomain() -- reliable for 'is material X present "
                "ANYWHERE in the domain', but this is a GLOBAL/domain-wide fact, not "
                "per-location. It cannot answer 'does THIS Si surface have oxide on it'. "
                "See D1/D3 below for the concrete failure this causes.",
    }
    out["A3_per_location_oxide_thickness"] = {
        "available": "NOT NATIVELY -- constructed manually by this audit",
        "note": "No ViennaPS/ViennaLS Python binding was found that returns "
                "'oxide thickness at x' directly. The only reliable route found "
                "in this investigation is: export a real triangulated mesh "
                "(save_volume_mesh or save_locos_volume_mesh) and intersect "
                "triangles at a chosen x (this audit's own "
                "measure_common.material_summary/_vertical_triangle_interval, "
                "copied from the already-reviewed Rev.3.1 methodology). This "
                "requires an EXPORT (i.e. real I/O, non-trivial for a coarse "
                "preflight check) and requires knowing in advance whether the "
                "domain needs the LOCOS-aware exporter (see A7 below).",
    }
    out["A4_min_oxide_band_domain_wide"] = {
        "available": "NOT NATIVELY",
        "note": "No single call returns 'the minimum oxide thickness anywhere in "
                "the domain'. Would have to be derived by sampling A3 at every x "
                "of interest -- expensive and geometry-shape-dependent (see D2: "
                "a sidewall needs a surface-normal sample, not a vertical one).",
    }
    out["A5_partial_oxide_multi_surface_trench_sidewall"] = {
        "available": "NOT NATIVELY, and NOT ATTEMPTED for a non-vertical surface",
        "note": "This audit's measurement contract (Item E) only supports a "
                "VERTICAL (same-x) cross-section. A trench sidewall's true "
                "oxide thickness is surface-NORMAL, not vertical, and would "
                "read as a much larger 'vertical' distance for a near-vertical "
                "wall. No attempt to build a surface-normal measurement was "
                "made this round -- left explicitly UNKNOWN, see D2 and the "
                "'not yet proven' list in REPORT.md.",
    }

    # A6/A7: LOCOS stack registration state and what it guarantees.
    materials = [vps.Material.Si, vps.Material.SiO2]
    wrap_flags = [False, True]
    out["A6_locos_registration_before"] = {
        "is_locos_registered": is_locos_registered(domain),
        "note": "False here because this domain was built directly via MakePlane, "
                "never passed through register_locos_export().",
    }
    register_locos_export(domain, materials, wrap_flags)
    out["A7_locos_registration_after_explicit_call"] = {
        "is_locos_registered": is_locos_registered(domain),
        "hint": [
            [str(m) for m in _locos_export_hint(domain)[0]],
            _locos_export_hint(domain)[1],
        ],
        "note": "register_locos_export() is an in-memory, id(domain)-keyed side "
                "table (tcad/backends/viennaps/io.py, _LOCOS_EXPORT_HINTS) -- it "
                "is NOT a property of the ViennaPS Domain object itself. Whether "
                "a domain 'needs' the LOCOS-aware exporter is knowledge that "
                "lives only in this Python-side table, populated by whichever "
                "ProcessStep built the domain.",
    }

    # A8: does that registration survive a real .vpsd save/reload round trip?
    with tempfile.TemporaryDirectory() as tmp:
        state_path = str(Path(tmp) / "state.vpsd")
        session.save_domain_state(domain, state_path)
        reloaded = session.load_domain_state(state_path)
        out["A8_locos_registration_survives_vpsd_reload"] = {
            "is_locos_registered_on_reloaded_domain": is_locos_registered(reloaded),
            "materials_native_on_reloaded_domain": sorted(
                str(m).split("'")[1] for m in reloaded.getMaterialsInDomain()),
            "num_level_sets_reloaded": int(reloaded.getNumberOfLevelSets()),
            "note": "reloaded is a NEW Python object with a NEW id() (Reader "
                    "creates a fresh vps.Domain() and populates it) -- so the "
                    "id(domain)-keyed registration on the ORIGINAL domain object "
                    "does not carry over. getMaterialsInDomain()/getNumberOfLevelSets() "
                    "ARE preserved (real domain-native state, not a Python side "
                    "table) -- so the geometry survives, but the WRAP-TOPOLOGY "
                    "KNOWLEDGE needed to export it correctly does not, unless the "
                    "caller re-registers it explicitly after every reload.",
        }
    return out


# ---------------------------------------------------------------------------
# D1: SiO2 exists in PART of the wafer (lateral), the rest is bare Si.
# Does a GLOBAL 'SiO2 present' check hide a LOCAL bare-Si surface?
# ---------------------------------------------------------------------------
def question_D1(label, oxide_thickness_um, grid_um=0.01):
    out_dir = OUT_DIR / label
    out_dir.mkdir(parents=True, exist_ok=True)
    x_extent, y_extent = 2.0, 1.0

    # getBoundaryConditions() segfaults on a domain with zero level sets
    # (documented elsewhere in this project, e.g. session.make_mask_spans's
    # own scratch-domain comment) -- read bcs from a disposable scratch
    # domain that already has one level set, exactly that established
    # pattern, before building the real domain from raw vls calls.
    scratch = session.create_domain(grid_um, x_extent, y_extent)
    vps.MakePlane(scratch, 0.0, vps.Material.Si).apply()
    bcs = scratch.getBoundaryConditions()

    domain = session.create_domain(grid_um, x_extent, y_extent)
    si_ls = vls.Domain([-x_extent / 2, x_extent / 2, -0.5, y_extent], bcs, grid_um)
    vls.MakeGeometry(si_ls, vls.Box([-x_extent / 2, -0.5], [x_extent / 2, 0.0])).apply()
    domain.insertNextLevelSetAsMaterial(si_ls, vps.Material.Si, False)

    # Oxide ONLY on the LEFT half (x in [-1, 0]); x in [0, 1] stays bare Si.
    oxide_ls = vls.Domain([-x_extent / 2, x_extent / 2, -0.5, y_extent], bcs, grid_um)
    oxide_box = vls.MakeGeometry(
        oxide_ls, vls.Box([-x_extent / 2, 0.0], [0.0, oxide_thickness_um]))
    oxide_box.setIgnoreBoundaryConditions([False, True, False])
    oxide_box.apply()
    domain.insertNextLevelSetAsMaterial(oxide_ls, vps.Material.SiO2, True)

    before = snapshot_plain(domain, out_dir / "before", x_um=-0.5, floor_depth_um=0.5)
    before_bare_side = snapshot_plain(domain, out_dir / "before_bare_side", x_um=0.5, floor_depth_um=0.5)

    model = build_model(0.5)
    model.setInitialOxideThickness(max(0.002, grid_um))
    with capture_native_stdout() as buf:
        vps.Process(domain, model).apply()
    buf.seek(0)
    native_log = buf.read().decode("utf-8", errors="replace")
    (out_dir / "native.log").write_text(native_log, encoding="utf-8")
    parsed = parse_native_log(native_log)

    after_oxide_side = snapshot_plain(domain, out_dir / "after_oxide_side", x_um=-0.5, floor_depth_um=0.5)
    after_bare_side = snapshot_plain(domain, out_dir / "after_bare_side", x_um=0.5, floor_depth_um=0.5)

    def cs(snap, mat):
        v = snap["materials"].get(mat)
        return v["field_cross_section"] if v else None

    oxide_side_before = cs(before, "SiO2")
    oxide_side_after = cs(after_oxide_side, "SiO2")
    bare_side_before_oxide = cs(before_bare_side, "SiO2")
    bare_side_after_oxide = cs(after_bare_side, "SiO2")
    bare_side_before_si = cs(before_bare_side, "Si")
    bare_side_after_si = cs(after_bare_side, "Si")

    result = {
        "label": label,
        "materials_native_before": before["materials_native"],
        "materials_native_after": after_oxide_side["materials_native"],
        "parsed_native_log": parsed,
        "global_getMaterialsInDomain_shows_SiO2": "SiO2" in after_oxide_side["materials_native"],
        "oxide_side_x=-0.5": {
            "before_cross_section": oxide_side_before, "after_cross_section": oxide_side_after,
        },
        "bare_side_x=0.5": {
            "before_SiO2_cross_section": bare_side_before_oxide,
            "after_SiO2_cross_section": bare_side_after_oxide,
            "before_Si_cross_section": bare_side_before_si,
            "after_Si_cross_section": bare_side_after_si,
            "did_bare_side_get_a_new_local_oxide": bare_side_after_oxide is not None,
            "did_bare_side_si_move_at_all": (
                (bare_side_after_si["y_max_um"] - bare_side_before_si["y_max_um"])
                if bare_side_before_si and bare_side_after_si else None
            ),
        },
    }
    return result


def question_D3_thick_elsewhere():
    """Same shape as D1, but the 'elsewhere' oxide is much thicker (0.2um,
    far above any grid-floor value) -- tests whether a THICK distant patch
    changes the answer for the still-bare region."""
    return question_D1("D3_thick_oxide_elsewhere_bare_target", oxide_thickness_um=0.2, grid_um=0.01)


def main():
    results["A_preflight_capabilities"] = question_A()
    results["D1_partial_lateral_oxide_thin"] = question_D1(
        "D1_partial_lateral_oxide_thin", oxide_thickness_um=0.02, grid_um=0.01)
    results["D3_thick_oxide_elsewhere"] = question_D3_thick_elsewhere()

    out_path = OUT_DIR / "results_AD.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("DONE:", out_path)
    print(json.dumps({
        "A8_survives_reload": results["A_preflight_capabilities"]["A8_locos_registration_survives_vpsd_reload"],
        "D1_bare_side_summary": results["D1_partial_lateral_oxide_thin"]["bare_side_x=0.5"],
        "D3_bare_side_summary": results["D3_thick_oxide_elsewhere"]["bare_side_x=0.5"],
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
