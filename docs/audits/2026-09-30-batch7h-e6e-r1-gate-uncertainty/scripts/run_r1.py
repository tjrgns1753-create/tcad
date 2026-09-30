"""Batch 7H-E6E-R1 remote driver (GitHub-hosted runner only; one run). Runs, each as its own subprocess:
unit test, the E6E targeted real test, the small Laplace control, diagnosis A, diagnosis B. Saves every output, rc, wall time, HEAD,
package versions and the LF sha256 of the files as executed."""
import hashlib
import os
import platform
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402

OUT = os.path.join(ROOT, "e6e_r1_out")
REL = "docs/audits/2026-09-30-batch7h-e6e-r1-gate-uncertainty"
CMDS = [["tests/unit/test_mesh_area_conservation_mock.py"], ["tests/integration/test_mesh_area_conservation_gate_real.py"],
        ["tests/integration/test_mesh_gate_small_laplace_control_real.py"], [f"{REL}/scripts/diag_r1.py", OUT, "A"],
        [f"{REL}/scripts/diag_r1.py", OUT, "B"]]
HASHED = ["tcad/device/devsim/mesh_conservation.py", "tcad/device/devsim/mesh_import.py", "tcad_2d_stagewise.py", "tcad/cli/run_pipeline.py",
          "tests/unit/test_mesh_area_conservation_mock.py", "tests/integration/test_mesh_area_conservation_gate_real.py",
          "tests/integration/test_mesh_gate_small_laplace_control_real.py", f"{REL}/scripts/diag_r1.py", f"{REL}/PLAN.md"]


def lf_sha(p):
    return hashlib.sha256(open(os.path.join(ROOT, p), "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def main():
    if "--validate-only" in sys.argv:
        print({p: lf_sha(p) for p in HASHED})
        return 0
    if not (os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"):
        print("[r1] refusing to run: not a GitHub-hosted runner", flush=True)
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
           "files_lf_sha256_before": {p: lf_sha(p) for p in HASHED}, "runs": []}
    for cmd in CMDS:
        t = time.time()
        p = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        name = os.path.basename(cmd[0]).replace(".py", "") + ("_" + cmd[-1] if cmd[0].endswith("diag_r1.py") else "")
        with open(os.path.join(OUT, f"{name}.log"), "w", encoding="utf-8", newline="\n") as f:
            f.write(ce.USER_PATH.sub("<USERPROFILE>", p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr else "")))
        res["runs"].append({"cmd": [c if c != OUT else "<OUT>" for c in cmd], "rc": p.returncode, "wall_s": round(time.time() - t, 1)})
        print(f"[r1] {name} rc={p.returncode} wall={time.time() - t:.1f}s", flush=True)
        print(p.stdout[-4000:], flush=True)
    res["files_lf_sha256_after"] = {p: lf_sha(p) for p in HASHED}
    res["files"] = {f: ce.sha_file(os.path.join(OUT, f)) for f in sorted(os.listdir(OUT))}
    ce.dump_strict(res, os.path.join(OUT, "r1_result.json"))
    return 0 if all(r["rc"] == 0 for r in res["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
