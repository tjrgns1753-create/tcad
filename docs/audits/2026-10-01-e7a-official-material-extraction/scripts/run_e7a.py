"""E7A remote driver (GitHub-hosted runner only): one subprocess per (case, route[, epsilon]) so a native crash cannot hide the others; raw stdout+stderr
(native ViennaPS/ViennaLS logs) of every run is saved. Criteria: ../CRITERIA.md."""
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
OUT = os.path.join(ROOT, "e7a_out")
REL = "docs/audits/2026-10-01-e7a-official-material-extraction"
PROBE = f"{REL}/scripts/probe_e7a.py"
PROBE_S1 = f"{REL}/scripts/probe_e7a_s1.py"
MODE = "s1" if "--s1" in sys.argv else "main"
HASHED = [f"{REL}/S1_CRITERIA.md", f"{REL}/scripts/probe_e7a_s1.py", "tcad/backends/viennaps/io.py", "tcad/process/oxidation/locos.py", "tests/integration/_explicit_oxide_fixture.py", PROBE, f"{REL}/CRITERIA.md"]
RUNS = [("P0", "P0", None)]
for case in ("A", "B1", "B2", "C", "CN"):
    RUNS += [(case, r, None) for r in ("R0", "R0d", "R1", "R2", "R3")]
for case in ("A", "CN"):
    RUNS += [(case, "R1", e) for e in (0.0, 0.02)]
if MODE == "s1":
    RUNS = [(case, r, None) for case in ("A", "B1", "B2", "C", "CN") for r in ("R4", "R5")]
if "--s1b" in sys.argv:
    MODE = "s1"
    RUNS = [("B2", "R5", None), ("B2", "R6", None)]


def lf_sha(p):
    return hashlib.sha256(open(os.path.join(ROOT, p), "rb").read().replace(b"\r\n", b"\n")).hexdigest()


def main():
    if "--validate-only" in sys.argv:
        print({p: lf_sha(p) for p in HASHED})
        return 0
    if not (os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"):
        print("[e7a] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)
    vers = {}
    for mod in ("viennaps", "viennals", "numpy", "meshio"):
        try:
            vers[mod] = getattr(__import__(mod), "__version__", None)
        except Exception as e:  # noqa: BLE001
            vers[mod] = f"IMPORT_FAILED {e!r}"[:200]
    res = {"head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(), "python": sys.version.split()[0],
           "platform": platform.platform(), "versions": vers, "files_lf_sha256": {p: lf_sha(p) for p in HASHED}, "runs": []}
    for case, rt, eps in RUNS:
        tag = f"{case}_{rt}" + (f"_eps{eps}" if eps is not None else "")
        cmd = [sys.executable, PROBE_S1 if MODE == "s1" else PROBE, OUT, case, rt] + ([str(eps)] if eps is not None else [])
        t = time.time()
        try:
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
            rc, text = p.returncode, p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr else "")
        except subprocess.TimeoutExpired as e:
            rc, text = "TIMEOUT", (e.stdout or "") if isinstance(e.stdout, str) else ""
        text = text.replace(os.path.expanduser("~"), "<USERPROFILE>")
        with open(os.path.join(OUT, "raw", f"{tag}.log"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        res["runs"].append({"tag": tag, "rc": rc, "wall_s": round(time.time() - t, 1)})
        print(f"[e7a] {tag} rc={rc} wall={time.time() - t:.1f}s", flush=True)
    res["files"] = {os.path.relpath(os.path.join(d, f), OUT).replace(os.sep, "/"): hashlib.sha256(open(os.path.join(d, f), "rb").read()).hexdigest()
                    for d, _, fs in os.walk(OUT) for f in sorted(fs)}
    with open(os.path.join(OUT, "e7a_result.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
