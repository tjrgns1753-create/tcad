#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Core process/wafer data models.

These dataclasses are backend-independent: they describe the fabrication
state and recipe parameters, and carry no ViennaPS (or any other backend)
imports. Moved verbatim out of tcad_2d_stagewise.py in Phase 1 — field
names, defaults, and semantics are unchanged so existing GUI code and
saved project JSON files keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Wafer:
    width_um: float = 10.0
    silicon_depth_um: float = 5.0
    oxide_um: float = 0.0

    pr_thickness_um: float = 1.0

    mask_left_um: float = 3.5
    mask_right_um: float = 6.5

    # Every OPEN window in the photomask, in the same 0..width_um
    # coordinates as mask_left_um/mask_right_um. A real mask patterns
    # several windows at once (a MOSFET's source and drain implant
    # openings, for instance); mask_left_um/mask_right_um can only
    # describe one, and are kept as the FIRST opening so every existing
    # reader of them keeps working unchanged.
    #
    # The process layer consumes this as `mask_spans_um` (the OPAQUE
    # complement -- see tcad.process.base.mask_spans_from_openings),
    # which also makes the mask's POSITION real: the older
    # mask_left/mask_right path goes through MakeTrench, which uses only
    # the WIDTH and always centres the window, so a mask drawn off to
    # one side was silently processed as a centred one.
    mask_openings_um: List[List[float]] = field(
        default_factory=lambda: [[3.5, 6.5]]
    )

    exposure_dose: float = 100.0
    develop_time_s: float = 60.0

    # --- resist state -------------------------------------------------
    # What photoresist is ACTUALLY on the wafer right now, as opposed to
    # the mask/PR *parameters* above, which always carry a value whether
    # or not the user ever ran lithography.
    #
    # Keeping these apart is the difference between a Process CAD and a
    # fixed recipe player. With only the parameters, every process step
    # had to guess whether a mask was meant, and guessed from defaults:
    # a plain deposition on a fresh wafer silently grew a 1.0um `Mask`
    # solid and deposited only inside mask_openings_um -- a patterned
    # film nobody asked for. Measured directly against real ViennaPS
    # 4.6.2 before this field existed.
    #
    # pr_present : PR COAT has been run and the resist has not been
    #     stripped. On its own this means a BLANKET film covering the
    #     whole wafer -- coating is not patterning.
    # developed  : DEVELOP has been run since the last coat, so the
    #     resist now carries openings at mask_openings_um. This is the
    #     FIRST point at which a resist opening becomes real geometry;
    #     mask alignment and exposure change no geometry at all.
    pr_present: bool = False

    developed: bool = False
    etched: bool = False
    stripped: bool = False

    # True after ANY real-backend process step (etch, oxidation, ...)
    # has produced a final mesh -- generalizes `etched`, which several
    # etch-only code paths (e.g. the trench-opening placeholder fallback
    # in tcad_2d_stagewise.py) still key on deliberately and unchanged.
    processed: bool = False


@dataclass
class BoschRecipe:
    cycles: int = 10

    grid_delta_um: float = 0.05
    x_extent_um: float = 10.0
    y_extent_um: float = 8.0

    polymer_rate: float = 0.03
    polymer_sticking: float = 1.0

    ion_source_exponent: float = 500.0
    ion_rate: float = -0.02

    neutral_rate: float = -0.01
    neutral_sticking: float = 0.10

    etch_time_s: float = 1.0
