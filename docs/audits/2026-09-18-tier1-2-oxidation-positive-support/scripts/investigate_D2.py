#!/usr/bin/env python3
"""D2: top surface has oxide, trench FLOOR (a real bare Si surface inside
a partially-oxidized domain, geometrically enclosed rather than laterally
adjacent like D1) does not. Separate process (own segfault-trap risk from
raw vls geometry construction)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_common import capture_native_stdout, parse_native_log, snapshot_plain, build_model, session
import viennaps as vps  # noqa: E402
import viennals as vls  # noqa: E402

OUT_DIR = Path(sys.argv[1]).resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)

grid_um = 0.02
x_extent, y_extent = 3.0, 1.5
bounds = [-x_extent / 2, x_extent / 2, -1.0, y_extent]

scratch = session.create_domain(grid_um, x_extent, y_extent)
vps.MakePlane(scratch, 0.0, vps.Material.Si).apply()
bcs = scratch.getBoundaryConditions()

# Si block y=[-1,0] MINUS a trench notch x=[-0.3,0.3], y=[-0.5,0].
si_block = vls.Domain(bounds, bcs, grid_um)
vls.MakeGeometry(si_block, vls.Box([-x_extent / 2, -1.0], [x_extent / 2, 0.0])).apply()
trench = vls.Domain(bounds, bcs, grid_um)
trench_geom = vls.MakeGeometry(trench, vls.Box([-0.3, -0.5], [0.3, 0.1]))
trench_geom.setIgnoreBoundaryConditions([False, True, False])
trench_geom.apply()
vls.BooleanOperation(si_block, trench, vls.BooleanOperationEnum.RELATIVE_COMPLEMENT).apply()

domain = session.create_domain(grid_um, x_extent, y_extent)
domain.insertNextLevelSetAsMaterial(si_block, vps.Material.Si, False)

# Oxide ONLY on the two flat mesa tops (x < -0.3 and x > 0.3), NOT over
# the trench floor/sidewalls (x in [-0.3, 0.3]).
oxide_thickness = 0.02
left_ox = vls.Domain(bounds, bcs, grid_um)
left_geom = vls.MakeGeometry(left_ox, vls.Box([-x_extent / 2, 0.0], [-0.3, oxide_thickness]))
left_geom.setIgnoreBoundaryConditions([False, True, False])
left_geom.apply()
right_ox = vls.Domain(bounds, bcs, grid_um)
right_geom = vls.MakeGeometry(right_ox, vls.Box([0.3, 0.0], [x_extent / 2, oxide_thickness]))
right_geom.setIgnoreBoundaryConditions([False, True, False])
right_geom.apply()
vls.BooleanOperation(left_ox, right_ox, vls.BooleanOperationEnum.UNION).apply()
domain.insertNextLevelSetAsMaterial(left_ox, vps.Material.SiO2, True)

before_mesa = snapshot_plain(domain, OUT_DIR / "D2_before_mesa", x_um=-1.0, floor_depth_um=1.0)
before_trench_floor = snapshot_plain(domain, OUT_DIR / "D2_before_trench_floor", x_um=0.0, floor_depth_um=1.0)

model = build_model(0.5)
model.setInitialOxideThickness(max(0.002, grid_um))
with capture_native_stdout() as buf:
    vps.Process(domain, model).apply()
buf.seek(0)
native_log = buf.read().decode("utf-8", errors="replace")
(OUT_DIR / "D2_native.log").write_text(native_log, encoding="utf-8")
parsed = parse_native_log(native_log)

after_mesa = snapshot_plain(domain, OUT_DIR / "D2_after_mesa", x_um=-1.0, floor_depth_um=1.0)
after_trench_floor = snapshot_plain(domain, OUT_DIR / "D2_after_trench_floor", x_um=0.0, floor_depth_um=1.0)


def cs(snap, mat):
    v = snap["materials"].get(mat)
    return v["field_cross_section"] if v else None


result = {
    "label": "D2_top_oxide_trench_floor_bare",
    "grid_delta_um": grid_um,
    "oxide_thickness_um": oxide_thickness,
    "parsed_native_log": parsed,
    "materials_native_before": before_mesa["materials_native"],
    "materials_native_after": after_mesa["materials_native"],
    "mesa_top_x=-1.0": {
        "before_SiO2": cs(before_mesa, "SiO2"), "after_SiO2": cs(after_mesa, "SiO2"),
        "before_Si": cs(before_mesa, "Si"), "after_Si": cs(after_mesa, "Si"),
    },
    "trench_floor_x=0.0": {
        "before_SiO2": cs(before_trench_floor, "SiO2"), "after_SiO2": cs(after_trench_floor, "SiO2"),
        "before_Si": cs(before_trench_floor, "Si"), "after_Si": cs(after_trench_floor, "Si"),
        "did_trench_floor_get_new_oxide": cs(after_trench_floor, "SiO2") is not None,
        "did_trench_floor_si_move": (
            (cs(after_trench_floor, "Si")["y_max_um"] - cs(before_trench_floor, "Si")["y_max_um"])
            if cs(before_trench_floor, "Si") and cs(after_trench_floor, "Si") else None
        ),
    },
    "note": "Sidewall itself (surface-normal thickness at the vertical trench "
            "wall) is NOT measured here -- this audit's cross-section method is "
            "vertical-only (Item E's own scope). Only the horizontal trench "
            "FLOOR is checked, as a real enclosed bare-Si surface. The sidewall "
            "remains explicitly UNKNOWN.",
}

out_path = OUT_DIR / "results_D2.json"
out_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
print(json.dumps(result, indent=2, default=str))
print("DONE:", out_path)
