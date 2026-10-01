"""E6M remote driver (GitHub-hosted runner only; one run): the synthetic judge checks and the 2D-1D PN consistency audit (one profile, 42 solves planned). Each step is its own subprocess; output, rc, wall time, HEAD, versions and LF sha256 of the files are
saved in e6m_out/."""
import hashlib
import os
import platform
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
OUT = os.path.join(ROOT, "e6m_out")
REL = "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency"
CMDS = [["tests/unit/test_e6l_correction_mock.py"], ["tests/unit/test_e6m_judge_mock.py"], ["tests/integration/test_pn_2d_1d_consistency_real.py", OUT]]
HASHED = [f"{REL}/PLAN.md", f"{REL}/scripts/e6m_metrics.py", f"{REL}/scripts/judge_e6m.py", "tests/integration/test_pn_2d_1d_consistency_real.py", "tests/unit/test_e6m_judge_mock.py",
          "tcad/characterization/pn_junction_iv_sweep.py", "tcad/device/devsim/semiconductor_equation.py", "tcad/device/devsim/doping_mapping.py", "tcad/device/devsim/mesh_import.py",
          "tcad/device/devsim/mesh_conservation.py", "tcad/physics/wafer_state_v2.py"]


def lf_sha(p):
    return hashlib.sha256(open(os.path.join(ROOT, p), "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def main():
    import json
    if "--validate-only" in sys.argv:
        print({p: lf_sha(p) for p in HASHED})
        return 0
    if not (os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"):
        print("[e6m] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(OUT, exist_ok=True)
    vers = {}
    for mod in ("devsim", "viennaps", "viennals", "numpy", "meshio"):
        try:
            vers[mod] = getattr(__import__(mod), "__version__", None)
        except Exception as e:  # noqa: BLE001
            vers[mod] = f"IMPORT_FAILED {e!r}"[:200]
    res = {"head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
           "python": sys.version.split()[0], "platform": platform.platform(), "versions": vers,
           "files_lf_sha256": {p: lf_sha(p) for p in HASHED}, "runs": []}
    for cmd in CMDS:
        t = time.time()
        p = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        name = os.path.basename(cmd[0]).replace(".py", "")
        text = p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr else "")
        text = text.replace(os.path.expanduser("~"), "<USERPROFILE>")
        with open(os.path.join(OUT, f"{name}.log"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        res["runs"].append({"cmd": [c if c != OUT else "<OUT>" for c in cmd], "rc": p.returncode, "wall_s": round(time.time() - t, 1)})
        print(f"[e6m] {name} rc={p.returncode} wall={time.time() - t:.1f}s", flush=True)
        print(p.stdout[-3000:], flush=True)
    res["files"] = {f: hashlib.sha256(open(os.path.join(OUT, f), "rb").read()).hexdigest() for f in sorted(os.listdir(OUT))}
    with open(os.path.join(OUT, "e6m_result.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    return 0 if all(r["rc"] == 0 for r in res["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
