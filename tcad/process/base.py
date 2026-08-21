#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Common interface every process-category step (Etching today; Deposition
and Oxidation in later phases) implements.

A ProcessStep is a thin, backend-independent wrapper around one ViennaPS
process recipe: it knows how to turn a plain recipe dict into calls
against tcad.backends.viennaps.session / tcad.backends.viennaps.io, and
returns a uniform result dict so the GUI, CLI, and (later) the
Process -> Mesh/Structure handoff can treat every model the same way,
regardless of category or which ViennaPS class backs it.
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Optional

from tcad.backends.viennaps import session

#: Recipe keys that only describe how to build a *fresh* wafer. When a
#: step inherits a domain from a previous step (process flow), these
#: cannot be honored — the wafer already exists — so prepare_domain()
#: warns about any of them that were supplied, rather than silently
#: ignoring them. Physical process parameters (etch_time_s, rate,
#: temperature_c, material_rates, ...) are NOT in this list and are
#: applied normally by each model.
INITIAL_GEOMETRY_RECIPE_KEYS = (
    "grid_delta_um",
    "x_extent_um",
    "y_extent_um",
    "mask_left_um",
    "mask_right_um",
    "mask_spans_um",
    "pr_thickness_um",
)


def mask_spans_from_openings(openings_um, x_extent_um):
    """Turn mask OPENINGS into the OPAQUE spans `mask_spans_um` wants.

    A photomask is naturally described by where it is OPEN (that is
    where the wafer gets processed), but `mask_spans_um` — and
    ViennaPS's own `make_mask_spans` behind it — take the OPAQUE
    regions. This is the complement, and the exact inverse of
    `tcad.physics.doping.implant_windows_from_mask_spans`, which goes
    the other way for the same reason.

    openings_um : [(lo, hi), ...] in the GUI's own 0..x_extent_um
        coordinates (0 = the wafer's left edge), the way a mask layout
        is drawn/typed. Overlapping or unsorted openings are merged
        first, so a caller may hand over raw user input.
    x_extent_um : the wafer's full width. Output is in DOMAIN
        coordinates, which are centred on 0 (spanning
        [-x_extent_um/2, +x_extent_um/2]) — the convention every recipe
        and every ViennaPS call in this project already uses.

    Returns [(lo, hi), ...] opaque spans, in domain coordinates. An
    empty `openings_um` yields one span covering the whole wafer (a
    fully opaque mask); openings covering everything yield none (no
    mask at all).
    """
    half = x_extent_um / 2.0

    merged = []
    for lo, hi in sorted((min(o), max(o)) for o in openings_um):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])

    spans = []
    cursor = 0.0
    for lo, hi in merged:
        if lo > cursor:
            spans.append((cursor - half, min(lo, x_extent_um) - half))
        cursor = max(cursor, hi)
    if cursor < x_extent_um:
        spans.append((cursor - half, x_extent_um - half))
    return spans


