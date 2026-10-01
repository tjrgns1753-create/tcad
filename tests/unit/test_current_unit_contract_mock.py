#!/usr/bin/env python3
"""User-facing unit contract of 2D DevSim drift-diffusion currents (Batch 7H-E6J): the raw number is per unit out-of-plane depth
(A/cm), carried as machine-readable metadata; an unknown unit is never shown as plain A. Pure Python (no DEVSIM / ViennaPS)."""
import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tcad.characterization.interface import (  # noqa: E402
    BiasPoint, CharacterizationResult, current_unit_metadata, current_unit_note, established_current_unit, format_current,
    CURRENT_CONVENTION_NOTE,
)
from tcad.characterization.io import save_csv, save_json  # noqa: E402
from tcad.characterization.plotting import save_iv_plot  # noqa: E402


def result(metadata):
    pts = [BiasPoint(voltages={"a": 0.0, "b": v}, currents={"a": -1.6e-4 * v / 1e-3, "b": 1.6e-4 * v / 1e-3}) for v in (0.0, 1e-3, 2e-3)]
    return CharacterizationResult(name="t", device="d", region="Si", sweep_contact="b", points=pts, metadata=metadata)


def main():
    m2 = current_unit_metadata(2)
    assert m2 == {"current_unit": "A/cm", "current_normalization": "per_out_of_plane_depth", "device_dimension": 2,
                  "current_convention": CURRENT_CONVENTION_NOTE}, m2
    for dim in (1, 3, None, 0):      # not verified: unit is None, never A, and no 2D-specific note is attached
        m = current_unit_metadata(dim)
        assert m == {"current_unit": None, "current_normalization": None, "device_dimension": dim}, m
        assert "current_convention" not in m
    for blank in (None, "", "   ", 3, {}):
        assert established_current_unit({"current_unit": blank}) is None, blank
    assert established_current_unit(None) is None and established_current_unit({}) is None
    assert established_current_unit({"current_unit": "A"}) == "A" and established_current_unit(m2) == "A/cm"
    raw = 1.6e-4
    shown = format_current(raw, m2)
    assert shown == "1.600000e-04 A/cm", shown
    assert float(shown.split()[0]) == float(f"{raw:.6e}"), "the printed number must be the raw number"
    neg = format_current(-raw, m2)
    assert neg.startswith("-1.600000e-04") and neg.endswith(" A/cm"), neg          # sign unchanged
    assert format_current(raw, {"current_unit": "A"}) == "1.600000e-04 A"          # an ESTABLISHED A is accepted as given
    for unknown in ({}, None, current_unit_metadata(3), current_unit_metadata(1), {"current_unit": None}, {"current_unit": ""}, {"current_unit": "  "}):
        s = format_current(raw, unknown)
        assert "unit not established" in s and not s.rstrip().endswith(" A") and "A/cm" not in s, s
    assert "per unit out-of-plane depth" in current_unit_note(m2) and "A/cm" in current_unit_note(m2)
    assert current_unit_note({}) == "" and current_unit_note(current_unit_metadata(3)) == "" and current_unit_note(current_unit_metadata(1)) == ""
    assert current_unit_note({"current_unit": "A"}) == ""                           # the 2D depth note only for that normalisation

    # explicit-depth CONTROL of the conversion formula only (a test depth of 1 um, never a production default)
    assert abs(raw * 1.0e-4 - 1.6e-8) <= 1e-20, raw * 1.0e-4

    tmp = Path(tempfile.mkdtemp(prefix="unit_contract_"))
    # results carrying the unit: CSV header, JSON metadata, plot axis; numbers untouched
    r = result(dict(m2))
    with open(save_csv(r, str(tmp / "a.csv")), newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["sweep_voltage_V", "I_a_A_per_cm", "I_b_A_per_cm"], rows[0]
    assert [float(x) for x in rows[2][1:]] == [-1.6e-4, 1.6e-4], rows[2]
    payload = json.loads(Path(save_json(r, str(tmp / "a.json"))).read_text())
    assert payload["metadata"]["current_unit"] == "A/cm" and payload["points"][1]["currents"]["b"] == 1.6e-4
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    captured = {}
    real_savefig = plt.Figure.savefig

    def spy(self, *a, **k):
        captured["ylabel"] = self.axes[0].get_ylabel()
        return real_savefig(self, *a, **k)
    plt.Figure.savefig = spy
    try:
        save_iv_plot(r, str(tmp / "a.png"))
        assert captured["ylabel"] == "Current (A/cm)", captured
        save_iv_plot(result({}), str(tmp / "b.png"))
        assert captured["ylabel"] == "Current (unit not established)", captured    # no unit metadata -> never A
        for md in ({"current_unit": None}, {"current_unit": ""}, current_unit_metadata(1)):
            save_iv_plot(result(dict(md)), str(tmp / "c.png"))
            assert captured["ylabel"] == "Current (unit not established)", (md, captured)
        save_iv_plot(result({"current_unit": "A"}), str(tmp / "d.png"))
        assert captured["ylabel"] == "Current (A)", captured                       # an explicitly established A is shown as such
    finally:
        plt.Figure.savefig = real_savefig
    for k, md in enumerate(({}, {"current_unit": None}, {"current_unit": ""}, current_unit_metadata(1), current_unit_metadata(3))):
        with open(save_csv(result(dict(md)), str(tmp / f"b{k}.csv")), newline="") as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["sweep_voltage_V", "I_a_unit_unknown", "I_b_unit_unknown"], (md, rows[0])
        assert [float(x) for x in rows[2][1:]] == [-1.6e-4, 1.6e-4]                # numbers untouched
        payload = json.loads(Path(save_json(result(dict(md)), str(tmp / f"b{k}.json"))).read_text())
        assert payload["points"][1]["currents"]["b"] == 1.6e-4 and payload["metadata"].get("current_unit") in (None, "")
    with open(save_csv(result({"current_unit": "A"}), str(tmp / "e.csv")), newline="") as f:
        assert next(csv.reader(f)) == ["sweep_voltage_V", "I_a_A", "I_b_A"]       # established A: allowed
    print("CURRENT UNIT CONTRACT MOCK CHECKS PASSED")


if __name__ == "__main__":
    main()
