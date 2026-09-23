"""Batch 7H-D3 worker: ONE configuration per process; writes one run JSON.

New wrapper (PLAN.md). It imports the 7H-D2 modules READ-ONLY (common_d2, worker_d2: build,
measure, diag_models, nv, ev) and changes none of them. Differences from worker_d2.run, all
required by the PLAN:
  * mirror mode applies +v to the p contact (worker_d2 applied -v: double sign flip);
  * the actual bias parameters and the contact-node potentials are read back at every recorded point;
  * a second, explicit cut-current definition with a stated tie rule for nodes exactly on a cut;
  * the reverse-branch 0 V state is recorded too; every solve is timed; fixture identity is logged.
cfg: {"id", "kind": "1d"|"2d", "fam", "variant", "h", "P": "P0"|"P12"|"P4", "mirror": bool}
usage: worker_d3.py '<cfg json>' <output json path>
"""
import hashlib
import json
import os
import re
import sys
import time
import traceback

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-23-batch7h-d2-current-precision", "scripts"))
import common_d2 as c2  # noqa: E402  (7H-D2, read-only)
import worker_d2 as w2  # noqa: E402  (7H-D2, read-only)

cd, md = c2.cd, c2.md
c2.VARIANTS["P12"] = (True, True, False)     # in-memory only; D2 files on disk are unchanged
FWD, REV, RECORD = w2.FWD, w2.REV, w2.RECORD
TIE_EPS_UM = 1e-9


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fixture_identity(cfg):
    if cfg["kind"] == "1d":
        xs = np.array(md.grid_1d(cfg["h"], "J1"), dtype=float)
        return {"kind": "1d", "h_um": cfg["h"], "n_nodes": int(len(xs)), "x_um_sha256": sha(xs.tobytes())}
    P, tris, q = c2.fixture(cfg["fam"], cfg["h"])
    path = os.path.join(c2.D1DATA, "fixtures_d1.json")
    raw = open(path, "rb").read()
    conn = sha(json.dumps(sorted(sorted(t) for t in tris)).encode())
    coord = sha(np.ascontiguousarray(P).tobytes())
    return {"kind": "2d", "key": f"{cfg['fam']}_h{cfg['h']}", "file": "docs/audits/2026-09-23-batch7h-d1-pn-convergence/data/fixtures_d1.json",
            "file_sha256_raw": sha(raw), "file_sha256_lf_normalized": sha(raw.replace(b"\r\n", b"\n")),
            "n_nodes": int(len(P)), "n_triangles": int(len(tris)),
            "stored_n_nodes": q["n_nodes"], "stored_n_triangles": q["n_triangles"],
            "coordinates_sha256": coord, "stored_coordinates_sha256": q["coordinates_sha256"],
            "connectivity_sha256": conn, "stored_connectivity_sha256": q["connectivity_sha256"],
            "identical_to_stored": bool(coord == q["coordinates_sha256"] and conn == q["connectivity_sha256"]
                                        and len(P) == q["n_nodes"] and len(tris) == q["n_triangles"])}


def geometry_check(dv, cfg):
    x = w2.nv(dv, "x") / cd.UM
    nd = w2.nv(dv, "NetDoping")
    if cfg["kind"] == "1d":
        expect = np.array(md.grid_1d(cfg["h"], "J1"), dtype=float)
    else:
        P, _, _ = c2.fixture(cfg["fam"], cfg["h"])
        expect = P[:, 0]
    sgn = -1.0 if cfg["mirror"] else 1.0                 # doping-side sign
    gsgn = -1.0 if (cfg["mirror"] and cfg["kind"] == "2d") else 1.0   # 2D mirror reflects the mesh; the symmetric 1D grid is reused
    err = float(np.max(np.abs(x - gsgn * expect))) if len(x) == len(expect) else float("inf")
    donors, acceptors = nd > 0, nd < 0
    return {"n_nodes": int(len(x)), "max_abs_dx_vs_expected_um": err,
            "donor_nodes": int(donors.sum()), "acceptor_nodes": int(acceptors.sum()),
            "donors_all_on_expected_side": bool(np.all(sgn * x[donors] > 0)),
            "acceptors_all_on_expected_side": bool(np.all(sgn * x[acceptors] < 0))}


def readback(dv, cfg, v_set, p_bias, n_bias):
    x, psi = w2.nv(dv, "x"), w2.nv(dv, "Potential")
    xmin, xmax = x.min(), x.max()
    p_nodes = (x == xmax) if cfg["mirror"] else (x == xmin)
    n_nodes = (x == xmin) if cfg["mirror"] else (x == xmax)
    return {"v_set": v_set, "p_bias_name": p_bias, "n_bias_name": n_bias,
            "p_bias_readback": float(dv.get_parameter(device="d", name=p_bias)),
            "n_bias_readback": float(dv.get_parameter(device="d", name=n_bias)),
            "psi_p_contact": float(psi[p_nodes].mean()), "psi_n_contact": float(psi[n_nodes].mean()),
            "psi_p_spread": float(np.ptp(psi[p_nodes])), "psi_n_spread": float(np.ptp(psi[n_nodes])),
            "p_contact_nodes": int(p_nodes.sum()), "n_contact_nodes": int(n_nodes.sum())}


