#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tcad CLI: run the full Process -> Mesh -> Doping -> Device ->
Characterization pipeline from one JSON config file.

This module only orchestrates existing Phase 1-9 functions — it
contains no process, mesh, doping, device, or characterization physics
of its own. See README.md for the config schema and a full example.

Usage:
    python -m tcad.cli.run_pipeline config.json
    tcad config.json          # after `pip install tcad[full]`
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


def _run_process_step(cfg: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
    category = cfg["category"]
    model = cfg["model"]
    recipe = cfg["recipe"]

    if category == "etching":
        import tcad.process.etching  # noqa: F401 -- registers models
    elif category == "deposition":
        import tcad.process.deposition  # noqa: F401
    elif category == "oxidation":
        import tcad.process.oxidation  # noqa: F401
    else:
        raise ValueError(f"Unknown process category: {category!r}")

    from tcad.process import registry

    step_cls = registry.get(category, model)
    output_dir = workdir / "process_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return step_cls().run(recipe, str(output_dir))


def _build_process_result(step_result: Dict[str, Any]):
    from tcad.mesh.viennaps_adapter import build_process_result
    return build_process_result(step_result)


def _apply_doping(process_result, cfg: Dict[str, Any] | None):
    if not cfg:
        return process_result

    from tcad.physics.doping import (
        apply_gaussian_implant_doping,
        apply_step_junction_doping,
        apply_uniform_doping,
    )

    kind = cfg["kind"]
    if kind == "uniform":
        return apply_uniform_doping(process_result, cfg["doping_by_region_cm3"])
    if kind == "step_junction":
        return apply_step_junction_doping(
            process_result,
            region=cfg["region"],
            junction_axis=cfg["junction_axis"],
            junction_position_um=cfg["junction_position_um"],
            donor_conc_cm3=cfg["donor_conc_cm3"],
            acceptor_conc_cm3=cfg["acceptor_conc_cm3"],
        )
    if kind == "gaussian_implant":
        return apply_gaussian_implant_doping(
            process_result,
            region=cfg["region"],
            junction_axis=cfg["junction_axis"],
            peak_position_um=cfg["peak_position_um"],
            straggle_um=cfg["straggle_um"],
            peak_conc_cm3=cfg["peak_conc_cm3"],
        )
    raise ValueError(f"Unknown doping kind: {kind!r}")


def _import_device(process_result, cfg: Dict[str, Any]):
    from tcad.device.devsim.mesh_import import import_process_result

    return import_process_result(
        process_result,
        mesh_name=cfg.get("mesh_name", "cli_mesh"),
        device_name=cfg.get("device_name", "cli_device"),
        material_map=cfg.get("material_map"),
        contact_regions=cfg.get("contact_regions"),
        contact_axis=cfg.get("contact_axis", "x"),
        length_scale_to_cm=cfg.get("length_scale_to_cm", 1.0),
        interface_region_pairs=[tuple(p) for p in cfg["interface_region_pairs"]]
        if cfg.get("interface_region_pairs")
        else None,
        contact_sides=cfg.get("contact_sides"),
        refine_near_um=cfg.get("refine_near_um"),
        refine_axis=cfg.get("refine_axis", "x"),
        refine_half_width_um=cfg.get("refine_half_width_um", 0.1),
        refine_levels=cfg.get("refine_levels", 4),
    )


def _apply_device_doping(imported, process_result, cfg: Dict[str, Any] | None):
    if not cfg or process_result.doping is None:
        return
    from tcad.device.devsim.doping_mapping import apply_doping

    apply_doping(imported.device, process_result.doping, length_scale_to_cm=cfg.get("length_scale_to_cm", 1.0))


def _run_characterization(imported, cfg: Dict[str, Any]):
    kind = cfg["type"]

    if kind == "iv":
        from tcad.characterization.iv_sweep import run_iv_sweep
        return run_iv_sweep(
            device=imported.device,
            region=cfg["region"],
            all_contacts=imported.contacts,
            sweep_contact=cfg["sweep_contact"],
            sweep_voltages=cfg["sweep_voltages"],
            fixed_contacts=cfg.get("fixed_contacts"),
            conductivity=cfg.get("conductivity", 1.0),
        )

    if kind == "pn_junction_iv":
        from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
        return run_pn_junction_iv_sweep(
            device=imported.device,
            region=cfg["region"],
            all_contacts=imported.contacts,
            sweep_contact=cfg["sweep_contact"],
            sweep_voltages=cfg["sweep_voltages"],
            fixed_contacts=cfg.get("fixed_contacts"),
            temperature_k=cfg.get("temperature_k", 300.0),
        )

    if kind == "mos_cv":
        from tcad.characterization.cv_sweep import run_mos_cv_sweep
        return run_mos_cv_sweep(
            device=imported.device,
            si_region=cfg["si_region"],
            oxide_region=cfg["oxide_region"],
            gate_contact=cfg["gate_contact"],
            substrate_contact=cfg["substrate_contact"],
            interface_name=cfg["interface_name"],
            gate_voltages=cfg["gate_voltages"],
            temperature_k=cfg.get("temperature_k", 300.0),
        )

    raise ValueError(f"Unknown characterization type: {kind!r}")


def _save_outputs(result, cfg: Dict[str, Any], workdir: Path) -> Dict[str, str]:
    from tcad.characterization.io import save_csv, save_cv_csv, save_json
    from tcad.characterization.plotting import save_cv_plot, save_iv_plot

    output_dir = workdir / "characterization_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, str] = {}

    is_cv = result.name == "mos_cv_sweep"

    csv_path = output_dir / cfg.get("csv_filename", "result.csv")
    written["csv"] = save_cv_csv(result, str(csv_path)) if is_cv else save_csv(result, str(csv_path))

    json_path = output_dir / cfg.get("json_filename", "result.json")
    written["json"] = save_json(result, str(json_path))

    plot_path = output_dir / cfg.get("plot_filename", "result.png")
    written["plot"] = save_cv_plot(result, str(plot_path)) if is_cv else save_iv_plot(result, str(plot_path))

    return written


def _cleanup_device(device_name: str, mesh_name: str) -> None:
    """Delete a DevSim device and its underlying mesh from DevSim's
    global state, so a later run_pipeline() call in the same process
    isn't affected by it.

    Why both calls are needed (confirmed by real execution, not
    guessed): devsim.solve() takes no `device=` argument — it solves
    every currently registered device together as one combined system,
    so a leftover device from an earlier run_pipeline() call can make
    a later, unrelated call fail to reconverge. delete_device() alone
    is not enough either: the underlying mesh (from create_gmsh_mesh())
    survives delete_device(), and re-importing with the same mesh name
    afterward fails with 'A mesh already exists with name ...' — only
    delete_mesh() actually frees that name for reuse.

    Best-effort: this always runs from a `finally` block (see
    run_pipeline()), including after the pipeline itself already
    failed. If cleanup itself raises (e.g. devsim became unavailable
    mid-run, or the device/mesh was already removed by other means),
    that cleanup failure is swallowed rather than replacing or masking
    whatever the `try` block was already returning or raising.
    """
    try:
        from tcad.device.devsim import backend
        module = backend.require_devsim()
        module.delete_device(device=device_name)
        module.delete_mesh(mesh=mesh_name)
    except Exception:
        pass


def run_pipeline(config: Dict[str, Any], workdir: Path) -> Dict[str, Any]:
    """Run the full pipeline described by `config`. Returns a summary
    dict with the ProcessResult regions, ImportedDevice info, and the
    written output file paths.

    Safe to call more than once in the same Python process: the DevSim
    device (and its mesh) this call creates is always deleted before
    returning or raising — see _cleanup_device() — so it can never
    affect a later run_pipeline() call's solve(). Process models,
    ProcessResult, and every Phase 5-9 function's signature/behavior
    are unchanged; only this orchestration function's device lifecycle
    changed.
    """
    step_result = _run_process_step(config["process"], workdir)
    process_result = _build_process_result(step_result)
    process_result = _apply_doping(process_result, config.get("doping"))

    imported = _import_device(process_result, config["device"])
    try:
        _apply_device_doping(imported, process_result, config.get("doping_device", config.get("device")))

        result = _run_characterization(imported, config["characterization"])
        written = _save_outputs(result, config.get("outputs", {}), workdir)

        return {
            "process_final_mesh": step_result.get("final_mesh"),
            "regions": [r.name for r in process_result.material_regions],
            "device": imported.device,
            "contacts": imported.contacts,
            "interfaces": imported.interfaces,
            "characterization": result.name,
            "outputs": written,
        }
    finally:
        _cleanup_device(imported.device, imported.mesh)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="tcad",
        description="Run a Process -> Mesh -> Doping -> Device -> Characterization pipeline from a JSON config.",
    )
    parser.add_argument("config", help="Path to a pipeline JSON config file (see README.md).")
    parser.add_argument(
        "--workdir", default=None,
        help="Directory for intermediate/output files (default: alongside the config file).",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    workdir = Path(args.workdir) if args.workdir else config_path.resolve().parent / "tcad_run"
    workdir.mkdir(parents=True, exist_ok=True)

    summary = run_pipeline(config, workdir)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
