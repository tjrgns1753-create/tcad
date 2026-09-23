"""Print the tables of REPORT.md from raw/matrix_results.json (pure post-processing; no ViennaPS needed)."""
import json
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
data = json.loads((AUDIT / "raw" / "matrix_results.json").read_text(encoding="utf-8"))
runs = data["runs"]
THR = ("1e-12", "1e-09", "1e-06", "0.0001")


def short(r):
    return f"g={r['grid_um']:<5} {r['model'][:3]}/{r['recipe_kind'][:3]}{'*' if r['label'].endswith('REPEAT') else ' '}"


out = []
P = out.append

P("== T1  matrix (13 runs); '*' = repeat of directional/selective at 0.05 on a separate copy of the same baseline")
for r in runs:
    P(f"#{r['run_number']:>2} {short(r)} etch {r['etch_elapsed_s']:>5}s  oxidation_calls={r['oxidation_calls']}  "
      f"native-vs-export: SiO2={r['classification_native_vs_export']['SiO2']:<20} Mask={r['classification_native_vs_export']['Mask']}")

P("\n== T2  material map / level-set order (pre == post ?)")
for r in runs:
    a, b = r["material_map_pre"], r["material_map_post"]
    P(f"#{r['run_number']:>2} {short(r)} order_pre={[x[1] for x in a['order']]} order_post={[x[1] for x in b['order']]} "
      f"ids_pre={[x[2] for x in a['order']]} ids_post={[x[2] for x in b['order']]} "
      f"identical={a == b}  n_lines(post LS)={r['native_post']['n_lines']}")

P("\n== T3  NATIVE occupancy inside the window (thickness_k(x) = ymax_LSk - ymax_LS(k-1), from level-set surface lines)")
P("   max x-penetration from the window edge (um) at float-zero thresholds " + str(THR) + " [sensitivity, not a criterion]")
for r in runs:
    for mat in ("SiO2", "Mask"):
        m = r["native_post"]["materials"].get(mat, {})
        if not m.get("present_in_domain"):
            P(f"#{r['run_number']:>2} {short(r)} {mat:<4} not a level set in the post domain"); continue
        pen = "  ".join(f"thr{t}: L={m['max_penetration_um_thr_' + t.replace('e-0', 'e-0')]['left'] if False else m['max_penetration_um_thr_' + t]['left']:.3g}/R={m['max_penetration_um_thr_' + t]['right']:.3g}" for t in THR)
        w = m["window_positions_with_material"]
        c = m["core"]
        P(f"#{r['run_number']:>2} {short(r)} {mat:<4} {pen} | n_pos(thr1e-9)={w['n']} min|x|={w['min_abs_x']} max_thick={w['max_thickness_um']:.3g} "
          f"min_thick={w['min_thickness_um_over_all_samples']:.3g} | core max thick={c['max_thickness_um']:.3g} cols_with={c['n_columns_with_material_thr_1e-9']}/{c['n_columns']}")

P("\n== T4  EXPORTED volume mesh (the step's final_mesh): positive-area crossings, components (shared-edge adjacency)")
for r in runs:
    v = r["volume_final"]
    for mat in ("SiO2", "Mask"):
        m = v["materials"].get(mat)
        if not m or "n_crossing_triangles_positive_area" not in m:
            P(f"#{r['run_number']:>2} {short(r)} {mat:<4} no such material in the mesh"); continue
        pa = m.get("paired_analyzer", {})
        P(f"#{r['run_number']:>2} {short(r)} {mat:<4} n_cross(area>0)={m['n_crossing_triangles_positive_area']:>3} n_cross(rule)={m['n_crossing_triangles_analyzer_rule']:>3} "
          f"area={m['total_clipped_area_um2']:.4g} pen={m['max_penetration_um']:.4g} comps={m['n_components_crossing_window']} "
          f"x0={m['present_on_centre_line_x0']} core_cols={m['core_columns_with_material']}/{m['core_columns_sampled']} "
          f"whole_window_rule={m['present_by_analyzer_rule']} paired={pa.get('status')}")
        for c in m["components_top12"][:4]:
            P(f"        comp: tri_total={c['n_triangles_total']:>5} tri_in_window={c['n_triangles_crossing_window']:>2} area={c['clipped_area_um2']:.4g} "
              f"x={[round(v, 5) for v in c['clipped_x_range']]} y={[round(v, 4) for v in c['clipped_y_range']]} "
              f"edge_lo={c['touches_window_edge_lo']} edge_hi={c['touches_window_edge_hi']} "
              f"connected_outside={c['connected_to_material_outside_window']} island={c['isolated_island']} pen={c['penetration_from_touched_edge_um']:.4g}")

