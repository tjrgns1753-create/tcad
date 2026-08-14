#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ============================================================
# TCAD_2D_REAL_REWRITE_V2
# ============================================================
# This is intentionally a new single-file implementation.
#
# PROCESS FLOW
#   Si wafer
#     -> film
#     -> photoresist coat
#     -> mask
#     -> exposure
#     -> develop
#     -> etch
#     -> strip
#
# ETCH BACKEND
#   ViennaPS 2-D
#
# Current real ViennaPS recipe:
#   Bosch DRIE
#       passivation
#       bottom breakthrough
#       silicon etch
#       repeat
#
# This program is an educational process-flow front end. It does not
# claim to reproduce a complete commercial plasma chemistry model.
# ============================================================

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Phase 1 refactor: Wafer/BoschRecipe live in tcad.core; ViennaPS
# session/domain/I-O plumbing lives in tcad.backends.viennaps.
# Phase 2 refactor: Bosch DRIE moved from tcad.backends.viennaps.bosch
# to tcad.process.etching.bosch_drie — it is now one registered Etching
# model among several (SF6O2, Fluorocarbon, IBE, WetEtching, Isotropic,
# Directional), not a special-cased backend function. worker_main() now
# dispatches through process_registry for whichever model the GUI picks.
from tcad.core import BoschRecipe, Wafer
from tcad.backends.viennaps import session as viennaps_session
from tcad.process import registry as process_registry
import tcad.process.etching  # noqa: F401 -- import side effect: registers etch models
import tcad.process.deposition  # noqa: F401 -- import side effect: registers deposition models
import tcad.process.oxidation  # noqa: F401 -- import side effect: registers oxidation models

# ============================================================
# VIENNAPS ETCH ENGINE
# ============================================================
#
# worker_main() dispatches through process_registry.get("etching", ...)
# so any registered etching model works, not just Bosch. Bosch's own
# algorithm (MakeTrench, passivation, breakthrough, silicon etch, cycle
# loop, snapshotting) is unchanged since Phase 1.

# Canvas polygon cap for _draw_real_mesh_result -- see its use for why.
_MAX_RENDERED_TRIANGLES = 2000

# ============================================================
# SUBPROCESS WORKER
# ============================================================

def worker_main(config_file: str, result_file: str):

    try:
        config = json.loads(
            Path(config_file).read_text(
                encoding="utf-8"
            )
        )

        # Any registered etching model works here (Bosch included): the
        # GUI sets "_etch_model_key" to pick which one.
        step_cls = process_registry.get("etching", config["_etch_model_key"])
        result = step_cls().run(
            config,
            config["output_dir"],
        )

        payload = {
            "success": True,
            **result,
        }

    except Exception as exc:

        payload = {
            "success": False,
            "error": repr(exc),
        }

    Path(result_file).write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# GUI
# ============================================================

