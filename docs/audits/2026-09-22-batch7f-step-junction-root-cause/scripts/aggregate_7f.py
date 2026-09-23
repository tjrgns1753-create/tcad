"""Batch 7F: aggregate imported_7f.json / structured_7f.json into the report's
required tables. Read-only, no new measurement -- pure reporting over already-
collected data.
"""
import json
import math
import os

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")

imported = {c["label"]: c for c in json.load(open(os.path.join(DATA, "imported_7f.json"), encoding="utf-8"))["imported_7f"]}
structured = {c["label"]: c for c in json.load(open(os.path.join(DATA, "structured_7f.json"), encoding="utf-8"))["structured_7f"]}


def p(*a):
    print(*a)


p("=" * 110)
p("TABLE 1: mesh quality (whole / junction_band / transition_ring / coarse_outer), imported L3/L4/L5, R1 node")
p("=" * 110)
for lv in (3, 4, 5):
    c = imported[f"imp_L{lv}_R1_node"]
    for zone in ("whole", "junction_band", "transition_ring", "coarse_outer"):
        z = c["mesh_quality"][zone]
        p(f"L{lv} {zone:16s} n_tri={z['n_triangles']:6d} n_nodes={z['n_nodes']:6d} dup_coords={z['n_duplicate_coords']} "
          f"zero_area={z['n_zero_area_triangles']} flipped={z['n_flipped_orientation_triangles']} non_manifold={z['n_non_manifold_edges']} "
          f"min_angle={z['triangle_min_angle_deg']['min']:.3f} deg  worst_aspect={z['aspect_ratio_longest_edge_over_shortest_altitude']['max']:.2f} "
          f"area[min,med,max]=[{z['triangle_area']['min']:.3e},{z['triangle_area']['median']:.3e},{z['triangle_area']['max']:.3e}] um^2")
    p()

p("=" * 110)
p("TABLE 2: contact geometry (imported, R1 node)")
p("=" * 110)
for lv in (3, 4, 5):
    c = imported[f"imp_L{lv}_R1_node"]
    p(f"L{lv}: contacts={c['contacts']} contact_geometry={c['contact_geometry']}")

p()
p("=" * 110)
p("TABLE 3: NodeVolume dopant inventory -- imported, all (level, rep, shift)")
p("=" * 110)
for lv in (3, 4, 5):
    for rep in ("R1", "R2"):
        for sh in (False, True):
            c = imported[f"imp_L{lv}_{rep}_{'shift' if sh else 'node'}"]
            inv = c["inventory"]
            p(f"L{lv} {rep} {'shift' if sh else 'node'}: Q_D/q={inv['Q_D_over_q_cm-1']:.6e} Q_A/q={inv['Q_A_over_q_cm-1']:.6e} "
              f"Q_net/q={inv['Q_net_over_q_cm-1']:.6e}  analytic Q_D={inv['Q_D_analytic_continuum_cm-1']:.6e} "
              f"NodeVolume_vs_triangulated_relerr={inv['sum_NodeVolume_vs_triangulated_area_relative_error']:.6f}")

p()
p("=" * 110)
p("TABLE 4: R1-R2 inventory difference vs junction-column NodeVolume (node-aligned cases)")
p("=" * 110)
for lv in (3, 4, 5):
    r1 = imported[f"imp_L{lv}_R1_node"]
    r2 = imported[f"imp_L{lv}_R2_node"]
    dQA = r1["inventory"]["Q_A_over_q_cm-1"] - r2["inventory"]["Q_A_over_q_cm-1"]
    expected = 1.0e18 * r1["junction_column"]["column_NodeVolume_sum_cm2"]
    p(f"L{lv}: Q_A(R1)-Q_A(R2)={dQA:.6e} cm^-1   NA*junction_column_NodeVolume={expected:.6e} cm^-1   "
      f"match_relerr={abs(dQA-expected)/max(abs(expected),1e-300):.6f}   junction_column_volume={r1['junction_column']['column_NodeVolume_sum_cm2']:.6e} cm^2 "
      f"({r1['junction_column']['n_nodes_in_column']} nodes)")

p()
p("=" * 110)
p("TABLE 4b: R1 vs R2 shifted doping fingerprint (byte-identical check, imported mesh)")
p("=" * 110)
for lv in (3, 4, 5):
    r1s = imported[f"imp_L{lv}_R1_shift"]["doping_fingerprint"]
    r2s = imported[f"imp_L{lv}_R2_shift"]["doping_fingerprint"]
    p(f"L{lv} shift: donors R1=={r2s['donors_sha256']==r1s['donors_sha256']}  "
      f"acceptors R1==R2 {r1s['acceptors_sha256']==r2s['acceptors_sha256']}")

p()
p("=" * 110)
p("TABLE 5: field maximum -- global / junction-band / junction-interior (imported, R1 node)")
p("=" * 110)
for lv in (3, 4, 5):
    c = imported[f"imp_L{lv}_R1_node"]
    f = c["field"]
    for key in ("global_max", "junction_band_max", "junction_interior_max_excl_boundary"):
        fm = f[key]
        if fm is None:
            p(f"L{lv} {key}: None")
            continue
        p(f"L{lv} {key}: mag={fm['magnitude_Vpercm']:.1f} V/cm Ex={fm['Ex_Vpercm']:.1f} Ey={fm['Ey_Vpercm']:.1f} "
          f"centroid_cm={fm['centroid_cm']} dist_junction={fm['distance_to_junction_cm']:.3e} boundary_adj={fm['boundary_adjacent']} "
          f"to_xmin={fm['to_xmin']:.3e} to_ymax={fm['to_ymax']:.3e}")
    p(f"L{lv} y-invariance indicator max|Ey|/max|Ex| = {f['y_invariance_indicator_max_absEy_over_max_absEx']:.4f}")
    p()

