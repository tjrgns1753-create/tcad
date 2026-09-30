"""Batch 7H-E6H remote driver (GitHub-hosted runner only; one run): pure unit tests, conformity of the committed B/F outputs, the
Poisson / linear controls on builder transition meshes. Each step is its own subprocess; output, rc, wall time, HEAD, versions and LF sha256 of the files are
saved in e6h_out/."""
import hashlib
import os
import platform
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
OUT = os.path.join(ROOT, "e6h_out")
REL = "docs/audits/2026-10-01-batch7h-e6h-conformity-poisson"
CMDS = [["tests/unit/test_mesh_structured_remesh_mock.py"], ["tests/unit/test_mesh_refine_mock.py"], ["tests/unit/test_mesh_conformity_check_mock.py"],
        ["tests/unit/test_mesh_implant_refine_fallback_mock.py"], [f"{REL}/scripts/conformity_bf.py"],
        ["tests/integration/test_mesh_gate_poisson_transition_real.py", OUT]]
HASHED = ["tcad/device/devsim/mesh_refine.py", "tcad/device/devsim/mesh_import.py", "tcad/device/devsim/mesh_conservation.py",
          "tests/unit/test_mesh_structured_remesh_mock.py", "tests/unit/test_mesh_conformity_check_mock.py",
          "tests/unit/test_mesh_implant_refine_fallback_mock.py", "tests/integration/test_mesh_gate_poisson_transition_real.py",
          f"{REL}/scripts/conformity_e6h.py", f"{REL}/scripts/op_analysis.py", f"{REL}/CRITERIA.md", f"{REL}/CRITERIA_ERRATUM_1.md"]


def lf_sha(p):
    return hashlib.sha256(open(os.path.join(ROOT, p), "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def main():
    import json
    if "--validate-only" in sys.argv:
        print({p: lf_sha(p) for p in HASHED})
        return 0
    if not (os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"):
        print("[e6h] refusing to run: not a GitHub-hosted runner", flush=True)
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
        print(f"[e6h] {name} rc={p.returncode} wall={time.time() - t:.1f}s", flush=True)
        print(p.stdout[-3000:], flush=True)
    res["files"] = {f: hashlib.sha256(open(os.path.join(OUT, f), "rb").read()).hexdigest() for f in sorted(os.listdir(OUT))}
    with open(os.path.join(OUT, "e6g_result.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    return 0 if all(r["rc"] == 0 for r in res["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
