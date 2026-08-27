#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAD-style negative tests that need no real backend: duplicate pin
position, and sweep parameter validation (step=0, start>stop with a
positive step)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    from tcad.mesh.pin import Pin
    from tcad.device.devsim.contact_probe import (
        PinPlacementError, REASON_DUPLICATE_POSITION, find_duplicate_pin_positions,
    )
    from tcad.characterization.sweep_validation import validate_sweep_range, SweepRangeError

    # Duplicate position: Source and Drain placed at the identical spot.
    source = Pin(name="Source", role="Source", x_um=2.0, y_um=0.0)
    drain = Pin(name="Drain", role="Drain", x_um=2.0, y_um=0.0)
    gate = Pin(name="Gate", role="Gate", x_um=5.0, y_um=0.15)
    duplicates = find_duplicate_pin_positions([source, drain, gate], tolerance_um=1e-6)
    assert len(duplicates) == 1, duplicates
    names = {p.name for p in duplicates[0]}
    assert names == {"Source", "Drain"}, names
    print(f"[1/3] duplicate pin position (Source==Drain) correctly detected: {names}")

    # step = 0 -- always invalid, regardless of start/stop.
    try:
        validate_sweep_range(start=-1.0, stop=3.0, step=0.0)
        assert False, "expected SweepRangeError for step=0"
    except SweepRangeError as exc:
        print(f"[2/3] step=0 correctly rejected: {exc}")

    # start > stop with a POSITIVE step never reaches stop.
    try:
        validate_sweep_range(start=3.0, stop=-1.0, step=0.1)
        assert False, "expected SweepRangeError for start>stop with positive step"
    except SweepRangeError as exc:
        print(f"[3/3] start>stop with positive step correctly rejected: {exc}")

    print()
    print("CAD-STYLE NEGATIVE VALIDATION (mock-level): OK")


if __name__ == "__main__":
    main()
