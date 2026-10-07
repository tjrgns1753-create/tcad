#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Save a CharacterizationResult to CSV or JSON. No devsim (or any
backend) import here — operates only on the plain dataclasses in
tcad.characterization.interface.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List

from tcad.characterization.interface import CharacterizationResult, established_current_unit


def save_csv(result: CharacterizationResult, path: str) -> str:
    """Write one row per BiasPoint: sweep voltage + every contact's
    current. Returns the written path as str.
    """
    contacts: List[str] = sorted(
        {c for point in result.points for c in point.currents}
    )

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # A result that carries an established unit (2D DevSim: "A/cm") names it in the header; a result without one is labelled
        # unit_unknown -- never assumed to be A.
        unit = established_current_unit(result.metadata)
        suffix = unit.replace("/", "_per_") if unit else "unit_unknown"
        writer.writerow(["sweep_voltage_V"] + [f"I_{c}_{suffix}" for c in contacts])
        for point in result.points:
            sweep_v = point.voltages.get(result.sweep_contact, "")
            row = [sweep_v] + [point.currents.get(c, "") for c in contacts]
            writer.writerow(row)

    return str(path)


def save_json(result: CharacterizationResult, path: str) -> str:
    """Write the full CharacterizationResult (all voltages + currents
    per point, plus metadata) as JSON. Returns the written path as str.
    """
    payload = {
        "name": result.name,
        "device": result.device,
        "region": result.region,
        "sweep_contact": result.sweep_contact,
        "metadata": result.metadata,
        "points": [
            {"voltages": p.voltages, "currents": p.currents, "converged": p.converged}
            for p in result.points
        ],
    }
    Path(path).write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    return str(path)


def save_measurement_bundle(result: CharacterizationResult, path: str) -> str:
    """CSV plus full result JSON and CSV hash. No new physics or unit inference.

    Invalid evidence is rejected before replacing either existing file. The
    two final os.replace calls are NOT a two-file transaction; consumers must
    check the companion's csv_sha256 before treating the pair as evidence.
    """
    from dataclasses import replace
    import hashlib
    import os
    import tempfile
    from tcad.characterization.interface import validate_bias_point
    if not result.points:
        raise ValueError("Cannot export an empty measurement.")
    for point in result.points:
        validate_bias_point(point)
        if result.sweep_contact not in point.voltages:
            raise ValueError("Measurement is missing its sweep voltage.")
    json.dumps(result.metadata, allow_nan=False)
    target = Path(path)
    companion = Path(str(target) + ".metadata.json")
    staged = []
    try:
        for _ in range(2):
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".measurement_", suffix=".tmp", delete=False) as f:
                staged.append(Path(f.name))
        save_csv(result, str(staged[0]))
        digest = hashlib.sha256(staged[0].read_bytes()).hexdigest()
        metadata = {**result.metadata, "export_evidence": {"schema": 1, "csv_sha256": digest}}
        save_json(replace(result, metadata=metadata), str(staged[1]))
        os.replace(staged[0], target)
        os.replace(staged[1], companion)
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)
    return str(companion)


def save_cv_csv(result: CharacterizationResult, path: str) -> str:
    """Write a C-V sweep's metadata (capacitance_F / capacitance_voltages_V,
    see tcad.characterization.cv_sweep.run_mos_cv_sweep) to CSV.
    Returns the written path as str.
    """
    voltages = result.metadata.get("capacitance_voltages_V", [])
    capacitance = result.metadata.get("capacitance_F", [])

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["gate_voltage_V", "capacitance_F"])
        for v, c in zip(voltages, capacitance):
            writer.writerow([v, c])

    return str(path)
