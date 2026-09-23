"""Batch 7H-D: run configurations in isolated subprocesses; store raw JSON
plus Newton iteration counts parsed from DEVSIM's own stdout.
usage: run_matrix.py <group>  (group: ref1d | synth2d | l3)"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")


def configs(group):
    if group == "ref1d":
        return [{"id": f"R0_dx{dx}", "kind": "1d", "dx_um": dx} for dx in (0.02, 0.01, 0.005, 0.0025)]
    if group == "synth2d":
        return [{"id": f"{m}_{v}", "kind": "2d", "mesh": m, "variant": v} for m in ("M1", "M2", "M3", "M4")
                for v in ("D0", "D1", "D2", "D3")]
    if group == "l3ref":
        return [{"id": f"R0L3_dx{dx}", "kind": "1d", "dx_um": dx, "x_range_um": [-2.0, 2.0]} for dx in (0.02, 0.01, 0.005, 0.0025)]
    if group == "l3":
        return [{"id": f"L3_after_{v}", "kind": "2d", "mesh": "L3_after", "variant": v} for v in ("D0", "D1")]
    raise SystemExit("unknown group")


def iterations(stdout):
    out = {}
    for m in re.finditer(r"### SOLVE-BEGIN (\S+)\n(.*?)### SOLVE-END \1 ok=(\w+)", stdout, re.S):
        its = re.findall(r"^Iteration: (\d+)", m.group(2), re.M)
        errs = re.findall(r'Device: "\S+"	RelError: (\S+)	AbsError: (\S+)', m.group(2))
        out[m.group(1)] = {"iterations": (int(its[-1]) + 1) if its else 0, "ok": m.group(3) == "True",
                           "final_rel": float(errs[-1][0]) if errs else None, "final_abs": float(errs[-1][1]) if errs else None}
    return out


def main(group):
    results = {}
    for cfg in configs(group):
        p = subprocess.run([sys.executable, os.path.join(HERE, "sg_worker.py"), json.dumps(cfg)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=3600,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        txt = p.stdout
        if "===RESULT_JSON===" in txt:
            r = json.loads(txt.split("===RESULT_JSON===", 1)[1].strip().splitlines()[0])
        else:
            r = {"cfg": cfg, "error": f"no result rc={p.returncode} tail={(txt + p.stderr)[-800:]}"}
        r["newton"] = iterations(txt)
        results[cfg["id"]] = r
        oks = {k: v.get("ok") for k, v in r.get("steps", {}).items() if isinstance(v, dict)}
        print(cfg["id"], r.get("error", ""), oks, {k: v["iterations"] for k, v in r["newton"].items()}, flush=True)
    with open(os.path.join(DATA, f"results_{group}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(results, f)


if __name__ == "__main__":
    main(sys.argv[1])
