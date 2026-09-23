"""Run a list of standalone test scripts from a given tree and record rc / time / last error line for each.
usage: python run_suite.py <tree_root> <out_file> <timeout_s> <test path> ...
(no test is skipped; a timeout is reported as TIMEOUT, never as a pass)"""
import subprocess
import sys
import time
from pathlib import Path

root, out_file, timeout = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
rows = []
for t in sys.argv[4:]:
    path = root / t
    if not path.exists():
        rows.append(f"{Path(t).stem:50s} MISSING")
        continue
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, str(path)], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        text = (p.stdout + "\n" + p.stderr).splitlines()
        err = next((ln.strip() for ln in reversed(text) if "Error" in ln or "Exception" in ln), "")
        rows.append(f"{Path(t).stem:50s} rc={p.returncode} {time.time() - t0:6.1f}s  {err[:170] if p.returncode else ''}")
    except subprocess.TimeoutExpired:
        rows.append(f"{Path(t).stem:50s} TIMEOUT({timeout}s)")
out_file.write_text("\n".join(rows) + "\n", encoding="utf-8")
print("\n".join(rows))
