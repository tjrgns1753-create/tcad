#!/usr/bin/env python3
"""Question C: an EXPLICITLY pre-built real planar Si/SiO2 stack (not a
numerical seed -- built directly via MakePlane, matching Rev.1/2's own
Matrix 4 methodology), at a given initial oxide thickness and grid.

usage: run_case_C.py OUT_DIR LABEL GRID_UM INITIAL_OXIDE_UM X_EXTENT Y_EXTENT
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

TIME_HOURS = 0.5
FIELD_X_UM = 0.0


def main():
    out_dir = Path(sys.argv[1]).resolve()
    label = sys.argv[2]
    grid_um = float(sys.argv[3])
    initial_oxide_um = float(sys.argv[4])
    x_extent = float(sys.argv[5])
    y_extent = float(sys.argv[6])
    out_dir.mkdir(parents=True, exist_ok=True)

    domain = session.create_domain(grid_um, x_extent, y_extent)
    vps.MakePlane(domain, 0.0, vps.Material.Si).apply()
    vps.MakePlane(domain, initial_oxide_um, vps.Material.SiO2, True).apply()
    before = snapshot_plain(domain, out_dir / f"{label}_before", x_um=FIELD_X_UM)

    model = build_model(TIME_HOURS)
    model.setInitialOxideThickness(0.002)
    # ^ harmless formality call: real pre-existing SiO2 already present,
    # so ViennaPS's own "no SiO2 layer found" seeding check does not fire
    # regardless of this argument (established in the prior audit's own
    # Matrix 4). The value passed here never matters when real oxide
    # already exists on the domain.

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
        "question": "C_explicit_planar_oxide_grid_sweep",
        "status": "ERROR" if error else "COMPLETED",
        "error": error,
        "elapsed_seconds": elapsed,
        "grid_delta_um": grid_um,
        "initial_oxide_um": initial_oxide_um,
        "x_extent_um": x_extent, "y_extent_um": y_extent,
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
            before_oxide = before["materials"]["SiO2"]["field_cross_section"]
            after_si = after["materials"]["Si"]["field_cross_section"]
            after_oxide = after["materials"]["SiO2"]["field_cross_section"]

            initial_oxide_measured = before_oxide["y_max_um"] - before_si["y_max_um"]
            final_oxide = after_oxide["y_max_um"] - after_si["y_max_um"]
            oxide_growth = final_oxide - initial_oxide_measured
            ambient_displacement = after_oxide["y_max_um"] - before_oxide["y_max_um"]
            silicon_consumed = before_si["y_max_um"] - after_si["y_max_um"]
            ratio = oxide_growth / silicon_consumed if silicon_consumed > 1e-12 else None
            predicted = None
            if parsed["b_um2_per_hour"] and parsed["b_over_a_um_per_hour"]:
                predicted = deal_grove_final_thickness(
                    parsed["b_um2_per_hour"], parsed["b_over_a_um_per_hour"],
                    initial_oxide_measured, TIME_HOURS)
            result["field_measurement"] = {
                "initial_oxide_thickness_measured_um": initial_oxide_measured,
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
                "grid_le_oxide_thickness": grid_um <= initial_oxide_um,
                "grid_eq_oxide_thickness": abs(grid_um - initial_oxide_um) < 1e-9,
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
