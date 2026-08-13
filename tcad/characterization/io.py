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

from tcad.characterization.interface import CharacterizationResult


def save_csv(result: CharacterizationResult, path: str) -> str:
    """Write one row per BiasPoint: sweep voltage + every contact's
    current. Returns the written path as str.
    """
    contacts: List[str] = sorted(
        {c for point in result.points for c in point.currents}
    )

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sweep_voltage_V"] + [f"I_{c}_A" for c in contacts])
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
            {"voltages": p.voltages, "currents": p.currents}
            for p in result.points
        ],
    }
    Path(path).write_text(json.dumps(payload, indent=2))
    return str(path)


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