p("=" * 110)
p("TABLE 6: y-invariance (Potential/Electrons/Holes/NetDoping spread), imported R1 node")
p("=" * 110)
for lv in (3, 4, 5):
    c = imported[f"imp_L{lv}_R1_node"]
    yi = c["y_invariance"]
    p(f"L{lv}: n_x_columns={yi['n_distinct_x_columns']} n_multi={yi['n_columns_with_ge2_nodes']} n_singleton={yi['n_singleton_columns']}")
    for name in ("Potential", "Electrons", "Holes", "NetDoping"):
        p(f"   {name}: max_spread={yi[f'{name}_max_spread']:.6e}  median_spread={yi[f'{name}_median_spread']:.6e}")

p()
p("=" * 110)
p("TABLE 7: depletion recovery -- old y-collapsed vs center-yline vs volume-weighted (imported R1 node, donor side)")
p("=" * 110)
for lv in (3, 4, 5):
    c = imported[f"imp_L{lv}_R1_node"]
    old = c["depletion_old_ycollapsed_donor_side"]
    cy = c["depletion_center_yline_donor_side"]
    vw = c["depletion_volume_weighted_donor_side"]
    p(f"L{lv} OLD(y-collapsed):        50%={old['recovery_50pct_cm']:.4e} 90%={old['recovery_90pct_cm']:.4e} 99%={old['recovery_99pct_cm']:.4e}")
    if "UNAVAILABLE_ON_THIS_MESH" in cy:
        p(f"L{lv} NEW(center y-line):     UNAVAILABLE_ON_THIS_MESH ({cy.get('reason')})")
    else:
        p(f"L{lv} NEW(center y-line):     50%={cy['recovery_50pct_cm']:.4e} 90%={cy['recovery_90pct_cm']:.4e} 99%={cy['recovery_99pct_cm']:.4e}  (y={cy['y_line_used_cm']:.4e}, n={cy['n_points_on_line']})")
    p(f"L{lv} NEW(volume-weighted):   50%={vw['recovery_50pct_cm']:.4e} 90%={vw['recovery_90pct_cm']:.4e} 99%={vw['recovery_99pct_cm']:.4e}  (n_columns={vw['n_columns_used']})")

p()
p("=" * 110)
p("TABLE 8: structured control -- NodeVolume relerr, equilibrium, mesh quality (all cases)")
p("=" * 110)
for label, c in structured.items():
    inv = c["inventory"]
    mq = c["mesh_quality"]["transition_ring"] if c["mesh_quality"]["transition_ring"]["n_triangles"] else c["mesh_quality"]["whole"]
    p(f"{label:32s} n_nodes={c['n_nodes']:5d} eq_ok={str(c['equilibrium_converged']):5s} "
      f"NodeVolume_relerr={inv['sum_NodeVolume_vs_triangulated_area_relative_error']:.3e} "
      f"min_angle={mq['triangle_min_angle_deg']['min']:.2f}")

p()
p("=" * 110)
p("TABLE 9: H/2H current scaling (structured, L4-equivalent, R1 node)")
p("=" * 110)
H = structured["struct_L4_R1_node_H"]
H2 = structured["struct_L4_R1_node_2H"]
for tag, c in (("H (y_extent=2.0um)", H), ("2H (y_extent=4.0um)", H2)):
    p(f"{tag}: contacts={c['contacts']} bias_points:")
    for bp in c["bias_points"]:
        if bp.get("converged"):
            p(f"   V={bp['v_bias']:+.2f}  currents={bp['currents']}  conservation_error={bp['conservation_error']:.3e}")
        else:
            p(f"   V={bp['v_bias']:+.2f}  NOT CONVERGED: {bp.get('error','')[:150]}")

contact_len_H = 2.0e-4  # cm, y_extent_um=2.0 * 1e-4
contact_len_2H = 4.0e-4
for bp_h, bp_2h in zip(H["bias_points"], H2["bias_points"]):
    if bp_h.get("converged") and bp_2h.get("converged"):
        cur_h = list(bp_h["currents"].values())
        cur_2h = list(bp_2h["currents"].values())
        i_h = max(abs(v) for v in cur_h)
        i_2h = max(abs(v) for v in cur_2h)
        ratio = i_2h / i_h if i_h else None
        p(f"V={bp_h['v_bias']:+.2f}: |I|(H)={i_h:.4e}  |I|(2H)={i_2h:.4e}  ratio(2H/H)={ratio}  "
          f"contact_length_ratio=2.0  current/contact_length(H)={i_h/contact_len_H:.4e}  current/contact_length(2H)={i_2h/contact_len_2H:.4e}")

p()
p("=" * 110)
p("TABLE 10: diagonal-orientation control (fixed vs alternating, L4 R1 node)")
p("=" * 110)
fixed = structured["struct_L4_R1_node_fixed"]
alt = structured["struct_L4_R1_node_alternating"]
for tag, c in (("fixed", fixed), ("alternating", alt)):
    inv = c["inventory"]
    f = c["field"]
    p(f"{tag}: eq_ok={c['equilibrium_converged']} NodeVolume_relerr={inv['sum_NodeVolume_vs_triangulated_area_relative_error']:.3e} "
      f"global_max_mag={f['global_max']['magnitude_Vpercm']:.1f} band_max_mag={f['junction_band_max']['magnitude_Vpercm']:.1f}")
