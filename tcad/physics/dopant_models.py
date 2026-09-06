#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-model anneal/redistribution dispatch registry (spec 2026-09-03
Sec7). Registration mechanism is a plain dict, decided at implementation
time -- the spec left the exact mechanism open, matching how the base
design (2026-08-25) also left DiffusionModel's own registration shape
undecided until implementation."""
from typing import Callable, Dict, Optional, Tuple

from tcad.physics.diffusion_model import anneal_profile
from tcad.physics.dopant_profile import DopantProfile
from tcad.physics.values import Resolution

# Handler contract: (profile, resolution) -- resolution reports whether
# the D(T) actually used for this anneal fell inside its own citation's
# measured window (VERIFIED), was extrapolated outside it (UNVERIFIED),
# or is None when no D(T) was computed at all (nothing to widen / no
# species label / no table entry -- see anneal_profile's own docstring).
# Final-review Fix 1 (2026-09-03 dopant-state-unification): widened from
# a bare DopantProfile return so apply_thermal_anneal() (doping.py) can
# surface an out-of-citation-window anneal instead of silently dropping
# that disclosure.
ANNEAL_HANDLERS: Dict[
    str, Callable[[DopantProfile, float, float], Tuple[DopantProfile, Optional[Resolution]]]
] = {}


def register_anneal_handler(model_tag: str, handler) -> None:
    ANNEAL_HANDLERS[model_tag] = handler


# anneal_profile() (Task 1 already migrated it to read model_params and
# use profile.host_material) is registered DIRECTLY -- no adapter
# needed. It must NOT append its own ThermalEvent (see its docstring,
# Task 1): apply_thermal_anneal() below does that once, uniformly, for
# every profile regardless of whether a handler exists, so a handler
# double-appending it would corrupt thermal_history.
register_anneal_handler("gaussian_v1", anneal_profile)
