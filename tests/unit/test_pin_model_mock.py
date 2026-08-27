#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pure dataclass/validation-shape tests for the Pin model -- no
ViennaPS/DevSim needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    from tcad.mesh.pin import Pin
    from tcad.device.devsim.contact_probe import (
        PinPlacementError, REASON_OUTSIDE_MESH, REASON_ON_INSULATOR,
        REASON_INTERIOR_BULK, REASON_NO_BOUNDARY_NEARBY,
        REASON_DUPLICATE_POSITION,
    )

    pin = Pin(name="Drain", role="Drain", x_um=4.0, y_um=0.0)
    assert pin.name == "Drain"
    assert pin.role == "Drain"
    assert pin.x_um == 4.0
    assert pin.y_um == 0.0
    assert pin.target_region is None

    pin2 = Pin(name="Gate", role="Gate", x_um=2.0, y_um=0.15, target_region="TiN")
    assert pin2.target_region == "TiN"

    err = PinPlacementError(pin, REASON_OUTSIDE_MESH, "x=4.0 is past the mesh's own x_max=3.5")
    assert err.pin is pin
    assert err.reason == REASON_OUTSIDE_MESH
    assert "x_max" in err.detail
    assert isinstance(err, Exception)

    reasons = {
        REASON_OUTSIDE_MESH, REASON_ON_INSULATOR, REASON_INTERIOR_BULK,
        REASON_NO_BOUNDARY_NEARBY, REASON_DUPLICATE_POSITION,
    }
    assert len(reasons) == 5, "reason codes must all be distinct strings"

    print("Pin model + PinPlacementError scaffolding: OK")


if __name__ == "__main__":
    main()