P("\n== T5  grid scaling (dimensionless): volume max_penetration/g, total_clipped_area/g^2 ; native penetration(thr1e-9)/g")
for key in (("directional", "plain"), ("directional", "selective"), ("isotropic", "plain"), ("isotropic", "selective")):
    for mat in ("SiO2", "Mask"):
        row = []
        for r in runs:
            if (r["model"], r["recipe_kind"]) != key or r["label"].endswith("REPEAT"):
                continue
            g = r["grid_um"]
            m = r["volume_final"]["materials"].get(mat, {})
            n = r["native_post"]["materials"].get(mat, {})
            npen = max(n.get("max_penetration_um_thr_1e-09", {"left": 0, "right": 0}).values()) if n.get("present_in_domain") else float("nan")
            row.append(f"g={g}: vol_pen/g={m.get('max_penetration_um', 0) / g:.4g} vol_area/g2={m.get('total_clipped_area_um2', 0) / g ** 2:.4g} native_pen/g={npen / g:.4g}")
        P(f"{key[0][:3]}/{key[1][:3]} {mat:<4} " + " | ".join(row))

P("\n== T6  determinism: directional/selective @0.05 vs the repeat on a separate copy of the same baseline")
a = [r for r in runs if r["grid_um"] == 0.05 and r["label"] == "directional_selective"][0]
b = [r for r in runs if r["label"].endswith("REPEAT")][0]
P(f"baseline sha256 equal: {a['baseline_sha256'] == b['baseline_sha256']}")
P(f"final_mesh sha256 equal: {a['files']['final_mesh_sha256'] == b['files']['final_mesh_sha256']}  ({a['files']['final_mesh_sha256'][:16]}.. / {b['files']['final_mesh_sha256'][:16]}..)")
P(f"unfloored export sha256 equal: {a['files']['unfloored_export_sha256'] == b['files']['unfloored_export_sha256']}")
P(f"native post surface sha256 equal: {a['native_post']['surface_sha256'] == b['native_post']['surface_sha256']}")
P(f"native floored-copy surface sha256 equal: {a['native_floored_copy']['surface_sha256'] == b['native_floored_copy']['surface_sha256']}")
same = json.dumps(a["volume_final"], sort_keys=True) == json.dumps(b["volume_final"], sort_keys=True)
P(f"volume metrics (all components) identical: {same}")

P("\n== T7  rate-0 Mask: did its native level set move?  wall x-position (nearest crossing to x=+-2) pre vs post, per height")
P("   body = heights above the oxide top (y 0.25..0.65, only mask material there); foot = y -0.2..0.25 (around/below the oxide top)")
P("   'lean' = x_post - 2 for the right wall (-2 - x_post for the left): POSITIVE = toward the mask/oxide side (outward, e.g. an undercut),")
P("   NEGATIVE = into the window. The reported value is the maximum over foot heights of the nearest wall crossing, so it can pick a")
P("   different branch of the contour at different heights; T7c (raw node coordinates) is the cleaner statement of the wobble.")
for r in runs:
    a, b = r["wall_positions_pre"], r["wall_positions_post"]
    cols = []
    for ls in ("Mask", "SiO2"):
        for side, sgn in (("right", 1), ("left", -1)):
            dbody = [abs(bb - aa) for aa, bb in zip(a[f"{ls}_{side}_body"], b[f"{ls}_{side}_body"]) if aa is not None and bb is not None]
            foot = list(zip(b["foot_heights_um"], b[f"{ls}_{side}_foot"]))
            leans = [((sgn * 2.0 - x) * -sgn, h) for h, x in foot if x is not None]      # >0 = inside window
            hmax = max(leans) if leans else (float("nan"), None)
            bmax = max(dbody) if dbody else float("nan")
            cols.append(f"{ls}/{side}: body max|dx|={bmax:.3g} foot max lean={hmax[0]:.3g}@y={hmax[1]}")
    P(f"#{r['run_number']:>2} {short(r)} " + " | ".join(cols[:2]))
