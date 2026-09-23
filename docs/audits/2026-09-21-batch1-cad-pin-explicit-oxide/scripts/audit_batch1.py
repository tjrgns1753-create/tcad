# -*- coding: utf-8 -*-
"""Audit for batch 1 (test_cad_negative_validation_real / test_pin_placement_validation_real).

1. builds the explicit initial Si/SiO2 stack exactly as both tests do and records the REQUESTED
   geometry, the NATIVE level-set tops and the EXPORTED-mesh measurements as separate blocks;
2. records the four computed pins with their evidence;
3. trap negative control: each of `vps.Oxidation` / `vps.Process` is independently trapped, counted,
   and restored -- also after an exception;
4. static AST scan of the helper and both tests for forbidden calls / lookups;
5. lists every line of the two tests that mentions oxidation, to show none claims a success.

Writes raw/audit_batch1.json.
"""
import ast
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
INTEGRATION = REPO / "tests" / "integration"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(INTEGRATION))

from tcad.backends.viennaps import session
import _explicit_oxide_fixture as fixture

module = session.require_viennaps()
out = {}

# ---- 1/2. geometry and pins (same parameters as the tests)
tmp = tempfile.mkdtemp(prefix="batch1_", dir=session._ascii_scratch_dir())
stack = fixture.build_explicit_si_sio2_stack(
    tmp, x_extent_um=10.0, y_extent_um=8.0, silicon_depth_um=5.0, oxide_top_um=0.4, grid_delta_um=0.2)
pins = fixture.compute_pins(stack, tolerance_um=0.05)
out["requested_input_geometry"] = stack.requested
out["native_level_set_top_um"] = stack.native_level_set_top_um
out["exported_mesh_measured"] = stack.measured
out["forbidden_call_counts_during_build"] = stack.forbidden_call_counts
out["native_vs_exported_difference_um"] = {
    "SiO2_top": stack.measured["sio2_top_y_exported"] - stack.native_level_set_top_um["SiO2"],
    "Si_top_vs_exported_interface_mean": (sum(stack.measured["si_sio2_interface_y_exported"]) / 2.0
                                          - stack.native_level_set_top_um["Si"]),
    "note": "exporter representation offset (grid-proportional, cause UNKNOWN); not oxide growth or Si consumption; no tolerance derived or asserted",
}
out["pins"] = {k: {"name": p.name, "wafer_x_um": p.x_um, "wafer_y_um": p.y_um, "domain_x_um": p.x_domain_um,
                   "basis": p.basis, "evidence": p.evidence} for k, p in pins.items()}

# ---- 3. trap negative control (each independently, and restoration after an exception)
control = {}
orig_ox, orig_proc = module.Oxidation, module.Process
for which in ("Oxidation", "Process"):
    try:
        with fixture.forbid_oxidation_and_process(module) as counts:
            getattr(module, which)()
    except AssertionError as exc:
        control[which] = {"raised": True, "message": str(exc)[:110], "counts": dict(counts)}
    control[which]["restored_after_exception"] = (module.Oxidation is orig_ox and module.Process is orig_proc)
out["trap_negative_control"] = control

# ---- 4. static scan
FORBIDDEN_CALL_NAMES = {"Oxidation", "Process", "setInitialOxideThickness", "_build_locos_geometry",
                        "LocosOxidation", "ThermalOxidation"}
scan = {}
for name in ("_explicit_oxide_fixture.py", "test_cad_negative_validation_real.py",
             "test_pin_placement_validation_real.py"):
    source = (INTEGRATION / name).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = sorted({ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)})
    bad_calls = [c for c in calls if c.split(".")[-1] in FORBIDDEN_CALL_NAMES]
    registry_lookups = [ast.unparse(n) for n in ast.walk(tree)
                        if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("registry.get")]
    imports = sorted({ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                      and re.search(r"oxidation|registry", ast.unparse(n))})
    scan[name] = {"forbidden_calls": bad_calls, "registry_lookups": registry_lookups,
                  "oxidation_or_registry_imports": imports,
                  "make_plane_calls": [c for c in calls if c.endswith("MakePlane")]}
out["static_scan_ast"] = scan

# ---- 5. every "oxidation" mention in the two tests
mentions = {}
for name in ("test_cad_negative_validation_real.py", "test_pin_placement_validation_real.py"):
    lines = (INTEGRATION / name).read_text(encoding="utf-8").splitlines()
    mentions[name] = [f"{i}: {ln.strip()}" for i, ln in enumerate(lines, 1) if re.search("oxidation|grown|grow", ln, re.I)]
out["oxidation_mentions_in_tests"] = mentions

(HERE.parent / "raw" / "audit_batch1.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("requested_input_geometry", "native_level_set_top_um",
                                       "native_vs_exported_difference_um", "trap_negative_control",
                                       "static_scan_ast", "oxidation_mentions_in_tests")}, indent=1, default=str))
print("EXPORTED:", {k: v for k, v in stack.measured.items() if k != "per_material"})
print("per_material:", stack.measured["per_material"])
print("AUDIT DONE")
