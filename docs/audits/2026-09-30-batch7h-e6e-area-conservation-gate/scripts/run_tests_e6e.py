"""Batch 7H-E6E remote test driver (GitHub-hosted runner only).
usage: run_tests_e6e.py targeted | regression [--validate-only]
targeted  : tests/unit/test_mesh_area_conservation_mock.py, tests/integration/test_mesh_area_conservation_gate_real.py
regression: tests/run_regression.py, once
Each command runs as a subprocess; its full output, exit code and wall time are saved. Also records HEAD, package versions, and
the sha256 of the gate module, the importer, the GUI file and the test files as executed."""
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

SETS = {"targeted": [["tests/unit/test_mesh_area_conservation_mock.py"], ["tests/integration/test_mesh_area_conservation_gate_real.py"]],
        "regression": [["tests/run_regression.py"]]}
HASHED = ["tcad/device/devsim/mesh_conservation.py", "tcad/device/devsim/mesh_import.py", "tcad_2d_stagewise.py", "tcad/cli/run_pipeline.py",
          "tests/unit/test_mesh_area_conservation_mock.py", "tests/integration/test_mesh_area_conservation_gate_real.py", "tests/run_regression.py"]


def lf_sha(p):
    return hashlib.sha256(open(os.path.join(ROOT, p), "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def main():
    mode = sys.argv[1]
    if "--validate-only" in sys.argv:
        print({p: lf_sha(p) for p in HASHED})
        return 0
    if not (os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"):
        print("[e6e-tests] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    out = os.path.join(ROOT, f"e6e_{mode}_out")
    os.makedirs(out, exist_ok=True)
    vers = {}
    for mod in ("devsim", "viennaps", "viennals", "numpy", "meshio"):
        try:
            m = __import__(mod)
            vers[mod] = getattr(m, "__version__", None)
        except Exception as e:  # noqa: BLE001
            vers[mod] = f"IMPORT_FAILED {e!r}"[:200]
    res = {"mode": mode, "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
           "python": sys.version.split()[0], "platform": platform.platform(), "versions": vers,
           "files_lf_sha256_before": {p: lf_sha(p) for p in HASHED}, "runs": []}
    for cmd in SETS[mode]:
        t = time.time()
        p = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        name = os.path.basename(cmd[0]).replace(".py", "")
        with open(os.path.join(out, f"{name}.log"), "w", encoding="utf-8", newline="\n") as f:
            f.write(ce.USER_PATH.sub("<USERPROFILE>", p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr else "")))
        res["runs"].append({"cmd": cmd, "rc": p.returncode, "wall_s": round(time.time() - t, 1)})
        print(f"[e6e-tests] {cmd} rc={p.returncode} wall={time.time() - t:.1f}s", flush=True)
        print(p.stdout[-6000:], flush=True)
    res["files_lf_sha256_after"] = {p: lf_sha(p) for p in HASHED}
    res["files"] = {f: ce.sha_file(os.path.join(out, f)) for f in sorted(os.listdir(out))}
    ce.dump_strict(res, os.path.join(out, "e6e_tests_result.json"))
    return 0 if all(r["rc"] == 0 for r in res["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
