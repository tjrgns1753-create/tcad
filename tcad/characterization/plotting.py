#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Basic I-V curve plotting from a CharacterizationResult. No devsim
import here either — matplotlib only, operating on the plain
dataclasses in tcad.characterization.interface.
"""

from __future__ import annotations

from tcad.characterization.interface import CharacterizationResult


def save_iv_plot(result: CharacterizationResult, path: str) -> str:
    """Plot sweep voltage vs. current at every contact. Returns the
    written path as str.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    contacts = sorted({c for point in result.points for c in point.currents})
    sweep_voltages = [point.voltages.get(result.sweep_contact, 0.0) for point in result.points]

    fig, ax = plt.subplots(figsize=(6, 4))
    for contact in contacts:
        currents = [point.currents.get(contact, 0.0) for point in result.points]
        ax.plot(sweep_voltages, currents, marker="o", label=f"I({contact})")

    ax.set_xlabel(f"{result.sweep_contact} voltage (V)")
    ax.set_ylabel("Current (A)")
    ax.set_title(f"{result.name} — {result.device}/{result.region}")
    ax.legend()
    ax.grid(True)

    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)

    return str(path)


def save_cv_plot(result: CharacterizationResult, path: str) -> str:
    """Plot a C-V sweep's capacitance vs. gate voltage (see
    tcad.characterization.cv_sweep.run_mos_cv_sweep's metadata).
    Returns the written path as str.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    voltages = result.metadata.get("capacitance_voltages_V", [])
    capacitance = result.metadata.get("capacitance_F", [])

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(voltages, capacitance, marker="o")
    ax.set_xlabel(f"{result.sweep_contact} voltage (V)")
    ax.set_ylabel("Capacitance (F)")
    ax.set_title(f"{result.name} — {result.device}/{result.region}")
    ax.grid(True)

    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)

    return str(path)
