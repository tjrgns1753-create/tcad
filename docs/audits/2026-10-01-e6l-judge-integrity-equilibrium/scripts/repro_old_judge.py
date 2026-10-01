"""E6L: reproduce the four false PASS / false continuation cases of the ORIGINAL E6K judge (read-only use of judge_e6k.py; nothing in E6K is modified)."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/scripts"))
import judge_e6k as old  # noqa: E402

RAW = ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out/pn_1d_diagnostic.json"


def verdicts(m):
    return {k: v["verdict"] for k, v in old.judge(m).items()}


def main():
    base = json.load(open(RAW))["metrics"]
    out = {"original": verdicts(base)}
    m = copy.deepcopy(base)
    m["minority"] = {"s_um": [3.0], "dev": m["minority"]["dev"][:1], "ref": m["minority"]["ref"][:1]}
    out["A_minority_3_to_1"] = verdicts(m)
    m = copy.deepcopy(base)
    del m["devices"]["L0_fwd"]
    out["B_delete_L0_fwd"] = verdicts(m)
    m = copy.deepcopy(base)
    m["J"]["L2"]["0.6"] = str(m["J"]["L2"]["0.6"])
    m["Emax"]["L2"]["-1.0"] = str(m["Emax"]["L2"]["-1.0"])
    out["C_numeric_strings"] = verdicts(m)
    m = copy.deepcopy(base)
    m["unit"]["control_ratio"] = float("nan")
    out["D_ratio_nan_flag_true"] = verdicts(m)
    print(json.dumps(out, indent=1))
    (Path(__file__).resolve().parents[1] / "repro_old_judge.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
