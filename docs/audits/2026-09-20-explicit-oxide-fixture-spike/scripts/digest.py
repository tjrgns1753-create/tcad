# -*- coding: utf-8 -*-
"""Print compact tables from raw/*.json (no measurement is made here; this
only reformats the raw JSON). Output is saved to raw/digest.txt by the caller."""
import json
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "raw"


def J(name):
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def f(x, n=6):
    if x is None:
        return "None"
    if isinstance(x, (int, bool)):
        return str(x)
    if isinstance(x, str):
        return x
    return f"{x:.{n}g}"


def h(t):
    print("\n" + "=" * 8 + " " + t + " " + "=" * 8)


d = J("exp1_deposited.json")
h("EXP1 SUPPORTED_DEPOSITED_OXIDE (rate 0.10 um/s)")
print("virgin Si top per grid:", {g: v["si_top"]["mean"] for g, v in d["virgin_si"].items()})
print("grid | t_s | requested | SiO2_mean | abs_err | rel_err | SiO2_min..max | Si_top(mean) | cols | area_SiO2/width | reload dArea | reload dSiO2 | counts(Ox,Proc,apply,seed)")
for c in d["cases"]:
    k = c["counts_after_build"]
    print(f"{c['grid']} | {c['time_s']} | {f(c['requested_um'])} | {f(c['sio2_thickness_col']['mean'])} | "
          f"{f(c['sio2_abs_err_mean_um'])} | {f(c['sio2_rel_err_mean'])} | "
          f"{f(c['sio2_thickness_col']['min'])}..{f(c['sio2_thickness_col']['max'])} | "
          f"{f(c['si_top_col']['mean'])} | {c['sio2_columns_present']} | {f(c['sio2_area_over_width_um'])} | "
          f"{c['reload'].get('area_diff')} | {f(c['reload'].get('sio2_thickness_mean_diff'))} | "
          f"({k['Oxidation_constructed']},{k['Process_constructed']},{k['Process_apply']},{k['Oxidation_setInitialOxideThickness']})")
    ch = c["chaining"]
    print(f"    chain etch(0.1um oxide-only): mats={ch.get('etch', {}).get('materials')} SiO2={f(ch.get('etch', {}).get('sio2_thickness_mean'))} "
          f"expected={f(ch.get('etch', {}).get('expected_sio2_after_um'))} Si_top={f(ch.get('etch', {}).get('si_top_mean'))} | "
          f"chain dep Si3N4: mats={ch.get('deposition_Si3N4', {}).get('materials')} Si3N4={f(ch.get('deposition_Si3N4', {}).get('si3n4_thickness_mean'))} "
          f"SiO2={f(ch.get('deposition_Si3N4', {}).get('sio2_thickness_mean'))} Si_top={f(ch.get('deposition_Si3N4', {}).get('si_top_mean'))} err={ch.get('error')}")

d = J("exp2_explicit.json")
h("EXP2 DIRECT_EXPLICIT_GEOMETRY (MakePlane)")
print("grid | requested | SiO2_mean | abs_err | rel_err | min..max | Si_top | SiO2 bottom | SiO2 top | cols | both mats | reload dArea | native LS ymax | counts")
for c in d["cases"]:
    k = c["counts_after_build_and_export"]
    print(f"{c['grid']} | {c['requested_um']} | {f(c['sio2_thickness_col']['mean'])} | {f(c['sio2_abs_err_mean_um'])} | "
          f"{f(c['sio2_rel_err_mean'])} | {f(c['sio2_abs_err_min_um'])}..{f(c['sio2_abs_err_max_um'])} | {f(c['si_top_col']['mean'])} | "
          f"{f(c['sio2_bottom_col']['mean'])} | {f(c['sio2_top_col']['mean'])} | {c['sio2_columns_present']} | "
          f"{c['both_materials_preserved']} | {c['reload'].get('area_diff')} | "
          f"{[f(x['y_max'], 5) for x in c['native']['level_set_surfaces']]} | "
          f"({k['Oxidation_constructed']},{k['Process_constructed']},{k['Process_apply']},{k['Oxidation_setInitialOxideThickness']})")
