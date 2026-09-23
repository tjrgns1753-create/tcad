"""Batch 7H-D2 runner: each configuration x precision variant in its own
subprocess (timeout 3600 s -> NOT_COMPLETED, no retry). Results in
data/runs/<id>.json, DEVSIM stdout in data/logs/<id>.log.
usage: run_d2.py 1d | 2d_coarse | 2d_fine | mirror"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
PS = ("P0", "P1", "P2", "P3", "P4")
H1D = (0.02, 0.01, 0.005, 0.0025, 0.00125, 0.000625, 0.0003125)
FAMS = (("M2", "D0"), ("M1", "D0"), ("M3", "D1"))


def configs(group):
    if group == "1d":
        return [{"kind": "1d", "h": h, "P": P, "mirror": False} for h in H1D for P in PS]
    if group == "2d_coarse":
        c = [{"kind": "2d", "fam": f, "variant": v, "h": h, "P": P, "mirror": False}
             for h in (0.02, 0.005) for f, v in FAMS for P in PS]
        return c + [{"kind": "2d", "fam": "M3", "variant": "D1", "h": 0.0025, "P": P, "mirror": False} for P in ("P0", "P4")]
    if group == "2d_fine":
        return [{"kind": "2d", "fam": f, "variant": v, "h": 0.00125, "P": P, "mirror": False} for f, v in FAMS for P in PS]
    if group == "mirror":
        return [{"kind": "1d", "h": 0.005, "P": P, "mirror": True} for P in ("P0", "P4")] + \
               [{"kind": "2d", "fam": "M1", "variant": "D0", "h": 0.005, "P": P, "mirror": True} for P in ("P0", "P4")]
    raise SystemExit("unknown group")


def rid(c):
    base = f"1D_h{c['h']}" if c["kind"] == "1d" else f"{c['fam']}_{c['variant']}_h{c['h']}"
    return f"{base}_{c['P']}" + ("_mirror" if c["mirror"] else "")


def main(group):
    for d in ("runs", "logs"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    for cfg in configs(group):
        i = rid(cfg)
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, os.path.join(HERE, "worker_d2.py"), json.dumps(cfg)], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=3600,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            lines = [ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")]
            with open(os.path.join(DATA, "logs", i + ".log"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(ln for ln in p.stdout.splitlines() if not ln.startswith("RESULT ")) +
                         "\n--- stderr ---\n" + p.stderr[-4000:])
            r = json.loads(lines[-1][7:]) if lines else {"cfg": cfg, "status": "NOT_COMPLETED", "error": p.stderr[-600:]}
        except subprocess.TimeoutExpired:
            r = {"cfg": cfg, "status": "NOT_COMPLETED", "error": "timeout 3600 s"}
        r["id"], r["wall_s"] = i, round(time.time() - t0, 1)
        with open(os.path.join(DATA, "runs", i + ".json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(r, fh)
        st = {k: v["info"]["ok"] for k, v in r.get("steps", {}).items() if isinstance(v, dict) and "info" in v}
        print(i, r.get("status", ""), r.get("error", ""), "all_ok" if st and all(st.values()) else st, r["wall_s"], "s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
