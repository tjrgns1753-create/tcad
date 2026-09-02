#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Canonical Process -> Device handoff artifact.

This module is intentionally backend-independent: no viennaps, meshio,
or devsim imports here. It defines the boundary data shape that
tcad/mesh/viennaps_adapter.py (Process side) produces and
tcad/device/devsim/mesh_import.py (Device side) consumes. Neither side
imports the other directly — everything crosses through ProcessResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MaterialRegion:
    """One material region present in the process-generated mesh.

    `tag` is the integer value found in the mesh's material cell-data
    array (e.g. ViennaPS's per-triangle "Material" field) for this
    region; `name` is the human-readable region/material name derived
    from it (e.g. "Si", "Mask").
    """

    name: str
    tag: int


@dataclass
class DopingRegion:
    """Doping assigned to one region — either uniform (Phase 7) or a
    step junction along one axis (Phase 8).

    region : region name — matches a MaterialRegion.name on the same
        ProcessResult (e.g. "Si").
    net_doping_cm3 : uniform case — constant net doping (cm^-3),
        positive = net donor (n-type), negative = net acceptor
        (p-type). None for a step-junction region.
    junction_axis / junction_position_um / donor_conc_cm3 /
        acceptor_conc_cm3 : step-junction case — donor_conc_cm3 applies
        on the side where `junction_axis` coordinate is greater than
        `junction_position_um`; acceptor_conc_cm3 on the other side.
        All None for a uniform region.
    peak_conc_cm3 / peak_position_um / straggle_um : gaussian_implant
        case — a 1D Gaussian net-doping profile along `junction_axis`
        (reused from the step-junction fields above, same meaning: the
        position axis), centered at peak_position_um with peak value
        peak_conc_cm3 (signed: positive = net donor, negative = net
        acceptor, same convention as net_doping_cm3) and standard
        deviation straggle_um. None for uniform/step-junction regions.
    implant_windows : implant_windows case — a background doping
        (net_doping_cm3, reused from the uniform case's same field/
        convention) with zero or more rectangular implants SUPERPOSED
        on top, along `junction_axis` (reused, same meaning: the
        position axis this region's windows are laid out on). Each
        window is a dict {"min_um": float, "max_um": float,
        "conc_cm3": float} — conc_cm3 ADDS to the background wherever
        min_um <= axis <= max_um (signed, same convention as
        net_doping_cm3; overlapping windows sum). Models e.g. a
        source/drain implant superposed on a channel/body background —
        the real physical relationship (an implant adds dopant on top
        of whatever was already there), not a replacement. None for
        every other kind.
    donor_peak_conc_cm3 / acceptor_peak_conc_cm3 : gaussian_implant
        case, donor/acceptor input variant — both profiles share the
        SAME peak_position_um/straggle_um (this project has no
        implant-energy model to give them independently-derived
        shapes; see CLAUDE.md's "no fake physics parameters" rule).
        peak_conc_cm3 is computed as donor - acceptor and is what
        every downstream consumer (doping_mapping.py, the renderer)
        continues to read. None when the region was built from a
        plain signed peak_conc_cm3 instead.
    donor_species / acceptor_species : label-only metadata (e.g. "P",
        "B", "As") for the process log and any future report — never
        read by doping_mapping.py or ViennaPS/DevSim, since neither
        backend has any species-dependent physics. None if unset.
    gaussian_terms : `gaussian_implant` case, MULTIPLE-implant variant —
        a list of independent term dicts (`species`, `polarity`,
        `peak_conc_cm3`, `peak_position_um`, `straggle_um`,
        `thermal_budget_cm2`), each representing one implant call that
        was ADDED rather than replacing what came before (see
        `tcad.physics.doping.apply_gaussian_implant_doping`'s
        `existing=` parameter). `None` for every region built from a
        single implant call with no `existing=` — the plain
        `peak_conc_cm3`/`peak_position_um`/`straggle_um` fields above
        still carry that one profile, unchanged. When both this and
        the plain fields are set, `gaussian_terms` is authoritative
        (device-layer and process-layer readers that understand it use
        it INSTEAD of the plain fields, which then describe only the
        region's original single-implant form for any caller not yet
        updated to read `gaussian_terms`).
    """

    region: str
    net_doping_cm3: Optional[float] = None
    junction_axis: Optional[str] = None
    junction_position_um: Optional[float] = None
    donor_conc_cm3: Optional[float] = None
    acceptor_conc_cm3: Optional[float] = None
    peak_conc_cm3: Optional[float] = None
    peak_position_um: Optional[float] = None
    straggle_um: Optional[float] = None
    implant_windows: Optional[List[Dict[str, float]]] = None
    donor_peak_conc_cm3: Optional[float] = None
    acceptor_peak_conc_cm3: Optional[float] = None
    donor_species: Optional[str] = None
    acceptor_species: Optional[str] = None
    gaussian_terms: Optional[List[Dict[str, Any]]] = None