class TCADApplication(tk.Tk):

    def __init__(self):
        super().__init__()

        self.title(
            "TCAD 2D — REAL PROCESS FLOW — V2"
        )

        self.geometry(
            "1380x850"
        )

        self.minsize(
            1100,
            700,
        )

        self.wafer = Wafer()
        self.recipe = BoschRecipe()
        # Path to the real ViennaPS final_mesh from the last successful
        # run_etch(), so redraw() can draw the actual geometry instead
        # of the placeholder rectangle. None until an etch succeeds.
        self.last_final_mesh = None

        self.history = []

        # Explicit process-state machine.
        # The simulator never jumps from PR coat directly to develop.
        self.process_stage = "wafer"

        self._make_style()
        self._make_header()
        self._make_body()
        self._make_status()

        self.redraw()

    # --------------------------------------------------------
    # STYLE
    # --------------------------------------------------------

    def _make_style(self):

        style = ttk.Style(self)

        try:
            style.theme_use("clam")
        except Exception:
            pass

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    def _make_header(self):

        header = ttk.Frame(
            self,
            padding=(12, 10),
        )

        header.pack(
            fill="x"
        )

        ttk.Label(
            header,
            text="TCAD 2D",
            font=(
                "Segoe UI",
                21,
                "bold",
            ),
        ).pack(
            side="left"
        )

        ttk.Label(
            header,
            text=(
                "  REAL PROCESS FLOW / "
                "LITHOGRAPHY + VIENNAPS"
            ),
            font=(
                "Segoe UI",
                10,
            ),
        ).pack(
            side="left"
        )

        backend = (
            "VIENNAPS READY"
            if viennaps_session.is_available()
            else "VIENNAPS NOT INSTALLED"
        )

        ttk.Label(
            header,
            text=backend,
            foreground=(
                "green"
                if viennaps_session.is_available()
                else "red"
            ),
            font=(
                "Segoe UI",
                10,
                "bold",
            ),
        ).pack(
            side="right"
        )

    # --------------------------------------------------------
    # STATUS BAR
    # --------------------------------------------------------

    def _make_status(self):
        self.status_var = tk.StringVar(
            value="Ready — TCAD_2D_REAL_REWRITE_V2"
        )
        ttk.Label(
            self,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
            padding=5,
        ).pack(
            fill="x",
            side="bottom",
        )

        # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    def _make_body(self):

        body = ttk.Frame(
            self
        )

        body.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=5,
        )

        self._make_process_panel(body)
        self._make_cross_section(body)
        self._make_control_panel(body)

    # --------------------------------------------------------
    # PROCESS PANEL
    # --------------------------------------------------------

    def _make_process_panel(
        self,
        parent,
    ):

        panel = ttk.LabelFrame(
            parent,
            text="Fabrication sequence",
            padding=10,
        )

        panel.pack(
            side="left",
            fill="y",
        )

        stages = [
            "Si wafer",
            "Film / oxide",
            "PR coat",
            "Mask alignment",
            "Exposure",
            "Develop",
            "Etch",
            "PR strip",
        ]

        self.stage_labels = []

        for index, name in enumerate(stages):

            label = ttk.Label(
                panel,
                text=(
                    f"○ {index + 1:02d}  {name}"
                ),
                width=25,
                padding=(
                    3,
                    7,
                ),
            )

            label.pack(
                anchor="w"
            )

            self.stage_labels.append(
                label
            )

        ttk.Separator(
            panel
        ).pack(
            fill="x",
            pady=12,
        )

        ttk.Button(
            panel,
            text="NEW WAFER",
            command=self.reset,
        ).pack(
            fill="x",
            pady=3,
        )

        ttk.Button(
            panel,
            text="SAVE PROJECT",
            command=self.save_project,
        ).pack(
            fill="x",
            pady=3,
        )

        ttk.Button(
            panel,
            text="LOAD PROJECT",
            command=self.load_project,
        ).pack(
            fill="x",
            pady=3,
        )

    # --------------------------------------------------------
    # CROSS SECTION
    # --------------------------------------------------------

    def _make_cross_section(
        self,
        parent,
    ):

        frame = ttk.LabelFrame(
            parent,
            text="2D process cross-section",
            padding=5,
        )

        frame.pack(
            side="left",
            fill="both",
            expand=True,
            padx=10,
        )

        self.canvas = tk.Canvas(
            frame,
            bg="white",
            highlightthickness=1,
            highlightbackground="#777",
        )

        self.canvas.pack(
            fill="both",
            expand=True,
        )

        self.canvas.bind(
            "<Configure>",
            lambda event: self.redraw(),
        )

    # --------------------------------------------------------
    # CONTROL PANEL
    # --------------------------------------------------------

    def _make_control_panel(
        self,
        parent,
    ):

        # GUI-only: the control panel is taller than most windows once
        # the Etch recipe's fields are stacked, which previously pushed
        # the START ETCH button and the whole Process log below the
        # window edge with no way to reach them. Hosting the panel in a
        # scrollable canvas keeps every widget reachable at any window
        # height. No process/physics logic is affected -- `panel` is
        # still the same ttk.Frame the sub-panels are built into.
        scroll_host = ttk.Frame(parent)
        scroll_host.pack(
            side="right",
            fill="y",
        )

        scroll_canvas = tk.Canvas(
            scroll_host,
            width=350,
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(
            scroll_host,
            orient="vertical",
            command=scroll_canvas.yview,
        )
        scroll_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)

        panel = ttk.Frame(
            scroll_canvas,
            width=350,
        )
        panel_window = scroll_canvas.create_window(
            (0, 0),
            window=panel,
            anchor="nw",
            width=350,
        )

        def _on_panel_configure(event):
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

        panel.bind("<Configure>", _on_panel_configure)

        def _on_canvas_configure(event):
            scroll_canvas.itemconfigure(panel_window, width=event.width)

        scroll_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            if event.num == 4:
                scroll_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                scroll_canvas.yview_scroll(1, "units")
            else:
                scroll_canvas.yview_scroll(
                    -1 * int(event.delta / 120), "units"
                )

        # Windows/macOS use <MouseWheel>; X11 reports buttons 4/5.
        scroll_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        scroll_canvas.bind_all("<Button-4>", _on_mousewheel)
        scroll_canvas.bind_all("<Button-5>", _on_mousewheel)

        self._make_lithography_panel(
            panel
        )

        self._make_etch_panel(
            panel
        )

        # etch_button (created above) is required by
        # _update_process_buttons(); call it only after both panels
        # exist so widget creation order / visual layout is unchanged,
        # only the timing of this refresh call moves.
        self._update_process_buttons()

        self._make_log_panel(
            panel
        )

    # --------------------------------------------------------
    # LITHOGRAPHY
    # --------------------------------------------------------

    def _make_lithography_panel(
        self,
        parent,
    ):

        frame = ttk.LabelFrame(
            parent,
            text="Lithography",
            padding=10,
        )

        frame.pack(
            fill="x"
        )

        self.pr_var = self._field(
            frame,
            "PR thickness (µm)",
            self.wafer.pr_thickness_um,
        )

        self.left_var = self._field(
            frame,
            "Mask opening left (µm)",
            self.wafer.mask_left_um,
        )

        self.right_var = self._field(
            frame,
            "Mask opening right (µm)",
            self.wafer.mask_right_um,
        )

        self.depth_var = self._field(
            frame,
            "Si substrate depth (µm)",
            self.wafer.silicon_depth_um,
        )

        self.dose_var = self._field(
            frame,
            "Exposure dose",
            self.wafer.exposure_dose,
        )

        self.develop_var = self._field(
            frame,
            "Develop time (s)",
            self.wafer.develop_time_s,
        )

        ttk.Label(
            frame,
            text="Run each fabrication step separately:",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(8, 4))

        self.coat_button = ttk.Button(
            frame,
            text="1. PR COAT",
            command=self.process_pr_coat,
        )
        self.coat_button.pack(fill="x", pady=2)

        self.align_button = ttk.Button(
            frame,
            text="2. MASK ALIGNMENT",
            command=self.process_mask_alignment,
        )
        self.align_button.pack(fill="x", pady=2)

        self.expose_button = ttk.Button(
            frame,
            text="3. EXPOSURE",
            command=self.process_exposure,
        )
        self.expose_button.pack(fill="x", pady=2)

        self.develop_button = ttk.Button(
            frame,
            text="4. DEVELOP",
            command=self.process_develop,
        )
        self.develop_button.pack(fill="x", pady=2)

        self.strip_button = ttk.Button(
            frame,
            text="PR STRIP",
            command=self.process_pr_strip,
        )
        self.strip_button.pack(fill="x", pady=(8, 2))

    # --------------------------------------------------------
    # ETCH
    # --------------------------------------------------------

    def _make_etch_panel(
        self,
        parent,
    ):

        frame = ttk.LabelFrame(
            parent,
            text="Etch recipe",
            padding=10,
        )

        frame.pack(
            fill="x",
            pady=10,
        )

        ttk.Label(
            frame,
            text="Etch process",
        ).pack(
            anchor="w"
        )

        self.etch_model = tk.StringVar(
            value="Bosch DRIE"
        )

        ttk.Combobox(
            frame,
            textvariable=self.etch_model,
            state="readonly",
            values=[
                "Bosch DRIE",
                "Directional RIE",
                "Isotropic etch",
                "SF6/O2",
            ],
        ).pack(
            fill="x"
        )

        self.cycles_var = self._field(
            frame,
            "Bosch cycles",
            self.recipe.cycles,
        )

        self.grid_var = self._field(
            frame,
            "Grid delta (µm)",
            self.recipe.grid_delta_um,
        )

        self.etch_time_var = self._field(
            frame,
            "Etch time / cycle (s)",
            self.recipe.etch_time_s,
        )

        self.poly_var = self._field(
            frame,
            "Polymer deposition rate",
            self.recipe.polymer_rate,
        )

        self.poly_stick_var = self._field(
            frame,
            "Polymer sticking",
            self.recipe.polymer_sticking,
        )

        self.ion_exp_var = self._field(
            frame,
            "Ion source exponent",
            self.recipe.ion_source_exponent,
        )

        self.ion_rate_var = self._field(
            frame,
            "Ion Si contribution",
            self.recipe.ion_rate,
        )

        self.neutral_rate_var = self._field(
            frame,
            "Neutral Si contribution",
            self.recipe.neutral_rate,
        )

        self.neutral_stick_var = self._field(
            frame,
            "Neutral sticking",
            self.recipe.neutral_sticking,
        )

        self.directional_rate_var = self._field(
            frame,
            "Directional RIE etch rate (µm/s)",
            0.1,
        )

        self.isotropic_rate_var = self._field(
            frame,
            "Isotropic etch rate (µm/s)",
            0.05,
        )

        self.ion_flux_var = self._field(
            frame,
            "SF6/O2 ion flux",
            12.0,
        )

        self.etchant_flux_var = self._field(
            frame,
            "SF6/O2 etchant flux",
            1800.0,
        )

        self.oxygen_flux_var = self._field(
            frame,
            "SF6/O2 oxygen flux",
            100.0,
        )

        self.etch_button = ttk.Button(
            frame,
            text="5. START ETCH — VIENNAPS",
            command=self.run_etch,
        )
        self.etch_button.pack(
            fill="x",
            pady=(12, 3),
        )

        ttk.Label(
            frame,
            text=(
                "The etched surface is generated by "
                "ViennaPS, not by a GUI drawing formula."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=5,
        )

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    def _make_log_panel(
        self,
        parent,
    ):

        frame = ttk.LabelFrame(
            parent,
            text="Process log",
            padding=5,
        )

        frame.pack(
            fill="both",
            expand=True,
        )

        self.log = tk.Text(
            frame,
            width=42,
            height=10,
            state="disabled",
            font=(
                "Consolas",
                9,
            ),
        )

        self.log.pack(
            fill="both",
            expand=True,
        )

    # --------------------------------------------------------
    # FIELD
    # --------------------------------------------------------

    def _field(
        self,
        parent,
        label,
        value,
    ):

        ttk.Label(
            parent,
            text=label,
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

        variable = tk.StringVar(
            value=str(value)
        )

        ttk.Entry(
            parent,
            textvariable=variable,
        ).pack(
            fill="x"
        )

        return variable

    # --------------------------------------------------------
    # LITHOGRAPHY OPERATION
    # --------------------------------------------------------

    def _read_lithography_fields(self):
        try:
            self.wafer.pr_thickness_um = float(self.pr_var.get())
            self.wafer.mask_left_um = float(self.left_var.get())
            self.wafer.mask_right_um = float(self.right_var.get())
            self.wafer.silicon_depth_um = float(self.depth_var.get())
            self.wafer.exposure_dose = float(self.dose_var.get())
            self.wafer.develop_time_s = float(self.develop_var.get())
        except ValueError:
            messagebox.showerror(
                "Lithography",
                "Lithography values must be numeric.",
            )
            return False

        if self.wafer.mask_right_um <= self.wafer.mask_left_um:
            messagebox.showerror(
                "Mask",
                "Opening right edge must be larger than left edge.",
            )
            return False

        if self.wafer.silicon_depth_um <= 0.0:
            messagebox.showerror(
                "Si substrate depth",
                "Si substrate depth must be positive.",
            )
            return False

        return True

    def _update_process_buttons(self):
        """Enable exactly the next physically valid process operation."""
        buttons = {
            "wafer": [self.coat_button],
            "pr_coated": [self.align_button],
            "aligned": [self.expose_button],
            "exposed": [self.develop_button],
            "developed": [self.etch_button],
            "etched": [self.strip_button],
            "stripped": [],
        }

        all_buttons = [
            self.coat_button,
            self.align_button,
            self.expose_button,
            self.develop_button,
            self.etch_button,
            self.strip_button,
        ]

        for button in all_buttons:
            button.configure(state="disabled")

        for button in buttons.get(self.process_stage, []):
            button.configure(state="normal")

    def process_pr_coat(self):
        if self.process_stage != "wafer":
            return
        if not self._read_lithography_fields():
            return

        self.process_stage = "pr_coated"
        self.history.append("PR coat")
        self._activate_stages(0, 1, 2)
        self._log(
            "\nSTEP: PR COAT\n"
            f"PR thickness = {self.wafer.pr_thickness_um} um"
        )
        self._update_process_buttons()
        self.redraw()

    def process_mask_alignment(self):
        if self.process_stage != "pr_coated":
            return
        if not self._read_lithography_fields():
            return

        self.process_stage = "aligned"
        self.history.append("Mask alignment")
        self._activate_stages(0, 1, 2, 3)
        self._log(
            "\nSTEP: MASK ALIGNMENT\n"
            f"Opening = "
            f"{self.wafer.mask_right_um - self.wafer.mask_left_um} um"
        )
        self._update_process_buttons()
        self.redraw()

    def process_exposure(self):
        if self.process_stage != "aligned":
            return
        if not self._read_lithography_fields():
            return

        self.process_stage = "exposed"
        self.history.append("Exposure")
        self._activate_stages(0, 1, 2, 3, 4)
        self._log(
            "\nSTEP: EXPOSURE\n"
            f"Dose = {self.wafer.exposure_dose}"
        )
        self._update_process_buttons()
        self.redraw()

    def process_develop(self):
        if self.process_stage != "exposed":
            return

        self.wafer.developed = True
        self.process_stage = "developed"
        self.history.append("Develop")
        self._activate_stages(0, 1, 2, 3, 4, 5)
        self._log(
            "\nSTEP: DEVELOP\n"
            f"Develop time = {self.wafer.develop_time_s} s\n"
            "Developed PR opening is now the etch mask."
        )
        self._update_process_buttons()
        self.redraw()

    def process_pr_strip(self):
        if self.process_stage != "etched":
            return

        self.wafer.stripped = True
        self.process_stage = "stripped"
        self.history.append("PR strip")
        self._activate_stages(0, 1, 2, 3, 4, 5, 6, 7)
        self._log(
            "\nSTEP: PR STRIP\n"
            "Photoresist removed after etch."
        )
        self._update_process_buttons()
        self.redraw()

    # --------------------------------------------------------
    # ETCH OPERATION
    # --------------------------------------------------------

    def run_etch(self):

        if not self.wafer.developed:

            messagebox.showwarning(
                "Process order",
                "Run lithography and develop first.",
            )

            return

        etch_model_keys = {
            "Bosch DRIE": "bosch_drie",
            "Directional RIE": "directional",
            "Isotropic etch": "isotropic",
            "SF6/O2": "sf6o2",
        }
        model_key = etch_model_keys.get(self.etch_model.get())

        if model_key is None:

            messagebox.showinfo(
                "Backend status",
                "Unknown etch model selected.",
            )

            return

        if not viennaps_session.is_available():

            messagebox.showerror(
                "ViennaPS",
                "ViennaPS is not installed.\n\n"
                "Run:\n"
                "python -m pip install ViennaPS",
            )

            return

        try:

            recipe = {
                "_etch_model_key": model_key,

                "mask_left_um":
                    self.wafer.mask_left_um,

                "mask_right_um":
                    self.wafer.mask_right_um,

                "pr_thickness_um":
                    self.wafer.pr_thickness_um,

                "silicon_depth_um":
                    self.wafer.silicon_depth_um,

                "grid_delta_um":
                    float(
                        self.grid_var.get()
                    ),

                "x_extent_um":
                    self.wafer.width_um,

                "y_extent_um":
                    8.0,

                "etch_time_s":
                    float(
                        self.etch_time_var.get()
                    ),
            }

            if model_key == "bosch_drie":

                recipe.update({
                    "cycles":
                        int(float(
                            self.cycles_var.get()
                        )),

                    "polymer_rate":
                        float(
                            self.poly_var.get()
                        ),

                    "polymer_sticking":
                        float(
                            self.poly_stick_var.get()
                        ),

                    "ion_source_exponent":
                        float(
                            self.ion_exp_var.get()
                        ),

                    "ion_rate":
                        float(
                            self.ion_rate_var.get()
                        ),

                    "neutral_rate":
                        float(
                            self.neutral_rate_var.get()
                        ),

                    "neutral_sticking":
                        float(
                            self.neutral_stick_var.get()
                        ),
                })

            elif model_key == "directional":

                recipe.update({
                    "direction": [0.0, -1.0, 0.0],
                    "directional_velocity":
                        -abs(float(
                            self.directional_rate_var.get()
                        )),
                    "mask_material": "Mask",
                })

            elif model_key == "isotropic":

                recipe.update({
                    "rate":
                        -abs(float(
                            self.isotropic_rate_var.get()
                        )),
                    "mask_material": "Mask",
                })

            elif model_key == "sf6o2":

                recipe.update({
                    "ion_flux": float(self.ion_flux_var.get()),
                    "etchant_flux": float(self.etchant_flux_var.get()),
                    "oxygen_flux": float(self.oxygen_flux_var.get()),
                })

        except ValueError:

            messagebox.showerror(
                "Etch recipe",
                "All recipe values must be numeric.",
            )

            return

        output_dir = tempfile.mkdtemp(
            prefix="tcad2d_real_v2_"
        )

        recipe["output_dir"] = output_dir

        config_file = Path(
            output_dir
        ) / "recipe.json"

        result_file = Path(
            output_dir
        ) / "result.json"

        config_file.write_text(
            json.dumps(
                recipe,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if model_key == "bosch_drie":
            start_msg = (
                "1. MakeTrench\n"
                "2. Initial Si etch\n"
                "3. Polymer passivation\n"
                "4. Bottom breakthrough\n"
                "5. Si etch\n"
                f"6. Repeat x {recipe['cycles']}\n"
            )
        else:
            start_msg = (
                f"1. MakeTrench\n"
                f"2. {self.etch_model.get()} etch ({recipe['etch_time_s']}s)\n"
            )

        self._log(
            f"\n================================\n"
            f"REAL VIENNAPS {self.etch_model.get().upper()} START\n"
            f"================================\n"
            f"{start_msg}"
        )

        self.update_idletasks()

        try:

            completed = subprocess.run(
                [
                    sys.executable,
                    str(
                        Path(__file__).resolve()
                    ),
                    "--worker",
                    str(config_file),
                    str(result_file),
                ],
                capture_output=True,
                text=True,
                timeout=900,
            )

        except Exception as exc:

            messagebox.showerror(
                "ViennaPS",
                str(exc),
            )

            return

        if not result_file.exists():

            messagebox.showerror(
                "ViennaPS",
                "Worker did not produce a result file.\n\n"
                + completed.stderr[-4000:],
            )

            return

        result = json.loads(
            result_file.read_text(
                encoding="utf-8"
            )
        )

        if not result.get("success"):

            messagebox.showerror(
                "ViennaPS",
                result.get(
                    "error",
                    "Unknown ViennaPS error.",
                ),
            )

            self._log(
                "\nVIENNAPS FAILED\n"
            )

            return

        self.wafer.etched = True
        self.process_stage = "etched"
        self.last_final_mesh = result.get("final_mesh")

        self._activate_stages(
            0,
            1,
            2,
            3,
            4,
            5,
            6,
        )

        cycles_note = f" x {result['cycles']}" if "cycles" in result else ""
        self.history.append(
            f"ViennaPS {self.etch_model.get()}{cycles_note}"
        )

        cycles_line = f"Cycles: {result['cycles']}\n" if "cycles" in result else ""
        self._log(
            f"\n================================\n"
            f"REAL VIENNAPS {self.etch_model.get().upper()} COMPLETE\n"
            f"================================\n"
            f"{cycles_line}"
            f"Surface files: "
            f"{len(result['snapshots'])}\n"
            f"Final mesh:\n"
            f"{result['final_mesh']}\n"
        )

        self.redraw()

        messagebox.showinfo(
            "ViennaPS",
            f"ViennaPS {self.etch_model.get()} simulation complete.\n\n"
            f"Final mesh:\n{result['final_mesh']}",
        )

    # --------------------------------------------------------
    # DRAW
    # --------------------------------------------------------

    def _draw_real_mesh_result(self, canvas, x0, x1, surface_y, bottom_y):
        """Draw the actual ViennaPS final_mesh (self.last_final_mesh, a
        .vtu volume mesh) as filled triangles, instead of the placeholder
        rectangle below. Returns True on success; False if the mesh
        can't be read (meshio/ViennaPS unavailable, file missing, no
        triangle cells, degenerate bounds, etc.), so the caller falls
        back to the placeholder in that case -- this must never raise.

        Reuses the exact meshio cell/cell_data access pattern already
        established in tcad/mesh/viennaps_adapter.py's build_process_result
        (triangle block lookup, "Material" cell_data, vps.Material(tag)
        name lookup), rather than inventing a new one.
        """
        if not self.last_final_mesh or not Path(self.last_final_mesh).exists():
            return False

        try:
            import meshio

            if not viennaps_session.is_available():
                return False
            module = viennaps_session.require_viennaps()

            mesh = meshio.read(self.last_final_mesh)
            triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
            if triangle_block is None or "Material" not in mesh.cell_data:
                return False
            block_index = mesh.cells.index(triangle_block)
            tags = mesh.cell_data["Material"][block_index]

            points = mesh.points
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            if (x_max - x_min) < 1e-9 or (x1 - x0) <= 0:
                return False

            # Mesh y=0 is the original wafer surface (ViennaPS convention
            # confirmed throughout this project's own investigation --
            # see CLAUDE.md), lined up here with surface_y so it matches
            # the lithography drawing above. x is fit to the full canvas
            # width; y uses the same scale, clamped so deep/tall meshes
            # stay inside the canvas instead of overflowing it.
            x_scale = (x1 - x0) / (x_max - x_min)
            depth_below = max(0.0, -y_min)
            depth_above = max(0.0, y_max)
            available_below = max(1.0, bottom_y - surface_y - 10)
            available_above = max(1.0, surface_y - 40)
            y_scale = x_scale
            if depth_below > 1e-9:
                y_scale = min(y_scale, available_below / depth_below)
            if depth_above > 1e-9:
                y_scale = min(y_scale, available_above / depth_above)

            material_colors = {
                "Si": "#c9c9c9",
                "Mask": "#202020",
                "SiO2": "#8fb8e8",
                "Polymer": "#f2c14e",
            }
            material_names = {}

            # redraw() runs on every window resize (<Configure>, see
            # __init__), and each run rebuilds the whole canvas from
            # scratch -- a fine grid_delta_um combined with the default
            # ~5um floor_depth_um can produce 10000+ triangles, which
            # would make resizing visibly stutter. Decimate to a fixed
            # cap rather than skip a spatial region, so this is a
            # performance safety valve, not a judgment about which part
            # of the geometry matters more.
            #
            # Found (not assumed) to be a REAL bug in the original
            # positional-stride version (`triangle_data[::step]`): the
            # exported mesh's triangle ORDER is not spatially uniform --
            # a material's own triangles are not spread evenly across
            # its true area in the file (confirmed by inspection: after
            # a plain stride, the surviving Si triangles clustered
            # almost entirely in one thin band near the floor boundary,
            # rendering as a small stray triangle instead of the whole
            # Si cross-section). A fixed positional stride reproduces
            # whatever bias is already in the file's ordering. Fixed by
            # decimating PER MATERIAL, with a random (not positional)
            # sample within each material, seeded so repeated redraws of
            # the same mesh (e.g. window resizes) are stable rather than
            # flickering between different random subsets. This also
            # guarantees every material present keeps a share of the
            # render cap proportional to its own triangle count, rather
            # than one material's triangles (e.g. a small Mask) being
            # crowded out entirely by another's (e.g. a much larger Si)
            # in a combined positional stride.
            triangle_data = triangle_block.data
            if len(triangle_data) > _MAX_RENDERED_TRIANGLES:
                by_material = {}
                for idx, tag in enumerate(tags):
                    by_material.setdefault(int(tag), []).append(idx)

                total = len(triangle_data)
                rng = random.Random(0)
                kept_indices = []
                for tag, indices in by_material.items():
                    share = max(1, round(_MAX_RENDERED_TRIANGLES * len(indices) / total))
                    if len(indices) > share:
                        kept_indices.extend(rng.sample(indices, share))
                    else:
                        kept_indices.extend(indices)
                kept_indices.sort()

                triangle_data = [triangle_data[i] for i in kept_indices]
                tags = [tags[i] for i in kept_indices]

            for tri, tag in zip(triangle_data, tags):
                tag = int(tag)
                name = material_names.get(tag)
                if name is None:
                    name = str(module.Material(tag)).split("'")[1]
                    material_names[tag] = name
                color = material_colors.get(name, "#b0b0b0")

                coords = []
                for node_idx in tri:
                    px, py = points[node_idx][0], points[node_idx][1]
                    coords.append(x0 + (px - x_min) * x_scale)
                    coords.append(surface_y - py * y_scale)

                # Skip sub-pixel triangles (invisible anyway) -- fine
                # grid_delta / deep floor_depth_um combinations can
                # produce thousands of them; this keeps the canvas
                # responsive without changing what's actually visible.
                tri_xs = coords[0::2]
                tri_ys = coords[1::2]
                if max(tri_xs) - min(tri_xs) < 1.0 and max(tri_ys) - min(tri_ys) < 1.0:
                    continue

                canvas.create_polygon(coords, fill=color, outline=color)

            canvas.create_text(
                x0 + 5, surface_y + 12,
                text="REAL VIENNAPS MESH",
                anchor="w", fill="#333",
                font=("Segoe UI", 8, "italic"),
            )
            return True
        except Exception:
            return False

    def redraw(self):

        canvas = self.canvas

        canvas.delete(
            "all"
        )

        width = max(
            canvas.winfo_width(),
            700,
        )

        height = max(
            canvas.winfo_height(),
            500,
        )

        x0 = 70
        x1 = width - 70

        surface_y = height * 0.48
        bottom_y = height - 60

        canvas.create_text(
            x0,
            25,
            text=(
                "2D CROSS SECTION / "
                "PROCESS STATE"
            ),
            anchor="w",
            font=(
                "Segoe UI",
                13,
                "bold",
            ),
        )

        # Silicon
        canvas.create_rectangle(
            x0,
            surface_y,
            x1,
            bottom_y,
            fill="#bdbdbd",
            outline="#555",
        )

        canvas.create_text(
            x0 + 10,
            bottom_y - 20,
            text="Si substrate",
            anchor="w",
        )

        # GUI-only stage visualization. Previously only `developed`
        # drew anything, so PR COAT / MASK ALIGNMENT / EXPOSURE showed
        # no visible change. These flags drive the drawing below; none
        # of them alter process state or the ViennaPS recipe.
        stage = self.process_stage
        pr_present = stage in (
            "pr_coated", "aligned", "exposed", "developed", "etched",
        )
        mask_present = stage in ("aligned", "exposed")
        exposed_now = stage == "exposed"
        opening_open = self.wafer.developed

        pr_height = max(
            25,
            min(
                110,
                self.wafer.pr_thickness_um
                * 55,
            ),
        )

        scale = (
            x1 - x0
        ) / self.wafer.width_um

        opening_x0 = (
            x0
            + self.wafer.mask_left_um
            * scale
        )

        opening_x1 = (
            x0
            + self.wafer.mask_right_um
            * scale
        )

        mask_y0 = (
            surface_y
            - pr_height
            - 45
        )

        if pr_present and not opening_open:

            # Uniform PR film: coated, and still uniform through
            # alignment and exposure (exposure changes chemistry, not
            # geometry -- shown by shading the exposed region instead).
            canvas.create_rectangle(
                x0,
                surface_y - pr_height,
                x1,
                surface_y,
                fill="#e8a0bd",
                outline="#803252",
            )

            canvas.create_text(
                x0 + 10,
                surface_y - pr_height / 2,
                text="PR",
                anchor="w",
            )

            if exposed_now:
                # Exposed (soluble) PR under the mask opening.
                canvas.create_rectangle(
                    opening_x0,
                    surface_y - pr_height,
                    opening_x1,
                    surface_y,
                    fill="#f6dce7",
                    outline="#803252",
                    stipple="gray50",
                )
                canvas.create_text(
                    (opening_x0 + opening_x1) / 2,
                    surface_y - pr_height / 2,
                    text="EXPOSED PR",
                    fill="#803252",
                )

        if mask_present:

            # Photomask held above the wafer during alignment/exposure.
            canvas.create_rectangle(
                x0,
                mask_y0,
                opening_x0,
                surface_y - pr_height,
                fill="#202020",
                outline="#111",
            )

            canvas.create_rectangle(
                opening_x1,
                mask_y0,
                x1,
                surface_y - pr_height,
                fill="#202020",
                outline="#111",
            )

            canvas.create_text(
                (opening_x0 + opening_x1) / 2,
                mask_y0 - 12,
                text="MASK OPENING",
                fill="#155ea8",
            )

            if exposed_now:
                # UV illumination through the mask opening.
                for offset in range(5):
                    ray_x = (
                        opening_x0
                        + (offset + 0.5)
                        * (opening_x1 - opening_x0)
                        / 5
                    )
                    canvas.create_line(
                        ray_x,
                        mask_y0 - 30,
                        ray_x,
                        surface_y - pr_height,
                        fill="#2e86de",
                        arrow="last",
                    )
                canvas.create_text(
                    (opening_x0 + opening_x1) / 2,
                    mask_y0 - 40,
                    text="UV EXPOSURE",
                    fill="#2e86de",
                )

        if opening_open:

            # After develop the exposed PR is removed, leaving a real
            # opening in the resist (this is the state the ViennaPS
            # etch consumes).
            canvas.create_rectangle(
                x0,
                surface_y - pr_height,
                opening_x0,
                surface_y,
                fill="#e8a0bd",
                outline="#803252",
            )

            canvas.create_rectangle(
                opening_x1,
                surface_y - pr_height,
                x1,
                surface_y,
                fill="#e8a0bd",
                outline="#803252",
            )

            canvas.create_text(
                x0 + 10,
                surface_y - pr_height / 2,
                text="PR",
                anchor="w",
            )

            canvas.create_text(
                (opening_x0 + opening_x1) / 2,
                surface_y - pr_height - 12,
                text="PR OPENING",
                fill="#155ea8",
            )

        # Prefer drawing the actual ViennaPS mesh (real geometry, e.g.
        # isotropic undercut) when one is available from the last
        # successful run_etch(). Falls back to the placeholder rectangle
        # below only if that fails (older project state, meshio missing,
        # etc.) -- the placeholder never pretended to be the numerical
        # ViennaPS surface, so this is a strict improvement, not a
        # behavior change for the case it can't apply to.
        if self.wafer.etched and self._draw_real_mesh_result(canvas, x0, x1, surface_y, bottom_y):
            pass

        elif self.wafer.etched:

            scale = (
                x1 - x0
            ) / self.wafer.width_um

            opening_x0 = (
                x0
                + self.wafer.mask_left_um
                * scale
            )

            opening_x1 = (
                x0
                + self.wafer.mask_right_um
                * scale
            )

            try:
                cycles = int(
                    float(
                        self.cycles_var.get()
                    )
                )
            except Exception:
                cycles = 1

            visual_depth = min(
                bottom_y - surface_y - 10,
                80 + cycles * 10,
            )

            canvas.create_rectangle(
                opening_x0,
                surface_y,
                opening_x1,
                surface_y + visual_depth,
                fill="white",
                outline="#444",
            )

            canvas.create_text(
                (opening_x0 + opening_x1) / 2,
                surface_y + visual_depth / 2,
                text=(
                    "VIENNAPS\n"
                    "RESULT"
                ),
                justify="center",
            )

    # --------------------------------------------------------
    # STAGES
    # --------------------------------------------------------

    def _activate_stages(
        self,
        *active,
    ):

        active = set(
            active
        )

        for index, label in enumerate(
            self.stage_labels
        ):

            current = label.cget(
                "text"
            )

            name = current[2:]

            label.configure(
                text=(
                    "● "
                    if index in active
                    else "○ "
                ) + name
            )

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    def _log(
        self,
        text,
    ):

        self.log.configure(
            state="normal"
        )

        self.log.insert(
            "end",
            text + "\n"
        )

        self.log.see(
            "end"
        )

        self.log.configure(
            state="disabled"
        )

    # --------------------------------------------------------
    # RESET
    # --------------------------------------------------------

    def reset(self):

        self.wafer = Wafer()
        self.recipe = BoschRecipe()
        self.history = []
        self.process_stage = "wafer"

        self._activate_stages()

        self._log(
            "\nNEW WAFER\n"
        )

        self._update_process_buttons()
        self.redraw()

    # --------------------------------------------------------
    # PROJECT SAVE
    # --------------------------------------------------------

    def save_project(self):

        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[
                (
                    "TCAD project",
                    "*.json",
                )
            ],
        )

        if not filename:
            return

        data = {
            "version":
                "TCAD_2D_REAL_REWRITE_V2",

            "wafer":
                asdict(self.wafer),

            "recipe":
                asdict(self.recipe),

            "history":
                self.history,
        }

        Path(filename).write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._log(
            f"PROJECT SAVED: {filename}"
        )

    # --------------------------------------------------------
    # PROJECT LOAD
    # --------------------------------------------------------

    def load_project(self):

        filename = filedialog.askopenfilename(
            filetypes=[
                (
                    "TCAD project",
                    "*.json",
                )
            ],
        )

        if not filename:
            return

        try:

            data = json.loads(
                Path(filename).read_text(
                    encoding="utf-8"
                )
            )

            self.wafer = Wafer(
                **data["wafer"]
            )

            self.recipe = BoschRecipe(
                **data["recipe"]
            )

            self.history = data.get(
                "history",
                [],
            )

            self._log(
                f"PROJECT LOADED: {filename}"
            )

            self.redraw()

        except Exception as exc:

            messagebox.showerror(
                "Load project",
                str(exc),
            )


# ============================================================
# ENTRY POINT
# ============================================================

def main():

    if (
        len(sys.argv) >= 2
        and sys.argv[1] == "--worker"
    ):

        if len(sys.argv) != 4:

            raise SystemExit(
                "Usage:\n"
                "tcad_2d_v2_REAL.py "
                "--worker CONFIG RESULT"
            )

        worker_main(
            sys.argv[2],
            sys.argv[3],
        )

        return

    application = TCADApplication()

    application.mainloop()


if __name__ == "__main__":
    main()