def cuts_explicit(dv, cfg, mirror_positions, tie):
    """Cut currents with an explicit tie rule. Labels are the ORIGINAL cut positions; the geometric position
    is -x_c for a mirror device. L = {x < pos} (a node with |x - pos| <= 1e-9 um goes to R for tie 'R',
    to L for tie 'L'); current toward +x = sum over L-R edges of (Jn+Jp)*couple_used, +1 if n0 is in L."""
    xum = w2.nv(dv, "x") / cd.UM
    n0, n1 = w2.ev(dv, "node_index@n0").astype(int), w2.ev(dv, "node_index@n1").astype(int)
    cname = "OvEdgeCouple" if cfg.get("variant") == "D1" else "EdgeCouple"
    cpl = w2.ev(dv, cname) if cfg["kind"] == "2d" else np.ones(len(n0))
    F = (w2.ev(dv, "ElectronCurrent") + w2.ev(dv, "HoleCurrent")) * cpl
    out = {}
    for xc in c2.CUTS_UM:
        pos = -xc if mirror_positions else xc
        on = np.abs(xum - pos) <= TIE_EPS_UM
        below = xum < pos
        L = (below & ~on) if tie == "R" else (below | on)
        a, b = L[n0], L[n1]
        s = np.where(a & ~b, 1.0, np.where(b & ~a, -1.0, 0.0))
        out[f"{xc:+.2f}"] = {"position_um": float(pos), "total": float(np.sum(s * F)), "n_edges": int(np.count_nonzero(s)),
                             "nodes_on_cut": int(on.sum())}
    return out


def tsolve(dv, kind, tag):
    t = time.perf_counter()
    r = c2.solve(dv, kind, tag)
    r["wall_s"] = round(time.perf_counter() - t, 3)
    return r


def record(dv, cfg, v_set, p_bias, n_bias):
    rec = w2.measure(dv, cfg)
    tie = "L" if cfg["mirror"] else "R"
    rec["C2X"] = cuts_explicit(dv, cfg, cfg["mirror"], tie)
    rec["C2X_tie"] = tie
    rec["C2X_other_tie"] = cuts_explicit(dv, cfg, cfg["mirror"], "R" if tie == "L" else "L")
    rec["readback"] = readback(dv, cfg, v_set, p_bias, n_bias)
    return rec


def run(cfg):
    import devsim as dv
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    t_run = time.perf_counter()
    info = dv.get_parameter(name="info")
    out = {"cfg": cfg, "fixture": fixture_identity(cfg), "flags_at_start": c2.read_flags(dv),
           "flags_set": c2.set_precision(dv, cfg["P"]),
           "devsim": {k: info.get(k) for k in ("version", "extended_precision", "direct_solver", "math_libraries")},
           "steps": {}}
    mirror = cfg["mirror"]
    p_bias, n_bias = ("right_bias", "left_bias") if mirror else ("left_bias", "right_bias")
    for bi, branch in enumerate((FWD, REV)):
        tag_a, tag_b = ("A", "B0") if bi == 0 else ("Arev", "B0rev")
        out["variant_info"] = w2.build(dv, cfg)
        if bi == 0:
            out["geometry"] = geometry_check(dv, cfg)
        setup_semiconductor_potential_equation("d", cd.REGION, ["left", "right"], 300.0)
        a = tsolve(dv, "poisson", tag_a)
        out["steps"][tag_a] = {"info": a}
        if not a["ok"]:
            break
        setup_drift_diffusion_equation("d", cd.REGION, ["left", "right"])
        w2.diag_models(dv)
        b = tsolve(dv, "drift_diffusion", tag_b)
        rec = {"info": b}
        if b["ok"]:
            rec.update(record(dv, cfg, 0.0, p_bias, n_bias))
        out["steps"][tag_b] = rec
        if not b["ok"]:
            break
        for v in branch:
            dv.set_parameter(device="d", name=p_bias, value=v)      # +v on the p contact in BOTH devices
            r = tsolve(dv, "drift_diffusion", f"C{v:+.3f}")
            rec = {"info": r}
            if r["ok"] and v in RECORD:
                rec.update(record(dv, cfg, v, p_bias, n_bias))
            out["steps"][f"C{v:+.3f}"] = rec
            if not r["ok"]:
                break
        dv.delete_device(device="d")
        dv.delete_mesh(mesh="m_d")
    out["flags_at_end"] = c2.read_flags(dv)
    out["devices_left"] = list(dv.get_device_list())
    out["wall_s"] = round(time.perf_counter() - t_run, 3)
    return out


def scrub(text):
    return re.sub(r"[A-Za-z]:[\\/][^\s\"']*", "<PATH>", text)


if __name__ == "__main__":
    cfg, path = json.loads(sys.argv[1]), sys.argv[2]
    try:
        res = run(cfg)
    except Exception as e:  # noqa: BLE001 - recorded, not hidden
        res = {"cfg": cfg, "error": scrub(repr(e))[:500], "traceback": scrub(traceback.format_exc())[-1500:]}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f)
    print(f"\n[worker_d3] wrote {os.path.basename(path)} error={'error' in res}", flush=True)