print("cross-grid same thickness:", json.dumps(d["cross_grid_same_thickness"]))
print("builder callables (AST):", d["builder_called_callables_ast"])
print("builder forbidden calls (AST):", d["builder_forbidden_calls_present_ast"])
print("SiO2 x-range vs Si x-range per case:", [(c["grid"], c["requested_um"], c["sio2_x_range"], c["si_x_range"]) for c in d["cases"]])

d = J("exp3_devsim_import.json")
h("EXP3 DevSim import + pin classifier")
for c in d["cases"]:
    es = c["edge_stats"]
    print(f"{c['kind'][:9]:9s} g={c['grid']} d={f(c['requested_um'])} regions={c.get('devsim_region_list')} "
          f"interfaces={c.get('devsim_interface_list')} contacts={c.get('devsim_contact_list')} nodes={c.get('node_counts')} "
          f"elems={c.get('element_counts')} shared_Si|SiO2_edges={es['shared_Si_SiO2_edges']} dupCoords={es['duplicate_coordinate_points']} "
          f"pins_ok={c['pins_all_expected_match']} err={c.get('import_error')}")
c0 = d["cases"][0]
print("pin outcomes (first case):", [(p["pin"], p["got"], p["expected"]) for p in c0["pins"]])
bad = [(c["kind"], c["grid"], c["requested_um"], [(p["pin"], p["got"], p["expected"]) for p in c["pins"] if p["match"] is False]) for c in d["cases"] if not c["pins_all_expected_match"]]
print("cases with a pin mismatch:", bad)
print("interface-pin outcomes:", sorted({(c["kind"][:9], c["grid"], [p["got"] for p in c["pins"] if p["pin"] == "at_Si_SiO2_interface"][0]) for c in d["cases"]}))
print("leftover devices:", d["devsim_devices_left_over"])

d = J("exp4_etch.json")
h("EXP4 etch suitability (R=0.30, d=0.30)")
print("prov | grid | scenario | B | Si_removed(export) | native Si LS ymax before->after | SiO2_removed | mats_after")
for c in d["cases"]:
    print(f"{c['provenance'][:6]} | {c['grid']} | {c['scenario']} | {f(c['budget_um'])} | {f(c.get('si_depth_removed'))} | "
          f"{f(c.get('native_si_levelset_ymax_before'), 4)}->{f(c.get('native_si_levelset_ymax_after'), 4)} | "
          f"{f(c.get('sio2_removed'))} | {c.get('materials_after')} {c.get('error') or ''}")
print("selectivity summary:", json.dumps(d["selectivity_summary"], indent=0))
for m in d["masked_window"]:
    print("masked window:", m["provenance"], m["grid"], m.get("materials_after"), m.get("error"))
    if "columns_after" in m:
        for x, v in m["columns_after"].items():
            print("   after x=", x, {k: [round(t, 4) for t in e] if e else None for k, e in v.items()})
        for x, v in m["columns_before"].items():
            print("   before x=", x, {k: [round(t, 4) for t in e] if e else None for k, e in v.items()})

d = J("exp5_thin_layer.json")
h("EXP5 thin layers")
print("kind | grid | req | req/grid | in_export | thickness_mean | rel_err | under_resolved_x count | WaferState exposed@x0 | export truth | verdict")
for c in d["cases"]:
    print(f"{c['kind'][:22]} | {c['grid']} | {f(c['requested_um'])} | {f(c['requested_over_grid'], 3)} | {c['layer_in_export']} | "
          f"{f(c['sio2_thickness_mean'])} | {f(c['sio2_rel_err_mean'])} | {c['under_resolved_x_count']} | "
          f"{c['wafer_state_exposed_at_x0']} | {c['export_truth_top_material_at_mid_column']} | {c['verdict']}")