@dataclass
class DopingProfile:
    """Doping data for a ProcessResult.

    kind : "uniform" (Phase 7) — one constant net_doping_cm3 per
        region. "step_junction" (Phase 8) — one region split into a
        donor side and an acceptor side along an axis. "gaussian_implant"
        — a 1D Gaussian net-doping profile along an axis (peak_conc_cm3,
        peak_position_um, straggle_um on DopingRegion). "implant_windows"
        — a background doping plus zero or more laterally-windowed
        implants superposed on top (implant_windows on DopingRegion) —
        e.g. source/drain regions superposed on a channel/body
        background within the same region.
    regions : one DopingRegion per doped region.
    """

    kind: str = "uniform"
    regions: List[DopingRegion] = field(default_factory=list)


@dataclass
class ProcessResult:
    """Canonical artifact handed from a Process step to a Device backend.

    volume_mesh_path : path to the process-generated volume mesh
        (e.g. a ViennaPS ProcessStep's "final_mesh" result).
    material_field : name of the cell-data array in that mesh holding
        per-cell material tags (matches ViennaPS's "Material" field).
    material_regions : materials actually present in the mesh, as
        (name, tag) pairs — see MaterialRegion.
    doping : Optional; None if no doping has been applied yet, or a
        DopingProfile built by tcad.physics.doping (kept separate from
        the 13 ViennaPS process models — see that module).
    domain_state_path : Optional; path to a persisted backend domain
        state (for ViennaPS, a .vpsd file written by
        tcad.backends.viennaps.session.save_domain_state) that a
        following process step can continue from. None for a
        single-step result, which is what every Phase 1-12 caller
        produces — this field is purely additive. It is a plain path
        string, never a live backend object, so this module stays
        backend-independent.
    structure : Optional; a plain dict snapshot of the backend domain's
        structural state at the end of this step (materials present,
        level-set count, bounding box, grid spacing). Recorded by the
        process-flow layer so callers can see what each step changed.
    physics_status : Optional; a plain dict reporting what a process
        step's physics knew about its own parameters (Resolution /
        Provenance per parameter). None until a step populates it —
        purely additive, like domain_state_path/structure.
    numerical_status : Optional; a plain dict reporting numerical
        (mesh-resolution) concerns, e.g. under-resolved geometry. Kept
        on its own key/axis, separate from physics_status, so a
        "we don't know the physics" fact and a "the mesh may be too
        coarse" fact never get merged together. None until a step
        populates it.
    units : length unit the mesh coordinates are in.
    metadata : free-form extra info (e.g. process snapshots), not
        relied on by any Device backend.
    """

    volume_mesh_path: str
    material_field: str = "Material"
    material_regions: List[MaterialRegion] = field(default_factory=list)
    doping: Optional[DopingProfile] = None
    units: str = "um"
    metadata: Dict[str, Any] = field(default_factory=dict)
    domain_state_path: Optional[str] = None
    structure: Optional[Dict[str, Any]] = None
    physics_status: Optional[dict] = None
    numerical_status: Optional[dict] = None
