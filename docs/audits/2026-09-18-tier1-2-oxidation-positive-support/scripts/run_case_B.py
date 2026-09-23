#!/usr/bin/env python3
"""Question B: bare-Si, TRUE physical seed fixed at 0.002um (never
grid-floored -- bypasses thermal.py's own buggy formula entirely, calling
vps.Oxidation directly), across several grids. One process per grid.

usage: run_case_B.py OUT_DIR GRID_UM
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_common import (  # noqa: E402
    capture_native_stdout, parse_native_log, deal_grove_final_thickness,
    snapshot_plain, build_model, session,
)
import viennaps as vps  # noqa: E402

SEED_UM = 0.002
TIME_HOURS = 0.5
X_EXTENT_UM = 0.3
Y_EXTENT_UM = 0.5
FIELD_X_UM = 0.0


def main():
    out_dir = Path(sys.argv[1]).resolve()
    grid_um = float(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    label = f"B_grid_{grid_um:.4f}".replace(".", "p")

    domain = session.create_domain(grid_um, X_EXTENT_UM, Y_EXTENT_UM)
    vps.MakePlane(domain, 0.0, vps.Material.Si).apply()
    before = snapshot_plain(domain, out_dir / f"{label}_before", x_um=FIELD_X_UM)

    model = build_model(TIME_HOURS)
    model.setInitialOxideThickness(SEED_UM)

    started = time.time()
    error = None
    native_log = ""
    try:
        with capture_native_stdout() as buf:
            vps.Process(domain, model).apply()
        buf.seek(0)
        native_log = buf.read().decode("utf-8", errors="replace")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        try:
            buf.seek(0)
            native_log = buf.read().decode("utf-8", errors="replace")
        except Exception:
            pass
    elapsed = time.time() - started
    (out_dir / f"{label}_native.log").write_text(native_log, encoding="utf-8")

    parsed = parse_native_log(native_log)
    result = {
        "question": "B_bare_si_true_physical_seed_grid_sweep",
        "status": "ERROR" if error else "COMPLETED",
        "error": error,
        "elapsed_seconds": elapsed,
        "grid_delta_um": grid_um,
        "seed_um": SEED_UM,
        "time_hours": TIME_HOURS,
        "field_x_um": FIELD_X_UM,
        "parsed_native_log": parsed,
        "before": before,
    }

    if error is None:
        try:
            after = snapshot_plain(domain, out_dir / f"{label}_after", x_um=FIELD_X_UM)
            result["after"] = after
            before_si = before["materials"]["Si"]["field_cross_section"]
            before_oxide = (before["materials"].get("SiO2") or {}).get("field_cross_section")
            after_si = after["materials"]["Si"]["field_cross_section"]
            after_oxide = (after["materials"].get("SiO2") or {}).get("field_cross_section")

            initial_oxide = (before_oxide["y_max_um"] - before_si["y_max_um"]) if before_oxide else 0.0
            if after_oxide is None:
                result["field_measurement"] = {
                    "note": "no SiO2 at all in the exported after-mesh at this x -- "
                            "seed was never created or is unresolved/degenerate",
                    "final_oxide_thickness_um": 0.0,
                    "silicon_consumed_um": 0.0,
                }
            else:
                final_oxide = after_oxide["y_max_um"] - after_si["y_max_um"]
                oxide_growth = final_oxide - initial_oxide
                ambient_displacement = after_oxide["y_max_um"] - (before_oxide["y_max_um"] if before_oxide else 0.0)
                silicon_consumed = (before_si["y_max_um"] - after_si["y_max_um"])
                ratio = oxide_growth / silicon_consumed if silicon_consumed > 1e-12 else None
                predicted = None
                if parsed["b_um2_per_hour"] and parsed["b_over_a_um_per_hour"]:
                    predicted = deal_grove_final_thickness(
                        parsed["b_um2_per_hour"], parsed["b_over_a_um_per_hour"], SEED_UM, TIME_HOURS)
                result["field_measurement"] = {
                    "initial_oxide_thickness_um": initial_oxide,
                    "final_oxide_thickness_um": final_oxide,
                    "oxide_growth_um": oxide_growth,
                    "ambient_surface_displacement_um": ambient_displacement,
                    "silicon_consumed_um": silicon_consumed,
                    "growth_identity_residual_um": oxide_growth - ambient_displacement - silicon_consumed,
                    "oxide_growth_over_silicon_consumed": ratio,
                    "deal_grove_final_thickness_um": predicted,
                    "deal_grove_error_um": (final_oxide - predicted) if predicted is not None else None,
                    "deal_grove_relative_error_percent": (
                        100.0 * (final_oxide - predicted) / predicted
                        if predicted not in (None, 0.0) else None
                    ),
                    "seed_resolved_in_grid": grid_um <= SEED_UM,
                    "no_growth_but_reported_complete": (
                        parsed["completion_log_found"] and abs(oxide_growth) < 1e-6
                    ),
                }
        except Exception as exc:
            result["measurement_error"] = f"{type(exc).__name__}: {exc}"

    result_path = out_dir / f"result_{label}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"result_path": str(result_path), "status": result["status"],
                       "elapsed": elapsed, "field_measurement": result.get("field_measurement")}, indent=2))
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
