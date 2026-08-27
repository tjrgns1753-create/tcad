#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BiasPoint.converged field shape -- no backend needed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    from tcad.characterization.interface import BiasPoint

    pt = BiasPoint(voltages={"A": 0.0}, currents={"A": 1e-9})
    assert pt.converged is True, "converged must default to True"

    pt2 = BiasPoint(voltages={"A": 0.0}, currents={"A": 1e-9}, converged=False)
    assert pt2.converged is False

    print("BiasPoint.converged field: OK")


if __name__ == "__main__":
    main()
