"""Batch 7H-D1 runner: each configuration in its own subprocess (timeout 3600 s,
registered stop condition). usage: run_d1.py ref1d_J1 | ref1d_J0 | 2d"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
H1D = (0.02, 0.01, 0.005, 0.0025, 0.00125)
H2D = (0.02, 0.01, 0.005, 0.0025)


def configs(group):
    if group in ("ref1d_J1", "ref1d_J0"):
        j = group[-2:]
        return [{"id": f"1D_{j}_h{h}", "kind": "1d", "h": h, "junction": j} for h in H1D]
    if group == "2d":
        return [{"id": f"{f}_{v}_h{h}", "kind": "2d", "fam": f, "h": h, "variant": v}
                for f, vs in (("M1", ("D0",)), ("M2", ("D0",)), ("M3", ("D0", "D1"))) for v in vs for h in H2D]
    raise SystemExit("unknown group")


def main(group):
    os.makedirs(os.path.join(DATA, "logs"), exist_ok=True)
    res = {}
    for cfg in configs(group):
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, os.path.join(HERE, "worker_d1.py"), json.dumps(cfg)], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=3600,
                               env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            txt, rc = p.stdout, p.returncode
            with open(os.path.join(DATA, "logs", cfg["id"] + ".log"), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(txt.split("===RESULT_JSON===")[0] + "\n--- stderr ---\n" + p.stderr[-4000:])
            r = json.loads(txt.split("===RESULT_JSON===", 1)[1].strip().splitlines()[0]) if "===RESULT_JSON===" in txt \
                else {"cfg": cfg, "status": "NOT_COMPLETED", "error": f"rc={rc} {(p.stderr or '')[-500:]}"}
        except subprocess.TimeoutExpired:
            r = {"cfg": cfg, "status": "NOT_COMPLETED", "error": "timeout 3600 s"}
        r["wall_s"] = round(time.time() - t0, 1)
        res[cfg["id"]] = r
        st = {k: (v.get("info", {}).get("ok"), v.get("info", {}).get("iterations")) for k, v in r.get("steps", {}).items()
              if isinstance(v, dict)}
        print(cfg["id"], r.get("status", ""), r.get("error", ""), st, r["wall_s"], "s", flush=True)
    with open(os.path.join(DATA, f"results_{group}.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh)


if __name__ == "__main__":
    main(sys.argv[1])
