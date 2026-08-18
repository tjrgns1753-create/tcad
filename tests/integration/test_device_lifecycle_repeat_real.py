#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DevSim device lifecycle fix verification (Major finding from the code
audit): devsim.solve() has no device= argument — it solves every
currently registered device together — so a leftover device from an
earlier run_pipeline() call could make a later, unrelated call fail to
reconverge. tcad/cli/run_pipeline.py now deletes the device (and its
mesh — deleting only the device was found insufficient, since the mesh
survives delete_device() and blocks reusing its name) in a `finally`
block, on both success and failure.

Test A: same Ohmic pipeline run twice in one process -> both succeed,
        identical I-V.
Test B: same PN-junction pipeline run twice in one process -> both
        succeed, identical equilibrium/forward-current behavior.
Test C: same MOS C-V pipeline run twice in one process -> both
        succeed, identical C-V.
Test D: a characterization step is made to raise mid-solve -> the
        device is still cleaned up (verified via devsim.get_device_list()),
        and a *subsequent, unrelated* pipeline run still succeeds
        (proving the exception didn't leave the device registered).

No mocks: every run below goes through tcad.cli.run_pipeline.run_pipeline()
exactly as the CLI does, against the actually-installed ViennaPS 4.6.2
and DevSim 2.10.1.
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from tcad.backends.viennaps import session as viennaps_session
from tcad.device.devsim import backend as devsim_backend

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
assert devsim_backend.is_available(), "DevSim must be installed for this test"

import devsim

from tcad.cli.run_pipeline import run_pipeline


def _load_config(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text())


def test_a_repeat_ohmic():
    config = _load_config("ohmic_iv_config.json")

    with tempfile.TemporaryDirectory() as tmp:
        summary1 = run_pipeline(config, Path(tmp) / "run1")
        summary2 = run_pipeline(config, Path(tmp) / "run2")

        csv1 = (Path(tmp) / "run1" / "characterization_output" / "iv.csv").read_text()
        csv2 = (Path(tmp) / "run2" / "characterization_output" / "iv.csv").read_text()

        assert summary1["characterization"] == "iv_sweep"
        assert summary2["characterization"] == "iv_sweep"
        assert csv1 == csv2, f"Test A: I-V results differ between runs:\n{csv1}\n---\n{csv2}"

    print("[Test A] PASS — Ohmic pipeline run twice in one process, identical I-V:")
    print("  " + csv1.strip().splitlines()[1])


def test_b_repeat_pn_junction():
    config = _load_config("pn_junction_config.json")

    with tempfile.TemporaryDirectory() as tmp:
        summary1 = run_pipeline(config, Path(tmp) / "run1")
        summary2 = run_pipeline(config, Path(tmp) / "run2")

        json1 = json.loads((Path(tmp) / "run1" / "characterization_output" / "pn_iv.json").read_text())
        json2 = json.loads((Path(tmp) / "run2" / "characterization_output" / "pn_iv.json").read_text())

        assert summary1["characterization"] == "pn_junction_iv_sweep"
        assert summary2["characterization"] == "pn_junction_iv_sweep"
        assert json1["points"] == json2["points"], (
            f"Test B: PN-junction I-V points differ between runs:\n{json1['points']}\n---\n{json2['points']}"
        )

    print("[Test B] PASS — PN-junction pipeline run twice in one process, identical result:")
    for p in json1["points"]:
        print(f"  {p['voltages']} -> {p['currents']}")


def test_c_repeat_mos_cv():
    config = _load_config("mos_cv_config.json")

    with tempfile.TemporaryDirectory() as tmp:
        summary1 = run_pipeline(config, Path(tmp) / "run1")
        summary2 = run_pipeline(config, Path(tmp) / "run2")

        json1 = json.loads((Path(tmp) / "run1" / "characterization_output" / "mos_cv.json").read_text())
        json2 = json.loads((Path(tmp) / "run2" / "characterization_output" / "mos_cv.json").read_text())

        assert summary1["characterization"] == "mos_cv_sweep"
        assert summary2["characterization"] == "mos_cv_sweep"
        assert json1["metadata"]["capacitance_F"] == json2["metadata"]["capacitance_F"], (
            f"Test C: C-V differs between runs:\n{json1['metadata']['capacitance_F']}\n"
            f"---\n{json2['metadata']['capacitance_F']}"
        )

    print("[Test C] PASS — MOS C-V pipeline run twice in one process, identical C-V:")
    print(f"  capacitance_F = {json1['metadata']['capacitance_F']}")


def test_d_exception_cleanup():
    config = _load_config("ohmic_iv_config.json")

    # Force a real failure partway through characterization: point the
    # equation setup at a region name that doesn't exist on the device.
    # devsim.node_solution() validates the region argument and raises
    # immediately -- this is a real exception from real DevSim code
    # (confirmed directly against this project's device beforehand),
    # not an injected fake one.
    broken_config = json.loads(json.dumps(config))
    broken_config["characterization"]["region"] = "NoSuchRegion"

    with tempfile.TemporaryDirectory() as tmp:
        raised = False
        try:
            run_pipeline(broken_config, Path(tmp) / "broken_run")
        except Exception as exc:
            raised = True
            print(f"[Test D] Pipeline raised as expected: {type(exc).__name__}: {exc}")
        assert raised, "Test D: expected run_pipeline() to raise for a nonexistent contact"

        # The device this failed run created must be gone -- if cleanup
        # didn't run, it would still be in DevSim's global device list
        # and would still carry the broken equation setup, and could
        # break the next, unrelated run below.
        device_name = broken_config["device"]["device_name"]
        remaining = devsim.get_device_list()
        assert device_name not in remaining, (
            f"Test D: device {device_name!r} was not cleaned up after an exception; "
            f"still registered: {remaining}"
        )
        print(f"[Test D] Device {device_name!r} confirmed absent from devsim.get_device_list() "
              f"after the exception (finally-block cleanup ran).")

        # A subsequent, unrelated, valid run must still succeed --
        # proving the failed run's device isn't lingering and coupling
        # into this solve (the original bug this fix addresses).
        summary = run_pipeline(config, Path(tmp) / "recovery_run")
        assert summary["characterization"] == "iv_sweep"
        print("[Test D] PASS — a subsequent valid pipeline run still succeeds after the failure.")


def main():
    test_a_repeat_ohmic()
    test_b_repeat_pn_junction()
    test_c_repeat_mos_cv()
    test_d_exception_cleanup()
    print()
    print("ALL DEVICE LIFECYCLE TESTS (A-D) PASSED AGAINST REAL VIENNAPS 4.6.2 + DEVSIM 2.10.1")


if __name__ == "__main__":
    main()
