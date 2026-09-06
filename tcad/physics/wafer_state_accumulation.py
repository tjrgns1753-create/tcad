#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The function the REAL production/GUI doping path calls to advance
WaferState (spec 2026-09-03 Sec9) -- mesh-file-based, matching what
run_doping() actually has (no live domain, per this task's own finding).
A SEPARATE, narrower fix applies inside tcad/process/etching/isotropic.py's
own resolve() context, which DOES have a live domain -- that call site
passes `last_step_category="etching"` directly to WaferState.query(),
not through advance_wafer_state() (this function is mesh-file-based via
ProcessResult.volume_mesh_path, which a live-domain caller doesn't have)."""
from __future__ import annotations

from typing import Optional

from tcad.mesh.interface import ProcessResult
from tcad.physics.dopant_profile import dopant_profiles_from_doping_profile
from tcad.physics.wafer_state import WaferState


def advance_wafer_state(
    prior_state: Optional[WaferState], result: ProcessResult, category: str,
) -> WaferState:
    prior_profiles = prior_state.dopant_profiles if prior_state is not None else ()
    this_step_profiles = (
        dopant_profiles_from_doping_profile(result.doping)
        if result.doping is not None else ()
    )
    return WaferState.from_process_result(
        result,
        dopant_profiles=prior_profiles + this_step_profiles,
        last_step_category=category,
    )
