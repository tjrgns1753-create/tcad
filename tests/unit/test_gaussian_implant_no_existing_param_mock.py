#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-09-03 dopant-state-unification, Task 4: DopingRegion.gaussian_terms
and apply_gaussian_implant_doping's existing= accumulation mechanism are
retired -- multi-term accumulation moves to WaferState-level
dopant_profiles (Task 5)."""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def test_apply_gaussian_implant_doping_has_no_existing_param():
    from tcad.physics.doping import apply_gaussian_implant_doping
    sig = inspect.signature(apply_gaussian_implant_doping)
    print(f"apply_gaussian_implant_doping params: {list(sig.parameters)}")
    assert "existing" not in sig.parameters


def test_doping_region_has_no_gaussian_terms_field():
    import dataclasses
    from tcad.mesh.interface import DopingRegion
    field_names = {f.name for f in dataclasses.fields(DopingRegion)}
    print(f"DopingRegion fields: {sorted(field_names)}")
    assert "gaussian_terms" not in field_names


def main():
    test_apply_gaussian_implant_doping_has_no_existing_param()
    test_doping_region_has_no_gaussian_terms_field()
    print("gaussian_terms/existing= accumulation mechanism confirmed retired.")


if __name__ == "__main__":
    main()