P("   (SiO2 level-set wall shown in raw/matrix_results.json; the earlier 'dthick/nearest-distance' metric is kept there as *__CONFOUNDED*: undercut beneath the mask raises 'mask thickness' although mask top is unmoved)")

P("\n== T7c  raw deviation of the POST native wall nodes from the pre wall x = +2 (right wall), oxide heights y in [0, 0.2), crop |x-2| <= 0.06")
P("   inward = toward the window (x < 2), outward = toward the mask/oxide (x > 2). Node coordinates only; no interpolation between nodes.")
for r in runs:
    parts = []
    for ls in ("Mask", "SiO2"):
        xs = [p[0] for seg in r["foot_native_post"][ls] for p in seg if 0.0 <= p[1] < 0.2 and abs(p[0] - 2.0) <= 0.06]
        dev = [x - 2.0 for x in xs]
        parts.append(f"{ls}: inward max={-min(dev) if dev and min(dev) < 0 else 0:.3g} outward max={max(dev) if dev and max(dev) > 0 else 0:.3g} (n_nodes={len(xs)})")
    g = r["grid_um"]
    mm = [p[0] - 2.0 for seg in r["foot_native_post"]["Mask"] for p in seg if 0.0 <= p[1] < 0.2 and abs(p[0] - 2.0) <= 0.06]
    ratio = max(abs(v) for v in mm) / g if mm else float("nan")
    P(f"#{r['run_number']:>2} {short(r)} " + " | ".join(parts) + f" | max|Mask dev|/g={ratio:.3g}")

P("\n== T7b  height range of the NATIVE sliver (columns where the material thickness > 1e-9)")
for r in runs:
    for mat in ("SiO2", "Mask"):
        m = r["native_post"]["materials"].get(mat, {})
        if m.get("at_penetrating_columns"):
            c = m["at_penetrating_columns"]
            P(f"#{r['run_number']:>2} {short(r)} {mat:<4} n_cols={c['n']} upper LS y in [{c['upper_LS_y_min']:.4f},{c['upper_LS_y_max']:.4f}]  lower LS y in [{c['lower_LS_y_min']:.4f},{c['lower_LS_y_max']:.4f}]")

P("\n== T8  where does it FIRST appear?  presence of SiO2 / Mask inside the window per stage")
P("   A native LS   B floored-copy LS   C unfloored volume mesh   D floored volume mesh (= final_mesh: bytes identical? see T9)")
for r in runs:
    def nat(rec, mat):
        return rec["materials"].get(mat, {}).get("present_in_window_native")
    def vol(rec, mat):
        return rec["materials"].get(mat, {}).get("n_crossing_triangles_positive_area", 0)
    P(f"#{r['run_number']:>2} {short(r)}  SiO2: A={nat(r['native_post'], 'SiO2')} B={nat(r['native_floored_copy'], 'SiO2')} C={vol(r['volume_unfloored_export'], 'SiO2')}tri D={vol(r['volume_floored_export'], 'SiO2')}tri"
      f"   Mask: A={nat(r['native_post'], 'Mask')} B={nat(r['native_floored_copy'], 'Mask')} C={vol(r['volume_unfloored_export'], 'Mask')}tri D={vol(r['volume_floored_export'], 'Mask')}tri")

P("\n== T9  export bookkeeping")
for r in runs:
    P(f"#{r['run_number']:>2} {short(r)} final_mesh bytes == floored-copy export: {r['files']['final_mesh_identical_to_floored_export_bytes']}  "
      f"post domain unchanged by exports: {r['post_domain_unchanged_by_exports']}  "
      f"unique-xy points == points: {r['volume_final']['n_unique_xy_points'] == r['volume_final']['n_points']}  eps={r['volume_final']['geometry_eps_um']:.3g}")
P(f"\nderive_regions fallbacks used: {data.get('derive_regions_fallbacks')}")
text = "\n".join(out)
(AUDIT / "raw" / "summary_tables.txt").write_bytes(text.encode("utf-8"))      # LF, not Windows text-mode CRLF
sys.stdout.reconfigure(encoding="utf-8")
print(text)