class ProcessStep(ABC):
    """Base class for one process recipe within a category.

    Subclasses set the three class attributes below and implement run().

    Domain lifecycle (process flow continuity):
        A ProcessStep normally builds its own fresh wafer — that is the
        single-step behavior every caller from Phase 1-12 relies on, and
        it is unchanged.

        To chain steps into a real process flow, the orchestration layer
        (tcad.process.flow) constructs the step with an already-built
        domain: `StepCls(inherited_domain=domain)`. There is no
        module-level/global "current flow" state anywhere — the carried
        geometry lives only on the step instance it was handed to, and
        is passed explicitly by the caller.
    """

    #: "etching" | "deposition" | "oxidation"
    category: ClassVar[str] = ""

    #: short, stable identifier used as the registry key, e.g. "sf6o2"
    name: ClassVar[str] = ""

    #: human-readable label for GUI/CLI display
    display_name: ClassVar[str] = ""

    def __init__(self, inherited_domain: Optional[Any] = None):
        """inherited_domain : a ViennaPS Domain from a previous step to
        continue processing on. None (the default) means this step
        builds its own fresh wafer, exactly as in Phase 1-12 — so
        `registry.get(...)()` keeps working unchanged.
        """
        self._inherited_domain = inherited_domain
        #: the domain this step actually processed, set by
        #: prepare_domain() so a flow orchestrator can persist it
        #: afterwards without reaching into ViennaPS itself.
        self.last_domain: Optional[Any] = None

    def prepare_domain(self, recipe: Dict[str, Any]):
        """Return the domain this step should process.

        Fresh case (no inherited domain): builds a new Domain + trench
        from the recipe, identical to the previous inline
        session.create_domain()/session.make_trench() pair.

        Inherited case: returns the carried domain untouched — no new
        Domain, no new trench — and warns about any initial-geometry
        recipe keys that therefore cannot apply.
        """
        if self._inherited_domain is not None:
            ignored = [k for k in INITIAL_GEOMETRY_RECIPE_KEYS if k in recipe]
            if ignored:
                warnings.warn(
                    f"{type(self).__name__}: continuing from an inherited domain, so "
                    f"initial-geometry recipe keys {ignored} are ignored (the wafer "
                    f"already exists). Physical process parameters are still applied.",
                    UserWarning,
                    stacklevel=2,
                )
            self.last_domain = self._inherited_domain
            return self._inherited_domain

        # Arbitrary multi-span mask, when the recipe asks for one.
        # MakeTrench below can only build `opaque | open | opaque` (one
        # centred window); `mask_spans_um` covers any pattern, including
        # the complement a MOSFET source/drain implant mask needs
        # (`open | opaque | open`). Purely additive: a recipe without
        # this key takes the identical MakeTrench path as before.
        if recipe.get("mask_spans_um"):
            geometry = session.make_mask_spans(
                grid_delta_um=recipe["grid_delta_um"],
                x_extent_um=recipe["x_extent_um"],
                y_extent_um=recipe["y_extent_um"],
                spans_um=[tuple(span) for span in recipe["mask_spans_um"]],
                mask_height_um=max(recipe["pr_thickness_um"], 0.1),
                mask_material=recipe.get("mask_material", "Mask"),
            )
            self.last_domain = geometry
            return geometry

        geometry = session.create_domain(
            grid_delta_um=recipe["grid_delta_um"],
            x_extent_um=recipe["x_extent_um"],
            y_extent_um=recipe["y_extent_um"],
        )
        session.make_trench(
            geometry,
            # round() clears float64 subtraction noise (e.g. 1.3 - 0.7 ==
            # 0.6000000000000001, off from 0.6 by ~1e-16): confirmed
            # against the installed ViennaPS 4.6.2 that MakeTrench's
            # window-cutting is unstable at exactly that noise level for
            # specific (width, gridDelta) combinations (fails only when
            # the ULP-level error rounds *up*, e.g. 0.05/0.1 gridDelta at
            # this width; adjacent values one ULP below, or 10x further
            # off, both cut correctly) -- an interior HRLE/level-set
            # rasterization edge case in ViennaPS/ViennaLS, not this
            # project's code. 9 decimal places is nanometer-scale
            # precision on a micrometer-scale recipe value, far finer
            # than any real recipe needs, so this cannot change intended
            # geometry -- it only removes arithmetic noise below that.
            trench_width_um=round(
                recipe["mask_right_um"] - recipe["mask_left_um"], 9
            ),
            trench_depth_um=0.0,
            mask_height_um=recipe["pr_thickness_um"],
        )
        self.last_domain = geometry
        return geometry

    @abstractmethod
    def run(self, recipe: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
        """Execute this process step and return a result dict.

        Implementations are expected to return at least:
            {"final_mesh": str, "snapshots": list[str]}
        so callers can treat every category/model uniformly. Additional
        model-specific keys (e.g. "cycles" for Bosch) may be included.
        """
        raise NotImplementedError