d = J("exp6_wrapped_locos.json")
h("EXP6 wrapped LOCOS explicit stack")
for c in d["cases"]:
    le, ch = c["locos_export"], c["chainable"]
    print(f"g={c['grid']} pad_req={c['requested_pad_um']} ({f(c['pad_over_grid'], 3)}g) stack={c['stack_materials']} wrap={c['wrap_flags']} counts={c['counts_after_build']}")
    print(f"   pad measured (window col)={f(c['pad_thickness_window_col'])} err={f(c['pad_abs_err_um'])} locos_export mats={le['materials']} areas={ {k: f(v) for k, v in le['areas'].items()} }")
    print(f"   edge_pairs={le['edge_pairs']}")
    print(f"   columns x=0.0: { {k: [round(t, 4) for t in e] if e else None for k, e in le['columns']['0.0'].items()} }  x=0.8: { {k: [round(t, 4) for t in e] if e else None for k, e in le['columns']['0.8'].items()} }")
    print(f"   plain export (unregistered): {c['plain_export_unregistered']}")
    print(f"   devsim: {c['devsim']}")
    print(f"   chainable: reg {ch['registered_before']}->{ch['registered_after']} mats={ch['materials_after']} dArea={ {k: f(v) for k, v in ch['area_diff_vs_locos_export'].items()} } counts={ch['counts_after_fixup']}")
    print(f"   vpsd roundtrip: {c['vpsd_roundtrip']}")
print("chain onto chainable:", json.dumps(d["chain_onto_chainable"])[:1500])
print("leftover devices:", d["leftover_devsim_devices"])
for w in ("deposition", "etch"):
    p = RAW / f"exp6b_nofixup_{w}.json"
    print(f"6b no-fixup {w}:", p.read_text(encoding="utf-8").replace("\n", " ") if p.exists() else "NO JSON")

d = J("exp7_fresh_zero_duration.json")
h("EXP7 zero-duration / gate")
for c in d["cases"]:
    print(f"{c['label']:34s} mats={c.get('materials')} SiO2@x0={f(c.get('sio2_thickness_at_window_x0'))} req_pad={c['requested_pad_um']} "
          f"transition={c.get('state_transition')} counts={c['counts']} spy={[x[0] for x in c['oxidation_spy_calls']]}")
print("inherited fixture unchanged:", d["inherited_fixture_unchanged_after_all_runs"])

d = J("exp8_contact_mode.json")
h("EXP8 contactMode")
for k, v in d.items():
    print(k, "=>", json.dumps(v))

d = J("exp9_resist_and_wafer_state.json")
h("EXP9 resist over oxide fixtures + WaferState")
for r in d["resist"]:
    print(f"{r['provenance'][:6]} {r['resist']}: ws={r.get('wafer_state')} export={r.get('export_materials')} err={r.get('error')}")
    print("   export cols:", json.dumps(r.get("export_columns")))
    print("   after Si3N4 dep:", r.get("after_deposition_materials"), json.dumps(r.get("after_deposition_columns")))
print("locos WaferState:", json.dumps(d["locos_wafer_state"]))
print("locos export columns:", json.dumps(d["locos_export_columns"]))
print("counts:", d["counts_resist_section"], d["counts_total"])

d = J("exp10_export_offset.json")
h("EXP10 export-route interface offset (explicit planar, d=0.30)")
for c in d["cases"]:
    for k in ("project_save_volume_mesh", "vps_native_saveVolumeMesh", "save_locos_volume_mesh_per_material"):
        v = c[k]
        print(f"g={c['grid']} {k:38s} Si_top={f(v['si_top'])} ({f(v['si_top_over_grid'])} x grid)  SiO2 bottom={f(v['sio2_bottom'])} top={f(v['sio2_top'])} thickness={f(v['sio2_thickness'])}")
print("1/201 =", d["one_over_201"])
