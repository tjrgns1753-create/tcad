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
import tcad.process.geometry  # noqa: F401 -- import side effect: registers gate_stack
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.doping import (
    apply_uniform_doping,
    apply_step_junction_doping,
    apply_gaussian_implant_doping,
    apply_implant_windows_doping,
)

# ============================================================
# VIENNAPS ETCH ENGINE
# ============================================================
#
# worker_main() dispatches through process_registry.get(category, model)
# for whichever category/model the GUI picks (etching or oxidation so
# far), not just Bosch. Bosch's own algorithm (MakeTrench, passivation,
# breakthrough, silicon etch, cycle loop, snapshotting) is unchanged
# since Phase 1.

# Canvas polygon cap for _draw_real_mesh_result -- see its use for why.
_MAX_RENDERED_TRIANGLES = 2000


def _material_boundary_loops(triangles):
    """Trace the true outer boundary of a set of same-material
    triangles (already filtered to one material) into one or more
    closed vertex-index loops.

    An edge touched by exactly one triangle in `triangles` is a
    boundary edge -- the standard definition of a triangulated
    region's silhouette. If every boundary vertex touches exactly 2
    boundary edges, the boundary edges form a disjoint union of
    simple cycles (one per connected region of this material), each
    traceable by walking the adjacency. Returns [] if that isn't the
    case (a non-manifold mesh, or a fully enclosed hole with no
    opening to this material's own outer boundary -- a topology no
    etch/deposition model this project ships today produces), so the
    caller can fall back to per-triangle rendering instead of drawing
    something wrong.
    """
    edge_count = {}
    for tri in triangles:
        idxs = [int(i) for i in tri]
        for i in range(3):
            a, b = idxs[i], idxs[(i + 1) % 3]
            key = (a, b) if a < b else (b, a)
            edge_count[key] = edge_count.get(key, 0) + 1

    boundary_edges = [e for e, c in edge_count.items() if c == 1]
    if not boundary_edges:
        return []

    adjacency = {}
    for a, b in boundary_edges:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)

    if any(len(v) != 2 for v in adjacency.values()):
        return []

    unvisited = set(boundary_edges)
    loops = []
    while unvisited:
        start_a, start_b = next(iter(unvisited))
        unvisited.discard((start_a, start_b))
        loop = [start_a, start_b]
        prev, current = start_a, start_b
        while current != start_a:
            n0, n1 = adjacency[current]
            nxt = n1 if n0 == prev else n0
            key = (current, nxt) if current < nxt else (nxt, current)
            if key not in unvisited:
                return []  # malformed / already-closed -- bail to fallback
            unvisited.discard(key)
            loop.append(nxt)
            prev, current = current, nxt
        loops.append(loop[:-1])

    return loops

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

        if config.get("_flow_steps"):
            # A user-composed process FLOW: several steps, in whatever
            # order the user queued them, each continuing from the
            # previous step's real geometry via
            # ProcessStep(inherited_domain=...). run_flow is the Phase
            # 13/14 machinery this project already verified; the GUI
            # simply had no way in until now.
            from tcad.process.flow import FlowStep, run_flow

            results = run_flow(
                [
                    FlowStep(
                        category=step["_process_category"],
                        name=step["_process_model_key"],
                        recipe=step,
                    )
                    for step in config["_flow_steps"]
                ],
                config["output_dir"],
            )
            # The LAST step's mesh is the finished device -- that is what
            # doping and device measurement consume.
            payload = {
                "success": True,
                "final_mesh": results[-1].volume_mesh_path,
                "step_count": len(results),
            }
        else:
            # Any registered category/model works here (Bosch included):
            # the GUI sets "_process_category"/"_process_model_key" to
            # pick which one -- this worker is not etch-specific.
            step_cls = process_registry.get(
                config["_process_category"], config["_process_model_key"]
            )
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

        # The ProcessResult (with DopingProfile attached) from the last
        # successful run_doping(), consumed by run_measurement() -- see
        # _make_measurement_panel()'s own docstring. None until doping
        # succeeds.
        self.last_doped_result = None

        # Each category panel's LabelFrame, registered as it is built,
        # so the category selector can show exactly one at a time (see
        # _show_panel_category).
        self._panel_frames = {}

        # The user-composed process flow: a list of fully-built recipes,
        # run in the given order by tcad.process.flow.run_flow so each
        # step continues from the previous one's real geometry. This is
        # what makes the ORDER the user's choice instead of a fixed
        # sequence -- a real device (a PN-junction diode, say) needs
        # oxidation -> lithography -> doping -> metallization, which the
        # old one-shot "etch OR oxidation OR deposition, then strip"
        # state machine could not express at all.
        self.flow_steps = []

        # Every real ViennaPS step already run this session (etch,
        # oxidation, deposition — NOT gate_stack, which is terminal and
        # cannot chain), in order. A standalone "RUN X" click (not
        # ADD TO FLOW) re-executes self.completed_steps + [this recipe]
        # as ONE flow via run_flow, so it continues from the real
        # current geometry instead of silently rebuilding a fresh wafer
        # -- see _chained_flow_config(). RUN PROCESS FLOW folds its own
        # queued self.flow_steps into this list the same way.
        self.completed_steps = []

        # Set only while an "ADD TO FLOW" button is being handled, so
        # the existing run_* recipe builders can be reused verbatim to
        # QUEUE a step instead of running it (see the hook they share).
        self._pending_flow_add = False

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

        self._mask_drag_start_um = None
        self._mask_drag_rect_id = None

        self.canvas.bind("<ButtonPress-1>", self._on_mask_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_mask_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_mask_drag_end)

    # --------------------------------------------------------
    # CONTROL PANEL
    # --------------------------------------------------------

    #: Category selector contents. Keys match self._panel_frames, set
    #: by each _make_*_panel as it builds its own LabelFrame.
    _PANEL_ORDER = (
        "litho",
        "etch",
        "oxidation",
        "deposition",
        "gate_stack",
        "doping",
        "measurement",
    )
    _PANEL_LABELS = {
        "litho": "Lithography / mask",
        "etch": "Etching",
        "oxidation": "Oxidation",
        "deposition": "Deposition",
        "gate_stack": "Geometry (MOSFET gate stack)",
        "doping": "Doping",
        "measurement": "Device measurement",
    }

    # --------------------------------------------------------
    # PROCESS FLOW (user-ordered, any sequence)
    # --------------------------------------------------------

    def _make_flow_panel(self, parent):
        """The user-composed process flow.

        A real device is not one process step. A PN-junction diode, as
        every textbook builds it, is oxidation -> lithography -> doping
        -> metallization -> lithography; a MOS gate is a different order
        again. The old GUI hard-wired ONE sequence (litho -> etch OR
        oxidation OR deposition -> strip) and gated the buttons so
        nothing else was reachable, which is the opposite of what a CAD
        tool should do.

        Steps are queued here in whatever order the user wants and run
        by `tcad.process.flow.run_flow`, which chains them through
        `ProcessStep(inherited_domain=...)` so each one continues from
        the previous step's real ViennaPS geometry rather than
        rebuilding a fresh wafer. That chaining is not new -- it is the
        Phase 13/14 machinery this project already verified -- it simply
        had no way in from the GUI until now.
        """
        frame = ttk.LabelFrame(parent, text="Process flow", padding=10)
        frame.pack(fill="x", pady=(8, 0))

        ttk.Label(
            frame,
            text="Steps run top to bottom; each continues from the previous "
                 "geometry.",
            wraplength=320,
            foreground="#555",
        ).pack(anchor="w", pady=(0, 4))

        self.flow_list = tk.Listbox(frame, height=6, exportselection=False)
        self.flow_list.pack(fill="x")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(3, 0))

        for text, width, command in (
            ("↑", 3, lambda: self._move_flow_step(-1)),
            ("↓", 3, lambda: self._move_flow_step(1)),
            ("Remove", 9, self.remove_flow_step),
            ("Clear", 7, self.clear_flow),
        ):
            ttk.Button(
                buttons, text=text, width=width, command=command
            ).pack(side="left", padx=(0, 3))

        self.run_flow_button = ttk.Button(
            frame,
            text="RUN PROCESS FLOW",
            command=self.run_process_flow,
        )
        self.run_flow_button.pack(fill="x", pady=(6, 0))

        self._refresh_flow_list()

    def run_process_flow(self):
        """Run every queued step in order, chained through real geometry."""
        if not self.flow_steps:
            messagebox.showinfo(
                "Process flow",
                "No steps queued. Pick a category, set its parameters, and "
                "press ADD TO FLOW.",
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

        # Fold in whatever standalone RUN clicks already built this wafer
        # (self.completed_steps) so RUN PROCESS FLOW continues from the
        # real current geometry too, not just from queued steps -- e.g.
        # RUN ETCH now, then ADD TO FLOW an oxidation and RUN PROCESS
        # FLOW, must oxidize the etched wafer, not a fresh one.
        all_steps = self.completed_steps + self.flow_steps

        output_dir = tempfile.mkdtemp(prefix="tcad2d_flow_")
        config_file = Path(output_dir) / "flow.json"
        result_file = Path(output_dir) / "result.json"

        config_file.write_text(
            json.dumps(
                {"_flow_steps": all_steps, "output_dir": output_dir},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._log(
            "\n================================\n"
            "REAL VIENNAPS PROCESS FLOW START\n"
            "================================\n"
            + "".join(
                f"{i + 1}. {self._flow_step_label(r)}\n"
                for i, r in enumerate(self.flow_steps)
            )
        )
        self.update_idletasks()

        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    str(config_file),
                    str(result_file),
                ],
                capture_output=True,
                text=True,
                timeout=1800,
            )
        except Exception as exc:
            messagebox.showerror("ViennaPS", str(exc))
            return

        if not result_file.exists():
            messagebox.showerror(
                "ViennaPS",
                "Worker did not produce a result file.\n\n"
                + completed.stderr[-4000:],
            )
            return

        result = json.loads(result_file.read_text(encoding="utf-8"))

        if not result.get("success"):
            messagebox.showerror(
                "ViennaPS", result.get("error", "Unknown ViennaPS error.")
            )
            self._log("\nPROCESS FLOW FAILED\n")
            return

        self.last_final_mesh = result.get("final_mesh")
        self.wafer.processed = True
        self.wafer.etched = True
        self.process_stage = "flow_done"

        self._log(
            f"\nPROCESS FLOW COMPLETE ({len(all_steps)} steps)\n"
            f"final mesh: {self.last_final_mesh}\n"
        )

        # The queued steps are now part of the wafer's real history, so
        # a later standalone RUN click (or another RUN PROCESS FLOW)
        # continues from here instead of redoing/discarding them.
        self.completed_steps = all_steps
        self.flow_steps = []
        self._refresh_flow_list()

        self._update_process_buttons()
        self.redraw()

    def _chained_flow_config(self, recipe, output_dir):
        """Wrap a single RUN-click recipe together with every step
        already run this session, so it executes as one run_flow() call
        that continues from the real current geometry via
        ProcessStep(inherited_domain=...) -- the same chaining
        RUN PROCESS FLOW already uses -- instead of silently rebuilding
        a fresh wafer the way a standalone single-step run used to.

        Called AFTER the ADD TO FLOW interception (self._pending_flow_add
        returns before this), so `recipe` here is always something about
        to run now, not merely queued.
        """
        return {
            "_flow_steps": self.completed_steps + [recipe],
            "output_dir": output_dir,
        }

    def _flow_step_label(self, recipe):
        category = recipe.get("_process_category", "?")
        model = recipe.get("_process_model_key", "?")
        detail = ""
        if "etch_time_s" in recipe:
            detail = f"  {recipe['etch_time_s']}s"
        elif "time_hours" in recipe:
            detail = f"  {recipe['time_hours']}hr"
        elif "deposition_time_s" in recipe:
            detail = f"  {recipe['deposition_time_s']}s"
        return f"{category} / {model}{detail}"

    def _append_flow_step(self, recipe):
        """Queue a fully-built recipe (called from the run_* builders'
        shared ADD TO FLOW hook)."""
        self.flow_steps.append(dict(recipe))
        self._refresh_flow_list(select=len(self.flow_steps) - 1)
        self._log(f"Flow step added: {self._flow_step_label(recipe)}\n")

    def _refresh_flow_list(self, select=None):
        if not hasattr(self, "flow_list"):
            return
        self.flow_list.delete(0, tk.END)
        for index, recipe in enumerate(self.flow_steps):
            self.flow_list.insert(
                tk.END, f"{index + 1}.  {self._flow_step_label(recipe)}"
            )
        if self.flow_steps:
            target = select if select is not None else 0
            target = max(0, min(target, len(self.flow_steps) - 1))
            self.flow_list.selection_clear(0, tk.END)
            self.flow_list.selection_set(target)

    def _selected_flow_index(self):
        selection = self.flow_list.curselection()
        return int(selection[0]) if selection else -1

    def _move_flow_step(self, delta):
        index = self._selected_flow_index()
        target = index + delta
        if index < 0 or not (0 <= target < len(self.flow_steps)):
            return
        self.flow_steps[index], self.flow_steps[target] = (
            self.flow_steps[target],
            self.flow_steps[index],
        )
        self._refresh_flow_list(select=target)

    def remove_flow_step(self):
        index = self._selected_flow_index()
        if index < 0:
            return
        removed = self.flow_steps.pop(index)
        self._refresh_flow_list(select=min(index, len(self.flow_steps) - 1))
        self._log(f"Flow step removed: {self._flow_step_label(removed)}\n")

    def clear_flow(self):
        self.flow_steps = []
        self._refresh_flow_list()
        self._log("Process flow cleared\n")

    def add_current_step_to_flow(self):
        """Build the CURRENTLY selected category/model's recipe and queue
        it, reusing that category's own existing recipe builder."""
        builders = {
            "etch": self.run_etch,
            "oxidation": self.run_oxidation,
            "deposition": self.run_deposition,
            "gate_stack": self.run_gate_stack,
        }
        key = next(
            (
                k
                for k in self._PANEL_ORDER
                if self._PANEL_LABELS[k] == self.panel_category.get()
            ),
            None,
        )
        builder = builders.get(key)
        if builder is None:
            messagebox.showinfo(
                "Process flow",
                "Only Etching, Oxidation, Deposition and Geometry are real "
                "ViennaPS process steps that can be queued into a flow.\n\n"
                "Lithography defines the mask every queued step uses; Doping "
                "and Device measurement run after the flow, on its final "
                "mesh.",
            )
            return

        self._pending_flow_add = True
        try:
            builder()
        finally:
            self._pending_flow_add = False

    def _show_panel_category(self):
        """Show only the selected category's panel."""
        selected = self.panel_category.get()
        for key in self._PANEL_ORDER:
            frame = self._panel_frames.get(key)
            if frame is None:
                continue
            if self._PANEL_LABELS[key] == selected:
                frame.pack(fill="x", pady=6)
            else:
                frame.pack_forget()

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

        # Category selector. Every category's panel is built once, into
        # one fixed container, and exactly ONE is shown at a time --
        # stacking all seven made the control panel several screens
        # long, and most of it was irrelevant to whatever the user was
        # actually doing. Each panel already picks its own MODEL and
        # shows only that model's parameters (see e.g.
        # _update_etch_field_visibility), so this adds the missing outer
        # level: category -> model -> that model's parameters.
        ttk.Label(
            panel,
            text="Process category",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(8, 2))

        self.panel_category = tk.StringVar(value=self._PANEL_LABELS["litho"])

        ttk.Combobox(
            panel,
            textvariable=self.panel_category,
            state="readonly",
            values=[self._PANEL_LABELS[key] for key in self._PANEL_ORDER],
        ).pack(fill="x")

        self.panel_category.trace_add(
            "write", lambda *_a: self._show_panel_category()
        )

        ttk.Button(
            panel,
            text="ADD TO FLOW  ▼",
            command=self.add_current_step_to_flow,
        ).pack(fill="x", pady=(4, 0))

        panel_container = ttk.Frame(panel)
        panel_container.pack(fill="x")

        self._make_lithography_panel(
            panel_container
        )

        self._make_etch_panel(
            panel_container
        )

        self._make_oxidation_panel(
            panel_container
        )

        self._make_deposition_panel(
            panel_container
        )

        self._make_geometry_panel(
            panel_container
        )

        self._make_doping_panel(
            panel_container
        )

        self._make_measurement_panel(
            panel_container
        )

        self._show_panel_category()

        self._make_flow_panel(
            panel
        )

        # etch_button/oxidation_button/deposition_button (created above)
        # are required by _update_process_buttons(); call it only after
        # all panels exist so widget creation order / visual layout is
        # unchanged, only the timing of this refresh call moves.
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

        self._panel_frames["litho"] = frame

        frame.pack(
            fill="x"
        )

        self.pr_var = self._field(
            frame,
            "PR thickness (µm)",
            self.wafer.pr_thickness_um,
        )

        # Mask openings. A real mask patterns several windows at once,
        # so this is a LIST, not one left/right pair. left_var/right_var
        # stay as the SELECTED opening's two fields (every existing
        # reader of them, including the canvas drag handler and
        # _read_lithography_fields, keeps working unchanged); the
        # listbox below is what makes the other openings reachable.
        ttk.Label(
            frame,
            text="Mask openings (µm)",
        ).pack(anchor="w", pady=(6, 0))

        self.openings_list = tk.Listbox(
            frame,
            height=4,
            exportselection=False,
        )
        self.openings_list.pack(fill="x")
        self.openings_list.bind(
            "<<ListboxSelect>>",
            lambda _e: self._on_opening_selected(),
        )

        opening_buttons = ttk.Frame(frame)
        opening_buttons.pack(fill="x", pady=(2, 0))

        ttk.Button(
            opening_buttons,
            text="+ Add",
            width=8,
            command=self.add_mask_opening,
        ).pack(side="left")

        ttk.Button(
            opening_buttons,
            text="- Remove",
            width=10,
            command=self.remove_mask_opening,
        ).pack(side="left", padx=(4, 0))

        ttk.Button(
            opening_buttons,
            text="Update",
            width=9,
            command=self.update_mask_opening,
        ).pack(side="left", padx=(4, 0))

        self.left_var = self._field(
            frame,
            "  selected opening: left (µm)",
            self.wafer.mask_left_um,
        )

        self.right_var = self._field(
            frame,
            "  selected opening: right (µm)",
            self.wafer.mask_right_um,
        )

        self._refresh_openings_list()

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

        self._panel_frames["etch"] = frame

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

        # Fields below are used by every etch model.
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

        # Only one of the four groups below is ever shown at a time,
        # matching the "Etch process" combobox above -- each model has
        # its own set of parameters, and showing all 12 at once
        # regardless of selection was confusing (e.g. Bosch's polymer/
        # ion fields stayed visible while Isotropic etch was selected,
        # even though run_etch() never reads them for that model).
        # See _update_etch_field_visibility(). All four group frames
        # live inside one fixed container (etch_params_container),
        # packed once, so switching the selected group never disturbs
        # the etch_button/log panel below it -- packing/unpacking a
        # frame directly into `frame` here would instead move it to
        # the end of the pack order each time, landing below the
        # button on every switch.
        etch_params_container = ttk.Frame(frame)
        etch_params_container.pack(
            fill="x"
        )

        bosch_frame = ttk.Frame(etch_params_container)

        self.cycles_var = self._field(
            bosch_frame,
            "Bosch cycles",
            self.recipe.cycles,
        )

        self.poly_var = self._field(
            bosch_frame,
            "Polymer deposition rate",
            self.recipe.polymer_rate,
        )

        self.poly_stick_var = self._field(
            bosch_frame,
            "Polymer sticking",
            self.recipe.polymer_sticking,
        )

        self.ion_exp_var = self._field(
            bosch_frame,
            "Ion source exponent",
            self.recipe.ion_source_exponent,
        )

        self.ion_rate_var = self._field(
            bosch_frame,
            "Ion Si contribution",
            self.recipe.ion_rate,
        )

        self.neutral_rate_var = self._field(
            bosch_frame,
            "Neutral Si contribution",
            self.recipe.neutral_rate,
        )

        self.neutral_stick_var = self._field(
            bosch_frame,
            "Neutral sticking",
            self.recipe.neutral_sticking,
        )

        directional_frame = ttk.Frame(etch_params_container)

        self.directional_rate_var = self._field(
            directional_frame,
            "Directional RIE etch rate (µm/s)",
            0.1,
        )

        isotropic_frame = ttk.Frame(etch_params_container)

        self.isotropic_rate_var = self._field(
            isotropic_frame,
            "Isotropic etch rate (µm/s)",
            0.05,
        )

        sf6o2_frame = ttk.Frame(etch_params_container)

        self.ion_flux_var = self._field(
            sf6o2_frame,
            "SF6/O2 ion flux",
            12.0,
        )

        self.etchant_flux_var = self._field(
            sf6o2_frame,
            "SF6/O2 etchant flux",
            1800.0,
        )

        self.oxygen_flux_var = self._field(
            sf6o2_frame,
            "SF6/O2 oxygen flux",
            100.0,
        )

        self._etch_model_frames = {
            "Bosch DRIE": bosch_frame,
            "Directional RIE": directional_frame,
            "Isotropic etch": isotropic_frame,
            "SF6/O2": sf6o2_frame,
        }

        self.etch_model.trace_add(
            "write",
            lambda *_args: self._update_etch_field_visibility(),
        )

        # Show only the group matching the combobox's current value
        # (the "Bosch DRIE" default) before the button below is
        # packed, so the visible group lands in the right place.
        self._update_etch_field_visibility()

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
    # OXIDATION
    # --------------------------------------------------------

    def _make_oxidation_panel(
        self,
        parent,
    ):
        """Thermal oxidation (fin or LOCOS) — only one model is
        registered under the "oxidation" category (tcad.process.
        oxidation.thermal), so unlike the etch panel there is no model
        combobox / per-model field-visibility switch here. LOCOS vs
        fin-style is instead the one real recipe switch
        (tcad/process/oxidation/thermal.py's own docstring: presence of
        "mask_material" activates LOCOS physics), exposed here as a
        single checkbox.

        Shares self.grid_var (built in _make_etch_panel, above this
        panel in the layout) rather than adding a second, independently
        -settable grid field: both panels build a fresh domain from the
        same self.wafer geometry, and this GUI runs one process step at
        a time (see run_oxidation), so one shared grid setting avoids
        two fields that would need to be kept in sync by hand.
        """

        frame = ttk.LabelFrame(
            parent,
            text="Oxidation recipe (thermal / LOCOS)",
            padding=10,
        )

        self._panel_frames["oxidation"] = frame

        frame.pack(
            fill="x",
            pady=10,
        )

        ttk.Label(
            frame,
            text="Oxidant",
        ).pack(
            anchor="w"
        )

        self.oxidant_var = tk.StringVar(
            value="Dry"
        )

        ttk.Combobox(
            frame,
            textvariable=self.oxidant_var,
            state="readonly",
            values=[
                "Dry",
                "Wet",
            ],
        ).pack(
            fill="x"
        )

        self.ox_temp_var = self._field(
            frame,
            "Temperature (°C)",
            1000.0,
        )

        self.ox_time_var = self._field(
            frame,
            "Time (hours)",
            0.5,
        )

        self.locos_var = tk.BooleanVar(
            value=False
        )

        ttk.Checkbutton(
            frame,
            text="LOCOS (mask present during oxidation)",
            variable=self.locos_var,
        ).pack(
            anchor="w",
            pady=(6, 0),
        )

        self.oxidation_button = ttk.Button(
            frame,
            text="5b. START OXIDATION — VIENNAPS",
            command=self.run_oxidation,
        )
        self.oxidation_button.pack(
            fill="x",
            pady=(12, 3),
        )

        ttk.Label(
            frame,
            text=(
                "LOCOS grows oxide under a real elastic mask/oxide "
                "contact model; unchecked grows oxide on the exposed "
                "(fin) silicon with no mask physics."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=5,
        )

    def run_oxidation(self):

        # No litho-first gate: oxidation is a valid FIRST step (a real
        # fab textbook PN-junction flow starts oxidation -> lithography
        # -> doping -> metallization, not the reverse). prepare_domain()
        # only ever reads self.wafer's mask/PR-thickness fields, which
        # always carry a value (defaulted or user-set), whether or not
        # develop() was ever clicked -- so this never lacked what it
        # needs, only used to refuse to run anyway.
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
                "_process_category": "oxidation",
                "_process_model_key": "thermal",

                # Every mask opening, not just the first -- see
                # _mask_recipe_keys().
                **self._mask_recipe_keys(),

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

                "oxidant":
                    self.oxidant_var.get(),

                "temperature_c":
                    float(
                        self.ox_temp_var.get()
                    ),

                "time_hours":
                    float(
                        self.ox_time_var.get()
                    ),
            }

            if self.locos_var.get():
                # Presence of this key is the fin (absent) vs LOCOS
                # (present) switch -- see thermal.py's own docstring.
                recipe["mask_material"] = "Mask"

        except ValueError:

            messagebox.showerror(
                "Oxidation recipe",
                "All recipe values must be numeric.",
            )

            return

        # ADD TO FLOW intercepts here: the recipe is fully built but
        # nothing has run yet, so the same recipe-building code serves
        # both "run this one step now" and "queue it into the flow".
        if self._pending_flow_add:
            self._append_flow_step(recipe)
            return

        output_dir = tempfile.mkdtemp(
            prefix="tcad2d_real_v2_"
        )

        config_file = Path(
            output_dir
        ) / "recipe.json"

        result_file = Path(
            output_dir
        ) / "result.json"

        # Chains onto whatever this session already built (see
        # _chained_flow_config()) instead of a fresh wafer.
        config_file.write_text(
            json.dumps(
                self._chained_flow_config(recipe, output_dir),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        model_label = "LOCOS" if self.locos_var.get() else "fin-style thermal oxidation"

        self._log(
            f"\n================================\n"
            f"REAL VIENNAPS {model_label.upper()} START\n"
            f"================================\n"
            f"1. {'Pad oxide + mask (LOCOS)' if self.locos_var.get() else 'MakeTrench'}\n"
            f"2. {recipe['oxidant']} oxidation, "
            f"{recipe['temperature_c']}°C, {recipe['time_hours']}h\n"
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

        self.wafer.processed = True
        self.process_stage = "oxidized"
        self.last_final_mesh = result.get("final_mesh")
        self.completed_steps.append(recipe)

        self._activate_stages(
            0,
            1,
            2,
            3,
            4,
            5,
            6,
        )

        self.history.append(
            f"ViennaPS {model_label}"
        )

        self._log(
            f"\n================================\n"
            f"REAL VIENNAPS {model_label.upper()} COMPLETE\n"
            f"================================\n"
            f"Surface files: "
            f"{len(result.get('snapshots', []))}\n"
            f"Final mesh:\n"
            f"{result['final_mesh']}\n"
        )

        # Fixes a real, previously-latent gap: neither this method nor
        # run_etch() used to call this after a successful run, so the
        # PR-strip button never visibly enabled through the normal UI
        # flow (see docs/investigation_log.md's GUI oxidation-panel
        # section). Same fix applied to run_etch() below.
        self._update_process_buttons()

        self.redraw()

        messagebox.showinfo(
            "ViennaPS",
            f"ViennaPS {model_label} simulation complete.\n\n"
            f"Final mesh:\n{result['final_mesh']}",
        )

    # --------------------------------------------------------
    # DEPOSITION
    # --------------------------------------------------------

    def _make_deposition_panel(
        self,
        parent,
    ):
        """7 registered deposition models, same combobox + per-model
        -frame-visibility pattern as _make_etch_panel. Default values
        for every field are the SAME ones
        tests/integration/test_phase3_deposition_real.py already
        verifies against real ViennaPS 4.6.2 (run every registered
        deposition model), not invented for this panel.

        Unlike etching, "deposition time" is NOT a field every model
        shares: geometric_trench is a one-shot geometric stamp with no
        Process() duration at all (see geometric_trench.py's own module
        docstring) -- so each per-model frame owns its own time field
        instead of one shared field living above the container the way
        grid_delta_um/etch_time_s do in _make_etch_panel.
        """

        frame = ttk.LabelFrame(
            parent,
            text="Deposition recipe",
            padding=10,
        )

        self._panel_frames["deposition"] = frame

        frame.pack(
            fill="x",
            pady=10,
        )

        ttk.Label(
            frame,
            text="Deposition process",
        ).pack(
            anchor="w"
        )

        self.deposition_model = tk.StringVar(
            value="Isotropic Deposition"
        )

        ttk.Combobox(
            frame,
            textvariable=self.deposition_model,
            state="readonly",
            values=[
                "Isotropic Deposition",
                "Directional (PVD/Sputter)",
                "Conformal CVD",
                "TEOS Deposition",
                "TEOS PE-CVD",
                "Selective Epitaxy",
                "Non-Conformal (geometric trench)",
            ],
        ).pack(
            fill="x"
        )

        deposition_params_container = ttk.Frame(frame)
        deposition_params_container.pack(
            fill="x"
        )

        isotropic_frame = ttk.Frame(deposition_params_container)
        self.dep_isotropic_rate_var = self._field(
            isotropic_frame, "Rate (µm/s)", 0.05,
        )
        self.dep_isotropic_time_var = self._field(
            isotropic_frame, "Deposition time (s)", 0.5,
        )
        self.dep_isotropic_material_var = self._material_field(
            isotropic_frame, "Deposited material", "SiO2",
        )

        directional_frame = ttk.Frame(deposition_params_container)
        self.dep_directional_velocity_var = self._field(
            directional_frame, "Directional velocity (µm/s)", 0.1,
        )
        self.dep_directional_time_var = self._field(
            directional_frame, "Deposition time (s)", 0.5,
        )
        self.dep_directional_material_var = self._material_field(
            directional_frame, "Deposited material", "Metal",
        )

        cvd_frame = ttk.Frame(deposition_params_container)
        self.dep_cvd_rate_var = self._field(
            cvd_frame, "Rate (µm/s)", 0.05,
        )
        self.dep_cvd_sticking_var = self._field(
            cvd_frame, "Sticking probability", 1.0,
        )
        self.dep_cvd_time_var = self._field(
            cvd_frame, "Deposition time (s)", 0.5,
        )
        self.dep_cvd_material_var = self._material_field(
            cvd_frame, "Deposited material", "SiO2",
        )

        teos_frame = ttk.Frame(deposition_params_container)
        self.dep_teos_sticking_var = self._field(
            teos_frame, "Sticking probability P1", 0.1,
        )
        self.dep_teos_rate_var = self._field(
            teos_frame, "Rate P1 (µm/s)", 1.0,
        )
        self.dep_teos_order_var = self._field(
            teos_frame, "Order P1", 1.0,
        )
        self.dep_teos_time_var = self._field(
            teos_frame, "Deposition time (s)", 0.5,
        )
        self.dep_teos_material_var = self._material_field(
            teos_frame, "Deposited material", "SiO2",
        )

        teos_pecvd_frame = ttk.Frame(deposition_params_container)
        self.dep_pecvd_sticking_var = self._field(
            teos_pecvd_frame, "Sticking probability (radical)", 0.1,
        )
        self.dep_pecvd_rate_radical_var = self._field(
            teos_pecvd_frame, "Deposition rate, radical (µm/s)", 1.0,
        )
        self.dep_pecvd_rate_ion_var = self._field(
            teos_pecvd_frame, "Deposition rate, ion (µm/s)", 1.0,
        )
        self.dep_pecvd_exponent_ion_var = self._field(
            teos_pecvd_frame, "Exponent (ion)", 100.0,
        )
        self.dep_pecvd_time_var = self._field(
            teos_pecvd_frame, "Deposition time (s)", 0.5,
        )
        self.dep_pecvd_material_var = self._material_field(
            teos_pecvd_frame, "Deposited material", "SiO2",
        )

        epitaxy_frame = ttk.Frame(deposition_params_container)
        self.dep_epitaxy_rate_var = self._field(
            epitaxy_frame, "Si growth rate (µm/s)", 1.0,
        )
        self.dep_epitaxy_time_var = self._field(
            epitaxy_frame, "Deposition time (s)", 0.5,
        )
        ttk.Label(
            epitaxy_frame,
            text=(
                "Crystal-orientation-dependent (rate111/rate100 use "
                "ViennaPS's own defaults, 0.5/1.0)."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

        trench_frame = ttk.Frame(deposition_params_container)
        self.dep_trench_reference_depth_var = self._field(
            trench_frame, "Reference depth (µm)", 1.0,
        )
        self.dep_trench_search_box_var = self._field(
            trench_frame, "Search-box radius (µm)", 1.0,
        )
        self.dep_trench_bottom_med_var = self._field(
            trench_frame, "Bottom (trench floor) thickness (µm)", 0.05,
        )
        self.dep_trench_a_var = self._field(
            trench_frame, "a (peak thickness term, µm)", 0.1,
        )
        self.dep_trench_b_var = self._field(
            trench_frame, "b (offset term, µm)", 0.02,
        )
        self.dep_trench_material_var = self._material_field(
            trench_frame, "Deposited material", "SiO2",
        )
        ttk.Label(
            trench_frame,
            text=(
                "Geometric stamp, not a rate x time simulation -- no "
                "deposition-time field. Thickness = a*(1-|y|/depth)^n+b, "
                "n=1 (ViennaPS default). Search-box radius must exceed "
                "a+b or the result is silently wrong -- see "
                "geometric_trench.py's own module docstring."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

        self._deposition_model_frames = {
            "Isotropic Deposition": isotropic_frame,
            "Directional (PVD/Sputter)": directional_frame,
            "Conformal CVD": cvd_frame,
            "TEOS Deposition": teos_frame,
            "TEOS PE-CVD": teos_pecvd_frame,
            "Selective Epitaxy": epitaxy_frame,
            "Non-Conformal (geometric trench)": trench_frame,
        }

        self.deposition_model.trace_add(
            "write",
            lambda *_args: self._update_deposition_field_visibility(),
        )
        self._update_deposition_field_visibility()

        self.deposition_button = ttk.Button(
            frame,
            text="5c. START DEPOSITION — VIENNAPS",
            command=self.run_deposition,
        )
        self.deposition_button.pack(
            fill="x",
            pady=(12, 3),
        )

        ttk.Label(
            frame,
            text=(
                "The deposited surface is generated by ViennaPS, not "
                "by a GUI drawing formula."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=5,
        )

    def _update_deposition_field_visibility(self):
        """Same mechanism as _update_etch_field_visibility(): show only
        the parameter group for the currently-selected deposition
        model, all packed into one fixed container so switching never
        moves the button/log panel below it."""

        selected = self.deposition_model.get()

        for model_name, group_frame in self._deposition_model_frames.items():
            if model_name == selected:
                group_frame.pack(fill="x")
            else:
                group_frame.pack_forget()

    def run_deposition(self):

        # No litho-first gate -- see run_oxidation()'s matching comment;
        # deposition is equally valid as a first step (blanket film on a
        # bare wafer) and prepare_domain() needs nothing develop() sets.
        deposition_model_keys = {
            "Isotropic Deposition": "isotropic",
            "Directional (PVD/Sputter)": "directional",
            "Conformal CVD": "single_particle_cvd",
            "TEOS Deposition": "teos",
            "TEOS PE-CVD": "teos_pecvd",
            "Selective Epitaxy": "selective_epitaxy",
            "Non-Conformal (geometric trench)": "geometric_trench",
        }
        model_key = deposition_model_keys.get(self.deposition_model.get())

        if model_key is None:

            messagebox.showinfo(
                "Backend status",
                "Unknown deposition model selected.",
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
                "_process_category": "deposition",
                "_process_model_key": model_key,

                # Every mask opening, not just the first -- see
                # _mask_recipe_keys().
                **self._mask_recipe_keys(),

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
            }

            if model_key == "isotropic":

                recipe.update({
                    "rate": float(self.dep_isotropic_rate_var.get()),
                    "deposition_time_s": float(self.dep_isotropic_time_var.get()),
                    "mask_material": "Mask",
                    "material": self.dep_isotropic_material_var.get(),
                })

            elif model_key == "directional":

                recipe.update({
                    "direction": [0.0, 1.0, 0.0],
                    "directional_velocity": float(self.dep_directional_velocity_var.get()),
                    "deposition_time_s": float(self.dep_directional_time_var.get()),
                    "mask_material": "Mask",
                    "material": self.dep_directional_material_var.get(),
                })

            elif model_key == "single_particle_cvd":

                recipe.update({
                    "rate": float(self.dep_cvd_rate_var.get()),
                    "sticking_probability": float(self.dep_cvd_sticking_var.get()),
                    "deposition_time_s": float(self.dep_cvd_time_var.get()),
                    "mask_material": "Mask",
                    "material": self.dep_cvd_material_var.get(),
                })

            elif model_key == "teos":

                recipe.update({
                    "sticking_probability_p1": float(self.dep_teos_sticking_var.get()),
                    "rate_p1": float(self.dep_teos_rate_var.get()),
                    "order_p1": float(self.dep_teos_order_var.get()),
                    "deposition_time_s": float(self.dep_teos_time_var.get()),
                    "material": self.dep_teos_material_var.get(),
                })

            elif model_key == "teos_pecvd":

                recipe.update({
                    "sticking_probability_radical": float(self.dep_pecvd_sticking_var.get()),
                    "deposition_rate_radical": float(self.dep_pecvd_rate_radical_var.get()),
                    "deposition_rate_ion": float(self.dep_pecvd_rate_ion_var.get()),
                    "exponent_ion": float(self.dep_pecvd_exponent_ion_var.get()),
                    "deposition_time_s": float(self.dep_pecvd_time_var.get()),
                    "material": self.dep_pecvd_material_var.get(),
                })

            elif model_key == "selective_epitaxy":

                recipe.update({
                    "material_rates": [
                        {"material": "Si", "rate": float(self.dep_epitaxy_rate_var.get())},
                    ],
                    "deposition_time_s": float(self.dep_epitaxy_time_var.get()),
                })

            elif model_key == "geometric_trench":

                recipe.update({
                    "reference_depth_um": float(self.dep_trench_reference_depth_var.get()),
                    "deposition_rate_um": float(self.dep_trench_search_box_var.get()),
                    "bottom_med_um": float(self.dep_trench_bottom_med_var.get()),
                    "a_um": float(self.dep_trench_a_var.get()),
                    "b_um": float(self.dep_trench_b_var.get()),
                    "material": self.dep_trench_material_var.get(),
                })

        except ValueError:

            messagebox.showerror(
                "Deposition recipe",
                "All recipe values must be numeric.",
            )

            return

        # ADD TO FLOW intercepts here: the recipe is fully built but
        # nothing has run yet, so the same recipe-building code serves
        # both "run this one step now" and "queue it into the flow".
        if self._pending_flow_add:
            self._append_flow_step(recipe)
            return

        output_dir = tempfile.mkdtemp(
            prefix="tcad2d_real_v2_"
        )

        config_file = Path(
            output_dir
        ) / "recipe.json"

        result_file = Path(
            output_dir
        ) / "result.json"

        # Chains onto whatever this session already built (see
        # _chained_flow_config()) instead of a fresh wafer.
        config_file.write_text(
            json.dumps(
                self._chained_flow_config(recipe, output_dir),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        model_label = self.deposition_model.get()

        time_note = (
            f" ({recipe['deposition_time_s']}s)"
            if "deposition_time_s" in recipe
            else " (zero-duration geometric stamp)"
        )
        self._log(
            f"\n================================\n"
            f"REAL VIENNAPS {model_label.upper()} START\n"
            f"================================\n"
            f"1. MakeTrench\n"
            f"2. {model_label}{time_note}\n"
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

        self.wafer.processed = True
        self.process_stage = "deposited"
        self.last_final_mesh = result.get("final_mesh")
        self.completed_steps.append(recipe)

        self._activate_stages(
            0,
            1,
            2,
            3,
            4,
            5,
            6,
        )

        self.history.append(
            f"ViennaPS {model_label}"
        )

        self._log(
            f"\n================================\n"
            f"REAL VIENNAPS {model_label.upper()} COMPLETE\n"
            f"================================\n"
            f"Surface files: "
            f"{len(result.get('snapshots', []))}\n"
            f"Final mesh:\n"
            f"{result['final_mesh']}\n"
        )

        self._update_process_buttons()

        self.redraw()

        messagebox.showinfo(
            "ViennaPS",
            f"ViennaPS {model_label} simulation complete.\n\n"
            f"Final mesh:\n{result['final_mesh']}",
        )

    def _make_geometry_panel(
        self,
        parent,
    ):
        """MOSFET gate-stack geometry (registry category "geometry",
        model "gate_stack") -- see tcad/process/geometry/gate_stack.py's
        own module docstring for why this does not fit the etch/
        oxidation/deposition pattern:

        - No lithography precedes it (no PR/mask fields to reuse) --
          it builds Si + gate oxide + electrode + separate S/D pads
          from scratch in one shot, so this button is always enabled,
          like NEW WAFER, not gated by self.process_stage the way
          etch/oxidation/deposition are.
        - It is TERMINAL: GateStack.__init__ refuses inherited_domain
          outright, and chaining any further vps.Process() call onto
          its export is confirmed (in the module docstring) to
          silently corrupt 4 of its 5 materials. So a successful build
          does not enable any further process button -- process_stage
          is set to "gate_stack", which _update_process_buttons()'s
          dict has no entry for (falls through to its own default: no
          buttons enabled), and _activate_stages() (the 01-08
          litho/process sequence markers) is deliberately NOT called,
          since this build did not go through that sequence at all.

        Field defaults are the same ones
        tests/integration/test_gate_stack_geometry_real.py already
        verifies against real ViennaPS 4.6.2 + DevSim, not invented.
        Materials (gate=TiN, source=W, drain=Cu, oxide=SiO2) are not
        exposed as fields for v1 -- gate_stack.py's own recipe.get()
        defaults already match the verified test values.
        """

        frame = ttk.LabelFrame(
            parent,
            text="MOSFET gate stack (standalone, terminal geometry)",
            padding=10,
        )

        self._panel_frames["gate_stack"] = frame

        frame.pack(
            fill="x",
            pady=10,
        )

        ttk.Label(
            frame,
            text=(
                "Builds Si + gate oxide + electrode + separate S/D pads "
                "directly -- no lithography step, and no further process "
                "may be chained onto the result (see gate_stack.py's own "
                "module docstring)."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=(0, 6),
        )

        self.gs_x_extent_var = self._field(
            frame, "X extent (µm)", 6.0,
        )
        self.gs_y_extent_var = self._field(
            frame, "Y extent (µm)", 3.0,
        )
        self.gs_silicon_depth_var = self._field(
            frame, "Si depth (µm)", 1.0,
        )
        self.gs_channel_left_var = self._field(
            frame, "Channel left (µm)", -0.8,
        )
        self.gs_channel_right_var = self._field(
            frame, "Channel right (µm)", 0.8,
        )
        self.gs_source_left_var = self._field(
            frame, "Source pad left (µm)", -2.4,
        )
        self.gs_source_right_var = self._field(
            frame, "Source pad right (µm)", -1.0,
        )
        self.gs_drain_left_var = self._field(
            frame, "Drain pad left (µm)", 1.0,
        )
        self.gs_drain_right_var = self._field(
            frame, "Drain pad right (µm)", 2.4,
        )
        self.gs_gate_oxide_var = self._field(
            frame, "Gate oxide thickness (µm)", 0.02,
        )
        self.gs_gate_height_var = self._field(
            frame, "Gate electrode height (µm)", 0.15,
        )
        self.gs_pad_height_var = self._field(
            frame, "S/D pad height (µm)", 0.10,
        )

        self.gate_stack_button = ttk.Button(
            frame,
            text="BUILD GATE STACK — VIENNAPS",
            command=self.run_gate_stack,
        )
        self.gate_stack_button.pack(
            fill="x",
            pady=(12, 3),
        )

        ttk.Label(
            frame,
            text=(
                "Uses the shared Grid delta (µm) field above (Etch "
                "recipe panel)."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=5,
        )

    def run_gate_stack(self):

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
                "_process_category": "geometry",
                "_process_model_key": "gate_stack",

                "grid_delta_um":
                    float(
                        self.grid_var.get()
                    ),

                "x_extent_um": float(self.gs_x_extent_var.get()),
                "y_extent_um": float(self.gs_y_extent_var.get()),
                "silicon_depth_um": float(self.gs_silicon_depth_var.get()),

                "channel_um": [
                    float(self.gs_channel_left_var.get()),
                    float(self.gs_channel_right_var.get()),
                ],
                "source_um": [
                    float(self.gs_source_left_var.get()),
                    float(self.gs_source_right_var.get()),
                ],
                "drain_um": [
                    float(self.gs_drain_left_var.get()),
                    float(self.gs_drain_right_var.get()),
                ],

                "gate_oxide_thickness_um": float(self.gs_gate_oxide_var.get()),
                "gate_height_um": float(self.gs_gate_height_var.get()),
                "pad_height_um": float(self.gs_pad_height_var.get()),
            }

        except ValueError:

            messagebox.showerror(
                "Gate stack recipe",
                "All recipe values must be numeric.",
            )

            return

        # ADD TO FLOW intercepts here: the recipe is fully built but
        # nothing has run yet, so the same recipe-building code serves
        # both "run this one step now" and "queue it into the flow".
        if self._pending_flow_add:
            self._append_flow_step(recipe)
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

        self._log(
            f"\n================================\n"
            f"REAL VIENNAPS GATE STACK START\n"
            f"================================\n"
            f"Standalone build -- no lithography, terminal geometry.\n"
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

        self.wafer.processed = True
        self.process_stage = "gate_stack"
        self.last_final_mesh = result.get("final_mesh")

        # Gate stack is standalone/terminal (see the module docstring in
        # tcad/process/geometry/gate_stack.py -- it refuses
        # inherited_domain outright), so it deliberately does NOT join
        # self.completed_steps the way etch/oxidation/deposition do.
        # Clearing here instead of leaving it stale prevents a LATER
        # standalone RUN click from silently resurrecting the
        # pre-gate-stack history via _chained_flow_config() as if this
        # build had never happened.
        self.completed_steps = []

        # Deliberately NOT calling self._activate_stages(...): this
        # build did not go through the 01-08 litho/process sequence at
        # all, so marking those stage markers "done" would misrepresent
        # what actually happened. _update_process_buttons() below also
        # deliberately leaves every gated button disabled ("gate_stack"
        # has no entry in its dict), matching the module docstring's
        # "do not chain a further process step onto it".

        self.history.append(
            "ViennaPS MOSFET gate stack"
        )

        self._log(
            f"\n================================\n"
            f"REAL VIENNAPS GATE STACK COMPLETE\n"
            f"================================\n"
            f"Surface files: "
            f"{len(result['snapshots'])}\n"
            f"Final mesh:\n"
            f"{result['final_mesh']}\n"
        )

        self._update_process_buttons()

        self.redraw()

        messagebox.showinfo(
            "ViennaPS",
            f"ViennaPS gate stack build complete.\n\n"
            f"Final mesh:\n{result['final_mesh']}",
        )

    def _make_doping_panel(
        self,
        parent,
    ):
        """Doping (tcad/physics/doping.py) -- architecturally unlike
        every other panel in this file: it is NOT a registry category
        (no ProcessStep, no vps.Process() call at all), so it does not
        go through worker_main()'s subprocess pattern. It is a pure-
        Python operation that reads the most recently produced real
        mesh (self.last_final_mesh, via build_process_result) and
        attaches a DopingProfile to it -- no ViennaPS simulation, no
        DevSim import (doping.py's own module docstring: "this module
        ... has no devsim import"). Cheap enough to run directly on the
        Tk main thread like a field-visibility toggle, unlike every
        other "START ..." button in this file.

        Consequently this panel is gated on "a real mesh currently
        exists" (self.wafer.processed + self.last_final_mesh), handled
        in _update_process_buttons(), NOT on self.process_stage --
        doping can be applied after etch, oxidation, deposition, OR a
        gate_stack build alike.

        IMPORTANT SCOPE LIMIT, stated up front in the panel itself:
        this only attaches a DopingProfile object and reports it in the
        log -- it does NOT run a DevSim solve, place contacts, or show
        an I-V/C-V curve. Wiring an actual biased device simulation
        into this GUI is a separate, much larger feature (contacts,
        equations, bias sweeps, plotting) that CLAUDE.md's "one
        subsystem at a time" rule argues against bundling into this
        step.

        Field defaults are the same ones already verified against real
        ViennaPS + DevSim in tests/integration/test_phase7_doping_real.py
        (uniform), test_phase8_pn_junction_real.py (step_junction),
        test_gaussian_implant_doping_real.py (gaussian_implant), and
        test_implant_windows_doping_real.py (implant_windows, source +
        drain -- exactly 2 windows, matching that test; not a general
        N-window UI, which nothing here has verified).
        """

        frame = ttk.LabelFrame(
            parent,
            text="Doping",
            padding=10,
        )

        self._panel_frames["doping"] = frame

        frame.pack(
            fill="x",
            pady=10,
        )

        ttk.Label(
            frame,
            text=(
                "Attaches a DopingProfile to the most recent real mesh "
                "(any of etch/oxidation/deposition/gate stack). Does "
                "NOT run a DevSim solve or show an I-V/C-V curve -- "
                "device biasing is out of scope for this panel."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=(0, 6),
        )

        ttk.Label(
            frame,
            text="Doping kind",
        ).pack(
            anchor="w"
        )

        self.doping_kind = tk.StringVar(
            value="Uniform"
        )

        ttk.Combobox(
            frame,
            textvariable=self.doping_kind,
            state="readonly",
            values=[
                "Uniform",
                "Step Junction",
                "Gaussian Implant",
                "Implant Windows",
            ],
        ).pack(
            fill="x"
        )

        doping_params_container = ttk.Frame(frame)
        doping_params_container.pack(
            fill="x"
        )

        uniform_frame = ttk.Frame(doping_params_container)
        self.dope_uniform_region_var = self._field(
            uniform_frame, "Region", "Si",
        )
        self.dope_uniform_conc_var = self._field(
            uniform_frame, "Net doping (cm^-3, signed)", 1.0e17,
        )

        step_frame = ttk.Frame(doping_params_container)
        self.dope_step_region_var = self._field(
            step_frame, "Region", "Si",
        )
        self.dope_step_axis_var = self._field(
            step_frame, "Axis (x/y)", "x",
        )
        self.dope_step_position_var = self._field(
            step_frame, "Junction position (µm)", 0.0,
        )
        self.dope_step_donor_var = self._field(
            step_frame, "Donor conc (cm^-3)", 1.0e18,
        )
        self.dope_step_acceptor_var = self._field(
            step_frame, "Acceptor conc (cm^-3)", 1.0e18,
        )

        gaussian_frame = ttk.Frame(doping_params_container)
        self.dope_gauss_region_var = self._field(
            gaussian_frame, "Region", "Si",
        )
        self.dope_gauss_axis_var = self._field(
            gaussian_frame, "Axis (x/y)", "x",
        )
        self.dope_gauss_position_var = self._field(
            gaussian_frame, "Peak position (µm)", 0.0,
        )
        self.dope_gauss_straggle_var = self._field(
            gaussian_frame, "Straggle (µm)", 0.5,
        )
        self.dope_gauss_conc_var = self._field(
            gaussian_frame, "Peak conc (cm^-3, signed)", 1.0e17,
        )

        windows_frame = ttk.Frame(doping_params_container)
        self.dope_win_region_var = self._field(
            windows_frame, "Region", "Si",
        )
        self.dope_win_axis_var = self._field(
            windows_frame, "Axis (x/y)", "x",
        )
        self.dope_win_background_var = self._field(
            windows_frame, "Background doping (cm^-3, signed)", -1.0e17,
        )
        self.dope_win_src_min_var = self._field(
            windows_frame, "Source window min (µm)", -1.6,
        )
        self.dope_win_src_max_var = self._field(
            windows_frame, "Source window max (µm)", -0.6,
        )
        self.dope_win_src_conc_var = self._field(
            windows_frame, "Source window conc (cm^-3)", 1.0e20,
        )
        self.dope_win_drn_min_var = self._field(
            windows_frame, "Drain window min (µm)", 0.6,
        )
        self.dope_win_drn_max_var = self._field(
            windows_frame, "Drain window max (µm)", 1.6,
        )
        self.dope_win_drn_conc_var = self._field(
            windows_frame, "Drain window conc (cm^-3)", 1.0e20,
        )
        ttk.Label(
            windows_frame,
            text=(
                "Exactly 2 windows (source + drain), superposed on the "
                "background -- matches the one real-verified "
                "implant_windows test, not a general N-window UI."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

        self._doping_kind_frames = {
            "Uniform": uniform_frame,
            "Step Junction": step_frame,
            "Gaussian Implant": gaussian_frame,
            "Implant Windows": windows_frame,
        }

        self.doping_kind.trace_add(
            "write",
            lambda *_args: self._update_doping_field_visibility(),
        )
        self._update_doping_field_visibility()

        self.doping_button = ttk.Button(
            frame,
            text="APPLY DOPING",
            command=self.run_doping,
        )
        self.doping_button.pack(
            fill="x",
            pady=(12, 3),
        )

    def _update_doping_field_visibility(self):
        """Same mechanism as _update_etch_field_visibility()."""

        selected = self.doping_kind.get()

        for kind_name, group_frame in self._doping_kind_frames.items():
            if kind_name == selected:
                group_frame.pack(fill="x")
            else:
                group_frame.pack_forget()

    def run_doping(self):

        if not (
            self.wafer.processed
            and self.last_final_mesh
            and Path(self.last_final_mesh).exists()
        ):

            messagebox.showwarning(
                "Process order",
                "Run a real process step (etch, oxidation, deposition, "
                "or gate stack) first.",
            )

            return

        kind = self.doping_kind.get()

        try:

            process_result = build_process_result(
                {"final_mesh": self.last_final_mesh, "snapshots": []}
            )

            if kind == "Uniform":

                region = self.dope_uniform_region_var.get()
                conc = float(self.dope_uniform_conc_var.get())
                doped_result = apply_uniform_doping(
                    process_result, {region: conc},
                )
                summary = f"region={region!r} net_doping_cm3={conc:.3e}"

            elif kind == "Step Junction":

                region = self.dope_step_region_var.get()
                axis = self.dope_step_axis_var.get()
                position = float(self.dope_step_position_var.get())
                donor = float(self.dope_step_donor_var.get())
                acceptor = float(self.dope_step_acceptor_var.get())
                doped_result = apply_step_junction_doping(
                    process_result, region=region, junction_axis=axis,
                    junction_position_um=position,
                    donor_conc_cm3=donor, acceptor_conc_cm3=acceptor,
                )
                summary = (
                    f"region={region!r} axis={axis!r} "
                    f"junction@{position}um donor={donor:.3e} "
                    f"acceptor={acceptor:.3e}"
                )

            elif kind == "Gaussian Implant":

                region = self.dope_gauss_region_var.get()
                axis = self.dope_gauss_axis_var.get()
                position = float(self.dope_gauss_position_var.get())
                straggle = float(self.dope_gauss_straggle_var.get())
                conc = float(self.dope_gauss_conc_var.get())
                doped_result = apply_gaussian_implant_doping(
                    process_result, region=region, junction_axis=axis,
                    peak_position_um=position, straggle_um=straggle,
                    peak_conc_cm3=conc,
                )
                summary = (
                    f"region={region!r} axis={axis!r} "
                    f"peak@{position}um straggle={straggle}um "
                    f"peak_conc={conc:.3e}"
                )

            elif kind == "Implant Windows":

                region = self.dope_win_region_var.get()
                axis = self.dope_win_axis_var.get()
                background = float(self.dope_win_background_var.get())
                windows = [
                    {
                        "min_um": float(self.dope_win_src_min_var.get()),
                        "max_um": float(self.dope_win_src_max_var.get()),
                        "conc_cm3": float(self.dope_win_src_conc_var.get()),
                    },
                    {
                        "min_um": float(self.dope_win_drn_min_var.get()),
                        "max_um": float(self.dope_win_drn_max_var.get()),
                        "conc_cm3": float(self.dope_win_drn_conc_var.get()),
                    },
                ]
                doped_result = apply_implant_windows_doping(
                    process_result, region=region, axis=axis,
                    background_doping_cm3=background, windows=windows,
                )
                summary = (
                    f"region={region!r} axis={axis!r} "
                    f"background={background:.3e} "
                    f"windows={windows}"
                )

            else:

                messagebox.showinfo(
                    "Doping",
                    "Unknown doping kind selected.",
                )

                return

        except ValueError:

            messagebox.showerror(
                "Doping recipe",
                "All numeric recipe values must be numeric.",
            )

            return

        except Exception as exc:

            messagebox.showerror(
                "Doping",
                str(exc),
            )

            return

        self.last_doped_result = doped_result

        self.history.append(
            f"Doping: {kind}"
        )

        self._log(
            f"\n================================\n"
            f"DOPING APPLIED: {kind.upper()}\n"
            f"================================\n"
            f"{summary}\n"
            f"Materials in mesh: "
            f"{[r.name for r in doped_result.material_regions]}\n"
            f"(DopingProfile attached only -- no DevSim solve run.)\n"
        )

        self._update_process_buttons()

        messagebox.showinfo(
            "Doping",
            f"Doping profile attached ({kind}).\n\n{summary}\n\n"
            f"No DevSim solve was run -- this only attaches the "
            f"DopingProfile object and reports it in the process log.",
        )

    def _make_measurement_panel(
        self,
        parent,
    ):
        """2-terminal DevSim device measurement -- reuses the doping
        already attached via _make_doping_panel() (self.last_doped_result)
        and the real, already-verified 2-terminal I-V pipeline
        (tcad.device.devsim.mesh_import.import_process_result +
        tcad.device.devsim.doping_mapping.apply_doping +
        tcad.characterization.pn_junction_iv_sweep.run_pn_junction_iv_sweep
        -- the exact sequence
        tests/integration/test_phase8_pn_junction_real.py already
        verifies against real ViennaPS + DevSim).

        Unlike every process/doping panel, this is the first GUI code
        path that imports devsim directly -- doping.py's own module
        docstring states it "has no devsim import" (see
        _make_doping_panel()'s own docstring), so wiring an actual
        solve needed a new import point.

        "Pin" here is deliberately NOT a free-form point the user
        clicks on the mesh -- contacts are auto-derived by
        mesh_import.py at the doped region's own axis extremes
        ("<region>_<axis>min"/"...max"), exactly like every existing
        2-terminal characterization test in this project. What IS
        user-configurable here: which of the two auto-derived contacts
        acts as the driven "voltage source" pin (a chosen bias, in
        volts) versus the "multimeter" pin (held at 0V/ground, current
        read out) -- both pins always get both a forced voltage AND a
        read current (real SMU semantics), so "source" vs "multimeter"
        is a UI framing choice over the same underlying two-contact
        bias, not two different backend mechanisms.

        run_pn_junction_iv_sweep()'s own docstring states it
        reproducibly fails to reconverge if called twice on the same
        already-solved device -- so every MEASURE click imports a
        FRESH DevSim device from scratch (a fixed mesh_name/device_name
        reused across clicks is safe only because delete_device() +
        delete_mesh() always runs in a `finally` block first, mirroring
        tcad/cli/run_pipeline.py's own _cleanup_device() pattern)
        rather than trying to keep one device alive across multiple
        measurements.

        Mesh refinement near the doping junction (refine_near_um) is
        only applied for step_junction doping, matching the one
        combination Phase 8 real-verified for convergence at high
        doping (donor=acceptor=1e18 cm^-3, grid_delta_um=0.15 -> mesh
        ~37x too coarse without it). Other doping kinds run unrefined
        through this panel -- convergence for those combinations is
        NOT yet verified here; a real DevSim convergence failure
        surfaces as a normal error dialog rather than being hidden.
        """

        frame = ttk.LabelFrame(
            parent,
            text="Device measurement (2-terminal)",
            padding=10,
        )

        self._panel_frames["measurement"] = frame

        frame.pack(
            fill="x",
            pady=10,
        )

        ttk.Label(
            frame,
            text=(
                "Uses the doping already applied above. Auto-derives 2 "
                "contacts at the doped region's own axis extremes -- "
                "pick which one is the driven voltage source; the "
                "other is held at 0V and read as the \"multimeter\" "
                "pin. Mesh refinement at the junction is only applied "
                "for Step Junction doping -- other kinds are "
                "unverified for convergence here."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=(0, 6),
        )

        self.meas_axis_var = self._field(
            frame, "Contact axis (x/y)", "x",
        )

        ttk.Label(
            frame,
            text="Voltage source pin",
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

        self.meas_source_pin = tk.StringVar(
            value="max"
        )

        ttk.Combobox(
            frame,
            textvariable=self.meas_source_pin,
            state="readonly",
            values=["min", "max"],
        ).pack(
            fill="x"
        )

        ttk.Label(
            frame,
            text=(
                "\"min\"/\"max\" = the doped region's own lower/upper "
                "extreme along the contact axis (e.g. Si_xmin / "
                "Si_xmax) -- the other one is the multimeter/GND pin."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(
            anchor="w",
            pady=(2, 0),
        )

        self.meas_voltage_var = self._field(
            frame, "Source voltage (V)", 0.3,
        )

        self.measure_button = ttk.Button(
            frame,
            text="MEASURE",
            command=self.run_measurement,
        )
        self.measure_button.pack(
            fill="x",
            pady=(12, 3),
        )

    def _refine_for_implant_windows(self, doped_result):
        """Graded-refine the real mesh at every implant-window edge.

        implant_windows is the one doping kind import_process_result
        cannot auto-refine -- it carries neither junction_position_um
        nor peak_position_um, so _derive_refine_from_doping() returns
        None for it -- and it is also the kind that needs refinement
        most: this panel's own default profile puts 1e20 source/drain
        windows on a -1e17 body, whose Debye length (~1.2nm) is ~170x
        finer than the 0.2um grid a GUI run uses.

        Measured on the shipped GUI path, one doping kind per process
        so no leaked device could fake a failure: without this the
        solve fails outright with "Convergence failure!"; with it the
        same recipe converges (622 -> 13543 mesh points, 16 predicates,
        11269 Si nodes, terminal currents equal and opposite to 4e-16).

        The refinement itself lives in
        tcad.device.devsim.mesh_import.refine_process_result_for_implant_windows()
        so this panel and
        tests/integration/test_gui_measurement_doping_kinds_real.py
        drive ONE implementation, not two copies of it. This method
        only adds the GUI's error dialogs and log line. Returns None if
        no refinement could be derived, in which case the caller aborts
        rather than running a solve already known to fail.
        """

        from tcad.device.devsim.mesh_import import (
            refine_process_result_for_implant_windows,
        )

        try:

            refined_result = refine_process_result_for_implant_windows(
                doped_result,
            )

            if refined_result is None:

                messagebox.showerror(
                    "Measurement",
                    "Could not derive mesh refinement from this "
                    "implant_windows profile, and this doping kind is "
                    "measured NOT to converge unrefined at these "
                    "concentrations. Aborting rather than running a "
                    "solve already known to fail.",
                )

                return None

            self._log(
                f"\nDoping-derived mesh refinement (implant_windows) "
                f"applied -- see {refined_result.volume_mesh_path}\n"
            )

            return refined_result

        except Exception as exc:

            messagebox.showerror(
                "Measurement",
                f"Mesh refinement for implant_windows failed:\n\n{exc}",
            )

            return None

    def run_measurement(self):

        if self.last_doped_result is None:

            messagebox.showwarning(
                "Process order",
                "Apply doping first (see the Doping panel above).",
            )

            return

        from tcad.device.devsim import backend as devsim_backend

        if not devsim_backend.is_available():

            # require_devsim()'s message distinguishes "genuinely not
            # installed" from "installed but failed to import" (e.g. a
            # missing BLAS/LAPACK library) — showing the wrong one sends
            # a user who already has DevSim installed to pip-install a
            # package that's already there instead of the real fix.
            try:
                devsim_backend.require_devsim()
            except RuntimeError as exc:
                messagebox.showerror("DevSim", str(exc))

            return

        axis = self.meas_axis_var.get()

        try:
            voltage = float(self.meas_voltage_var.get())
        except ValueError:

            messagebox.showerror(
                "Measurement recipe",
                "Source voltage must be numeric.",
            )

            return

        doped_result = self.last_doped_result
        region = doped_result.doping.regions[0].region
        kind = doped_result.doping.kind

        from tcad.device.devsim.mesh_import import import_process_result
        from tcad.device.devsim.doping_mapping import apply_doping
        from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
        from tcad.characterization.robust_iv_sweep import (
            run_robust_pn_junction_iv_sweep,
        )

        module = devsim_backend.require_devsim()
        device_name = "gui_measure_device"
        mesh_name = "gui_measure_mesh"
        length_scale_to_cm = 1.0e-4

        refine_kwargs = {}

        if kind == "step_junction":
            region_doping = doped_result.doping.regions[0]
            refine_kwargs = {
                "refine_near_um": region_doping.junction_position_um,
                "refine_axis": region_doping.junction_axis,
            }

        elif kind == "gaussian_implant":
            # import_process_result derives the refinement position from
            # the profile's own peak_position_um -- the same opt-in flag
            # tests/integration/test_auto_refine_from_doping_real.py
            # already verifies for this kind.
            refine_kwargs = {"auto_refine_from_doping": True}

        elif kind == "implant_windows":
            refined_result = self._refine_for_implant_windows(doped_result)

            if refined_result is None:

                return

            doped_result = refined_result

        else:
            self._log(
                "\n(No mesh refinement needed -- uniform doping has no "
                "junction to resolve.)\n"
            )

        imported = None

        try:

            imported = import_process_result(
                doped_result, mesh_name=mesh_name, device_name=device_name,
                contact_regions=[region], contact_axis=axis,
                length_scale_to_cm=length_scale_to_cm,
                **refine_kwargs,
            )

            if len(imported.contacts) != 2:

                messagebox.showerror(
                    "Measurement",
                    f"Expected exactly 2 contacts for region "
                    f"{region!r}, got {imported.contacts}.",
                )

                return

            min_contact, max_contact = imported.contacts[0], imported.contacts[1]
            source_contact = (
                max_contact if self.meas_source_pin.get() == "max" else min_contact
            )
            gnd_contact = min_contact if source_contact == max_contact else max_contact

            if kind == "implant_windows":
                # implant_windows is the kind that puts real production
                # source/drain levels (1e20 cm^-3) on this device, which
                # run_pn_junction_iv_sweep's single-jump strategy cannot
                # reach -- it fails in the EQUILIBRIUM solve before any
                # bias is applied. The robust path ramps the doping
                # level, uses DevSim's own drift-diffusion tolerances,
                # and restores the solution on a failed bias step; it
                # returns the SAME current as the simple path wherever
                # the simple path works (verified to 5.7e-08 relative --
                # see tests/integration/test_robust_iv_sweep_real.py).
                # It registers NetDoping itself, so apply_doping must
                # NOT be called first for this kind.
                self._log(
                    "\nUsing the robust solve path (doping-level "
                    "continuation + DevSim's own drift-diffusion "
                    "tolerances + restoring bias ramp).\n"
                )
                result = run_robust_pn_junction_iv_sweep(
                    device=imported.device, region=region,
                    all_contacts=imported.contacts,
                    sweep_contact=source_contact, sweep_voltages=[voltage],
                    doping=doped_result.doping,
                    length_scale_to_cm=length_scale_to_cm,
                    fixed_contacts={gnd_contact: 0.0},
                )
            else:
                apply_doping(
                    imported.device, doped_result.doping,
                    length_scale_to_cm=length_scale_to_cm,
                )
                result = run_pn_junction_iv_sweep(
                    device=imported.device, region=region,
                    all_contacts=imported.contacts,
                    sweep_contact=source_contact, sweep_voltages=[voltage],
                    fixed_contacts={gnd_contact: 0.0},
                )

        except Exception as exc:

            messagebox.showerror(
                "Measurement",
                str(exc),
            )

            return

        finally:

            if imported is not None:
                try:
                    module.delete_device(device=imported.device)
                    module.delete_mesh(mesh=imported.mesh)
                except Exception:
                    pass

        point = result.points[0]
        source_i = point.currents[source_contact]
        gnd_i = point.currents[gnd_contact]

        self.history.append(
            f"Measurement: {source_contact}={voltage}V"
        )

        self._log(
            f"\n================================\n"
            f"DEVSIM MEASUREMENT\n"
            f"================================\n"
            f"Region={region!r} axis={axis!r} doping_kind={kind!r}\n"
            f"Voltage source pin: {source_contact} = {voltage:+.4f} V "
            f"-> I = {source_i:.6e} A\n"
            f"Multimeter (GND) pin: {gnd_contact} = 0.0000 V "
            f"-> I = {gnd_i:.6e} A\n"
        )

        messagebox.showinfo(
            "Measurement",
            f"Voltage source ({source_contact}): {voltage:+.4f} V, "
            f"I = {source_i:.6e} A\n\n"
            f"Multimeter ({gnd_contact}): 0.0000 V, "
            f"I = {gnd_i:.6e} A",
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
    # ETCH FIELD VISIBILITY
    # --------------------------------------------------------

    def _update_etch_field_visibility(self):
        """Show only the parameter group matching the currently
        selected etch model in the "Etch process" combobox, hiding the
        other three. See _make_etch_panel for why every group frame is
        packed into a single fixed container instead of `frame`
        directly (packing order)."""

        selected = self.etch_model.get()

        for model_name, group_frame in self._etch_model_frames.items():
            if model_name == selected:
                group_frame.pack(
                    fill="x"
                )
            else:
                group_frame.pack_forget()

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

    #: Curated subset of vps.Material -- the full enum has ~80 entries
    #: (see viennaps.Material), most irrelevant to a 2D Si process flow.
    #: These are what this project's own recipes/tests already deposit
    #: or reference (SiO2, Si3N4, PolySi, W, TiN, Cu -- see
    #: gate_stack.py and material_colors in redraw()) plus a generic
    #: "Metal" for a sputter target with no specific alloy chosen.
    _DEPOSITION_MATERIAL_OPTIONS = [
        "SiO2", "Si3N4", "PolySi", "W", "TiN", "Cu", "Metal", "Ta", "Ti",
    ]

    def _material_field(self, parent, label, default):
        """Same layout as _field(), but a readonly material combobox
        instead of a free-text numeric entry -- feeds the recipe's
        optional `material` key (see e.g. isotropic.py's own
        duplicateTopLevelSet() use), which tags the newly-deposited
        region as a genuinely distinct material instead of silently
        merging it into whatever material already sits on top."""

        ttk.Label(
            parent,
            text=label,
        ).pack(
            anchor="w",
            pady=(4, 0),
        )

        variable = tk.StringVar(value=default)

        ttk.Combobox(
            parent,
            textvariable=variable,
            state="readonly",
            values=self._DEPOSITION_MATERIAL_OPTIONS,
        ).pack(
            fill="x"
        )

        return variable

    # --------------------------------------------------------
    # LITHOGRAPHY OPERATION
    # --------------------------------------------------------

    # --------------------------------------------------------
    # MASK OPENINGS (multi-window mask)
    # --------------------------------------------------------

    def _selected_opening_index(self):
        selection = self.openings_list.curselection()
        if selection:
            return int(selection[0])
        return 0 if self.wafer.mask_openings_um else -1

    def _refresh_openings_list(self, select=None):
        """Redraw the listbox from self.wafer.mask_openings_um and keep
        mask_left_um/mask_right_um pointing at the selected one."""
        previous = self._selected_opening_index()
        self.openings_list.delete(0, tk.END)
        for index, (lo, hi) in enumerate(self.wafer.mask_openings_um):
            self.openings_list.insert(
                tk.END, f"{index + 1}.  {lo:.3f} – {hi:.3f} µm"
            )

        if not self.wafer.mask_openings_um:
            return

        target = select if select is not None else previous
        target = max(0, min(target, len(self.wafer.mask_openings_um) - 1))
        self.openings_list.selection_clear(0, tk.END)
        self.openings_list.selection_set(target)
        self._on_opening_selected()

    def _on_opening_selected(self):
        """Load the selected opening into the left/right fields (and
        into wafer.mask_left_um/mask_right_um, which the canvas drag
        handler and the single-opening recipe path both still read)."""
        index = self._selected_opening_index()
        if index < 0 or index >= len(self.wafer.mask_openings_um):
            return
        lo, hi = self.wafer.mask_openings_um[index]
        self.wafer.mask_left_um = lo
        self.wafer.mask_right_um = hi
        self.left_var.set(f"{lo:.3f}")
        self.right_var.set(f"{hi:.3f}")
        self.redraw()

    def add_mask_opening(self):
        """Append a new opening, placed in the first free gap so it does
        not silently overlap an existing one."""
        openings = sorted(self.wafer.mask_openings_um)
        width = self.wafer.width_um
        cursor = 0.0
        placed = None
        for lo, hi in openings:
            if lo - cursor >= 0.3:
                placed = [cursor + 0.1, min(lo - 0.1, cursor + 1.1)]
                break
            cursor = max(cursor, hi)
        if placed is None and width - cursor >= 0.3:
            placed = [cursor + 0.1, min(width - 0.1, cursor + 1.1)]
        if placed is None:
            messagebox.showinfo(
                "Mask openings",
                "No free space left on the mask for another opening.",
            )
            return

        self.wafer.mask_openings_um.append(placed)
        self.wafer.mask_openings_um.sort()
        self._refresh_openings_list(
            select=self.wafer.mask_openings_um.index(placed)
        )
        self._log(f"Mask opening added: {placed[0]:.3f} – {placed[1]:.3f} µm\n")

    def remove_mask_opening(self):
        if len(self.wafer.mask_openings_um) <= 1:
            messagebox.showinfo(
                "Mask openings",
                "A mask needs at least one opening — otherwise no part "
                "of the wafer is exposed and no process step would do "
                "anything.",
            )
            return
        index = self._selected_opening_index()
        removed = self.wafer.mask_openings_um.pop(index)
        self._refresh_openings_list(select=min(index, len(self.wafer.mask_openings_um) - 1))
        self._log(f"Mask opening removed: {removed[0]:.3f} – {removed[1]:.3f} µm\n")

    def update_mask_opening(self):
        """Write the two text fields back into the selected opening."""
        index = self._selected_opening_index()
        if index < 0:
            return
        try:
            lo = float(self.left_var.get())
            hi = float(self.right_var.get())
        except ValueError:
            messagebox.showerror("Mask openings", "Opening edges must be numeric.")
            return
        if hi <= lo:
            messagebox.showerror(
                "Mask openings", "Opening right edge must be larger than left edge."
            )
            return
        self.wafer.mask_openings_um[index] = [lo, hi]
        self.wafer.mask_openings_um.sort()
        self._refresh_openings_list(
            select=self.wafer.mask_openings_um.index([lo, hi])
        )

    def _mask_recipe_keys(self):
        """The mask portion of a process recipe, built from every
        opening rather than just the first.

        Always emits `mask_spans_um` (the OPAQUE complement — see
        tcad.process.base.mask_spans_from_openings). That path honours
        the mask's real POSITION, while the older
        mask_left_um/mask_right_um path goes through MakeTrench, which
        uses only the WIDTH and always centres the window — so a mask
        drawn off to one side used to be processed as a centred one.
        mask_left_um/mask_right_um are still included for any consumer
        that reads them, and for a single centred opening the two paths
        produce the identical geometry (verified: the GUI's own default
        3.5–6.5 on a 10µm wafer gives sidewalls at ±1.5 either way).
        """
        from tcad.process.base import mask_spans_from_openings

        return {
            "mask_left_um": self.wafer.mask_left_um,
            "mask_right_um": self.wafer.mask_right_um,
            "mask_spans_um": [
                list(span)
                for span in mask_spans_from_openings(
                    self.wafer.mask_openings_um, self.wafer.width_um
                )
            ],
        }

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
        """Keep every process operation reachable.

        This used to enable exactly ONE button -- the next step of a
        single hard-wired sequence (litho -> etch OR oxidation OR
        deposition -> strip). That made whole classes of real device
        impossible to build: a textbook PN-junction diode needs
        oxidation -> lithography -> doping -> metallization ->
        lithography, and nothing in that order was reachable.

        Order is now the user's to choose (see _make_flow_panel), so
        the buttons are no longer gated on `process_stage`.
        run_etch/run_oxidation/run_deposition dropped their own
        litho-first checks too (prepare_domain() never actually needed
        develop() to have run -- it only ever reads self.wafer's
        mask/PR-thickness fields, which always carry a value). What
        remains gated here is genuinely required: doping needs a real
        mesh to attach to, and measurement needs doping already applied
        (run_measurement checks that).
        """
        for button in (
            self.coat_button,
            self.align_button,
            self.expose_button,
            self.develop_button,
            self.etch_button,
            self.oxidation_button,
            self.deposition_button,
            self.strip_button,
        ):
            button.configure(state="normal")

        # Doping is not part of the litho/process_stage sequence at
        # all -- it attaches a DopingProfile to whatever real mesh was
        # most recently produced (etch/oxidation/deposition/gate_stack
        # all count), so it is gated on "a real mesh currently exists"
        # rather than on process_stage, same condition redraw() already
        # uses for real_mesh_available.
        doping_ready = bool(
            self.wafer.processed
            and self.last_final_mesh
            and Path(self.last_final_mesh).exists()
        )
        self.doping_button.configure(
            state="normal" if doping_ready else "disabled"
        )

        # Measurement needs doping already attached (self.last_doped_result),
        # same "not part of the litho/process_stage sequence" reasoning
        # as doping itself.
        self.measure_button.configure(
            state="normal" if self.last_doped_result is not None else "disabled"
        )

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
        if self.process_stage not in ("etched", "oxidized", "deposited"):
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

        # No litho-first gate -- see run_oxidation()'s matching comment.
        # This used to be the one step that still enforced litho-first;
        # keeping it while oxidation/deposition dropped theirs would
        # just move the same "why do I have to do X first" complaint
        # here instead of fixing it, and prepare_domain() needs nothing
        # from develop() that self.wafer doesn't already carry a value
        # for (defaulted or user-set).
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
                "_process_category": "etching",
                "_process_model_key": model_key,

                # Every mask opening, not just the first -- see
                # _mask_recipe_keys().
                **self._mask_recipe_keys(),

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

        # ADD TO FLOW intercepts here: the recipe is fully built but
        # nothing has run yet, so the same recipe-building code serves
        # both "run this one step now" and "queue it into the flow".
        if self._pending_flow_add:
            self._append_flow_step(recipe)
            return

        output_dir = tempfile.mkdtemp(
            prefix="tcad2d_real_v2_"
        )

        config_file = Path(
            output_dir
        ) / "recipe.json"

        result_file = Path(
            output_dir
        ) / "result.json"

        # Chains onto whatever this session already built (see
        # _chained_flow_config()) instead of a fresh wafer.
        config_file.write_text(
            json.dumps(
                self._chained_flow_config(recipe, output_dir),
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
        self.wafer.processed = True
        self.process_stage = "etched"
        self.last_final_mesh = result.get("final_mesh")
        self.completed_steps.append(recipe)

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
            f"{len(result.get('snapshots', []))}\n"
            f"Final mesh:\n"
            f"{result['final_mesh']}\n"
        )

        # See run_oxidation()'s matching comment: this call was missing
        # here too, so PR strip never visibly enabled after a real etch
        # through the normal UI flow.
        self._update_process_buttons()

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
        .vtu volume mesh), instead of the placeholder rectangle in
        redraw(). Returns True on success; False if the mesh can't be
        read (meshio/ViennaPS unavailable, file missing, no triangle
        cells, degenerate bounds, etc.), so the caller falls back to
        the placeholder in that case -- this must never raise.

        Each material is drawn as its TRUE boundary silhouette (via
        _material_boundary_loops(), traced from every one of its
        triangles, not a decimated sample) -- one solid filled polygon
        per connected region. This is what makes a genuine void (e.g.
        an isotropic-etch undercut) show up correctly: the silhouette
        simply excludes it, rather than either hiding it under a
        stale placeholder (the original bug -- see CLAUDE.md's "GUI:
        real-mesh render still shows intact Si under an isotropic
        undercut") or rendering it as a sparse scatter of randomly
        -sampled triangles (which is what drawing every material this
        way used to look like, and is why redraw() no longer draws
        the flat Si-substrate rectangle at all when this succeeds --
        this silhouette IS the substrate shape now, notch included).
        Falls back to the old per-triangle decimated rendering only
        for a material whose boundary isn't a clean set of simple
        loops (see _material_boundary_loops's own docstring for when).

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
            tags = [int(t) for t in mesh.cell_data["Material"][block_index]]
            triangle_data = triangle_block.data

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
                # gate_stack.py's own default electrode/pad materials --
                # otherwise fall back to the generic gray, which would
                # make gate/source/drain indistinguishable from each
                # other and from Si.
                "TiN": "#7d3c98",
                "W": "#f39c12",
                "Cu": "#c0392b",
            }
            material_names = {}

            def to_canvas(node_idx):
                px, py = points[node_idx][0], points[node_idx][1]
                return x0 + (px - x_min) * x_scale, surface_y - py * y_scale

            by_material = {}
            for idx, tag in enumerate(tags):
                by_material.setdefault(tag, []).append(idx)

            # redraw() runs on every window resize (<Configure>, see
            # __init__), and each run rebuilds the whole canvas from
            # scratch. Per material, prefer its TRUE boundary
            # silhouette (_material_boundary_loops(), traced from
            # EVERY one of its triangles -- boundary edges are
            # O(perimeter), not O(area), so this stays fast without
            # decimating) and draw it as one solid filled polygon per
            # connected region. This is what makes a genuine void
            # (e.g. an isotropic-etch undercut) render correctly: the
            # silhouette simply excludes it, so nothing needs to be
            # separately cleared or painted over.
            #
            # A fine grid_delta / deep floor_depth_um combination can
            # still produce a material whose boundary tracing fails
            # (see that function's own docstring) -- for that fallback
            # case ONLY, decimate to a fixed cap with a random (not
            # positional) per-material sample, seeded so repeated
            # redraws of the same mesh are stable. (An earlier version
            # of this decimation used a positional stride across ALL
            # materials combined, which reproduced whatever spatial
            # bias already existed in the exported file's triangle
            # order -- confirmed to leave the Si cross-section
            # rendered as a small stray triangle instead of the whole
            # substrate. Per-material boundary tracing replaces that
            # bug's fix rather than just inheriting it.)
            rng = random.Random(0)

            for tag, indices in by_material.items():
                name = material_names.get(tag)
                if name is None:
                    name = str(module.Material(tag)).split("'")[1]
                    material_names[tag] = name
                color = material_colors.get(name, "#b0b0b0")

                loops = _material_boundary_loops([triangle_data[i] for i in indices])

                if loops:
                    for loop in loops:
                        coords = []
                        for node_idx in loop:
                            cx, cy = to_canvas(node_idx)
                            coords.extend([cx, cy])
                        if len(coords) >= 6:
                            canvas.create_polygon(coords, fill=color, outline=color)
                    continue

                draw_indices = indices
                if len(draw_indices) > _MAX_RENDERED_TRIANGLES:
                    draw_indices = rng.sample(draw_indices, _MAX_RENDERED_TRIANGLES)

                for i in draw_indices:
                    coords = []
                    for node_idx in triangle_data[i]:
                        cx, cy = to_canvas(node_idx)
                        coords.extend([cx, cy])

                    # Skip sub-pixel triangles (invisible anyway).
                    tri_xs = coords[0::2]
                    tri_ys = coords[1::2]
                    if max(tri_xs) - min(tri_xs) < 1.0 and max(tri_ys) - min(tri_ys) < 1.0:
                        continue

                    canvas.create_polygon(coords, fill=color, outline=color)

            # p/n doping overlay: a translucent red (p-type, net
            # negative) / blue (n-type, net positive) tint over whatever
            # doped region(s) exist, so a doping change is visible on
            # screen instead of only in the log. Drawn last so it sits
            # on top of the material fill; stipple keeps the material
            # silhouette underneath legible rather than hiding it.
            if self.last_doped_result is not None and getattr(
                self.last_doped_result, "doping", None
            ) is not None:
                for region_name in {r.region for r in self.last_doped_result.doping.regions}:
                    region_tag = next(
                        (t for t, n in material_names.items() if n == region_name),
                        None,
                    )
                    if region_tag is None:
                        continue
                    node_idxs = {
                        node for i in by_material.get(region_tag, [])
                        for node in triangle_data[i]
                    }
                    if not node_idxs:
                        continue
                    region_y_top = max(points[n][1] for n in node_idxs)
                    region_y_bot = min(points[n][1] for n in node_idxs)
                    cy_top = surface_y - region_y_top * y_scale
                    cy_bot = surface_y - region_y_bot * y_scale

                    for x_lo_um, x_hi_um, color in self._doping_color_segments(
                        region_name, x_min, x_max
                    ):
                        if x_hi_um <= x_lo_um:
                            continue
                        cx_lo = x0 + (x_lo_um - x_min) * x_scale
                        cx_hi = x0 + (x_hi_um - x_min) * x_scale
                        canvas.create_rectangle(
                            cx_lo, cy_top, cx_hi, cy_bot,
                            fill=color, outline="", stipple="gray50",
                        )

            canvas.create_text(
                x0 + 5, surface_y + 12,
                text="REAL VIENNAPS MESH",
                anchor="w", fill="#333",
                font=("Segoe UI", 8, "italic"),
            )
            return True
        except Exception:
            return False

    def _doping_color_segments(self, region_name, x_min_um, x_max_um):
        """(x_lo_um, x_hi_um, color) segments for region_name's doping,
        in real domain x coordinates, matching apply_doping()'s own
        sign convention exactly (tcad/device/devsim/doping_mapping.py:
        NetDoping = Donors-Acceptors for step_junction, background +
        summed windows for implant_windows, etc.) so the overlay never
        shows a p/n split that disagrees with what would actually be
        solved. n-type (net doping >= 0) is blue, p-type (net doping
        < 0) is red -- the standard convention the doping panel itself
        already documents (net_doping_cm3: "positive = net donor
        (n-type), negative = net acceptor (p-type)").

        Only "x"-axis doping is visualized (every doping kind this GUI
        exposes defaults to axis="x"); a region doped along "y" is left
        uncolored rather than drawn wrong.
        """
        doping = getattr(self.last_doped_result, "doping", None)
        if doping is None:
            return []

        N_COLOR, P_COLOR = "#2f6fed", "#e0393e"
        segments = []

        for region in doping.regions:
            if region.region != region_name:
                continue
            axis = getattr(region, "junction_axis", None)

            if doping.kind == "uniform":
                color = N_COLOR if (region.net_doping_cm3 or 0.0) >= 0 else P_COLOR
                segments.append((x_min_um, x_max_um, color))

            elif doping.kind == "gaussian_implant":
                if axis != "x":
                    continue
                color = N_COLOR if (region.peak_conc_cm3 or 0.0) >= 0 else P_COLOR
                segments.append((x_min_um, x_max_um, color))

            elif doping.kind == "step_junction":
                if axis != "x":
                    continue
                position = region.junction_position_um
                acceptor_color = (
                    P_COLOR if (region.acceptor_conc_cm3 or 0.0) > 0 else N_COLOR
                )
                donor_color = (
                    N_COLOR if (region.donor_conc_cm3 or 0.0) >= 0 else P_COLOR
                )
                segments.append((x_min_um, position, acceptor_color))
                segments.append((position, x_max_um, donor_color))

            elif doping.kind == "implant_windows":
                if axis != "x":
                    continue
                background = region.net_doping_cm3 or 0.0
                bg_color = N_COLOR if background >= 0 else P_COLOR
                windows = sorted(
                    region.implant_windows or [], key=lambda w: w["min_um"]
                )
                cursor = x_min_um
                for window in windows:
                    lo = max(x_min_um, window["min_um"])
                    hi = min(x_max_um, window["max_um"])
                    if lo > cursor:
                        segments.append((cursor, lo, bg_color))
                    net = background + window["conc_cm3"]
                    segments.append((lo, hi, N_COLOR if net >= 0 else P_COLOR))
                    cursor = max(cursor, hi)
                if cursor < x_max_um:
                    segments.append((cursor, x_max_um, bg_color))

        return segments

    def _wafer_canvas_x_transform(self):
        """(x0, x1, scale) mapping wafer x in [0, width_um] to canvas
        pixel x -- the SAME geometry redraw() computes inline for the
        mask-opening rectangle, factored out here so the mouse-drag
        mask editor below stays in sync with it rather than keeping a
        second, driftable copy of the same formula."""
        width = max(self.canvas.winfo_width(), 700)
        x0 = 70
        x1 = width - 70
        scale = (x1 - x0) / self.wafer.width_um
        return x0, x1, scale

    def _canvas_x_to_mask_um(self, canvas_x):
        x0, x1, scale = self._wafer_canvas_x_transform()
        clipped = min(max(canvas_x, x0), x1)
        return (clipped - x0) / scale

    def _mask_dragging_allowed(self):
        # Mouse-drawn mask editing targets the SAME mask_left_um/
        # mask_right_um fields the Lithography panel's text entries
        # already do (_read_lithography_fields reads them at process-run
        # time) -- so it is meaningful exactly when those fields still
        # are: before any real process step has produced a mesh. Once
        # processed, the canvas shows the real ViennaPS mesh instead of
        # the mask placeholder, and editing mask_left_um/right_um then
        # would silently disagree with the geometry already on screen.
        return not self.wafer.processed

    def _on_mask_drag_start(self, event):
        if not self._mask_dragging_allowed():
            return
        self._mask_drag_start_um = self._canvas_x_to_mask_um(event.x)

    def _on_mask_drag_move(self, event):
        if self._mask_drag_start_um is None:
            return
        x0, x1, scale = self._wafer_canvas_x_transform()
        start_x = x0 + self._mask_drag_start_um * scale
        end_x = min(max(event.x, x0), x1)

        if self._mask_drag_rect_id is not None:
            self.canvas.delete(self._mask_drag_rect_id)

        height = max(self.canvas.winfo_height(), 500)
        self._mask_drag_rect_id = self.canvas.create_rectangle(
            start_x, 20, end_x, height - 20,
            outline="#1a73e8", width=2, dash=(4, 2),
        )

    def _on_mask_drag_end(self, event):
        if self._mask_drag_start_um is None:
            return

        end_um = self._canvas_x_to_mask_um(event.x)
        left_um = min(self._mask_drag_start_um, end_um)
        right_um = max(self._mask_drag_start_um, end_um)

        self._mask_drag_start_um = None
        if self._mask_drag_rect_id is not None:
            self.canvas.delete(self._mask_drag_rect_id)
            self._mask_drag_rect_id = None

        # A drag shorter than this is almost certainly an accidental
        # click, not an intended mask -- leave the existing mask
        # untouched rather than silently collapsing it to ~0 width.
        min_width_um = 0.05
        if (right_um - left_um) < min_width_um:
            self.redraw()
            return

        # A drag edits the SELECTED opening (the mask may have several
        # -- see _make_lithography_panel), so write it back through the
        # openings list rather than only into mask_left_um/right_um.
        index = self._selected_opening_index()
        if 0 <= index < len(self.wafer.mask_openings_um):
            self.wafer.mask_openings_um[index] = [left_um, right_um]
            self.wafer.mask_openings_um.sort()
            self._refresh_openings_list(
                select=self.wafer.mask_openings_um.index([left_um, right_um])
            )
        else:
            self.wafer.mask_left_um = left_um
            self.wafer.mask_right_um = right_um
            self.left_var.set(f"{left_um:.3f}")
            self.right_var.set(f"{right_um:.3f}")

        self.redraw()

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

        # Silicon placeholder -- drawn only when we do NOT expect the
        # real-mesh render below (_draw_real_mesh_result(), called
        # later in this function, after the PR/mask litho visuals) to
        # succeed. When a real mesh IS available, its own
        # boundary-traced Si silhouette becomes the solid substrate
        # shape instead -- drawing this flat rectangle unconditionally
        # first, with nothing later clearing it, is what let a real
        # void (e.g. an isotropic-etch undercut) keep showing through
        # as if it were still intact Si. See CLAUDE.md's "GUI:
        # real-mesh render still shows intact Si under an isotropic
        # undercut" for the investigation this fixes.
        real_mesh_available = bool(
            self.wafer.processed
            and self.last_final_mesh
            and Path(self.last_final_mesh).exists()
        )

        if not real_mesh_available:
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
            "pr_coated", "aligned", "exposed", "developed", "etched", "oxidized",
            "deposited",
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

        # Every mask opening in canvas pixels. The mask may pattern
        # several windows (see _make_lithography_panel), so the drawing
        # below iterates this list; opening_x0/opening_x1 remain the
        # SELECTED opening, still used for the single-window labels.
        opening_pixels = [
            (x0 + lo * scale, x0 + hi * scale)
            for lo, hi in sorted(self.wafer.mask_openings_um)
        ] or [(x0, x0)]

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
                # Exposed (soluble) PR under EVERY mask opening.
                for op_x0, op_x1 in opening_pixels:
                    canvas.create_rectangle(
                        op_x0,
                        surface_y - pr_height,
                        op_x1,
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
            # Opaque wherever there is no opening -- drawn as the gaps
            # between consecutive openings, so any number of windows
            # renders correctly.
            edge = x0
            for op_x0, op_x1 in opening_pixels:
                if op_x0 > edge:
                    canvas.create_rectangle(
                        edge,
                        mask_y0,
                        op_x0,
                        surface_y - pr_height,
                        fill="#202020",
                        outline="#111",
                    )
                edge = max(edge, op_x1)
            if edge < x1:
                canvas.create_rectangle(
                    edge,
                    mask_y0,
                    x1,
                    surface_y - pr_height,
                    fill="#202020",
                    outline="#111",
                )

            for op_x0, op_x1 in opening_pixels:
                canvas.create_text(
                    (op_x0 + op_x1) / 2,
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
            # Resist remains everywhere EXCEPT the openings, so draw the
            # gaps between consecutive openings (any number of them).
            edge = x0
            for op_x0, op_x1 in opening_pixels:
                if op_x0 > edge:
                    canvas.create_rectangle(
                        edge,
                        surface_y - pr_height,
                        op_x0,
                        surface_y,
                        fill="#e8a0bd",
                        outline="#803252",
                    )
                edge = max(edge, op_x1)
            if edge < x1:
                canvas.create_rectangle(
                    edge,
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

            for op_x0, op_x1 in opening_pixels:
                canvas.create_text(
                    (op_x0 + op_x1) / 2,
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
        if real_mesh_available:
            if not self._draw_real_mesh_result(canvas, x0, x1, surface_y, bottom_y):
                # real_mesh_available said a mesh file exists, but
                # reading/rendering it failed anyway (meshio missing,
                # corrupt file, ViennaPS unavailable, etc.). The flat
                # rectangle was skipped earlier trusting this call to
                # succeed -- draw it now as a last-resort fallback so
                # the canvas isn't left blank.
                canvas.create_rectangle(
                    x0, surface_y, x1, bottom_y,
                    fill="#bdbdbd", outline="#555",
                )
                canvas.create_text(
                    x0 + 10, bottom_y - 20,
                    text="Si substrate", anchor="w",
                )

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
        self.last_doped_result = None
        self.last_final_mesh = None
        self.history = []
        self.process_stage = "wafer"

        # Both must clear here: completed_steps is what every standalone
        # RUN click now replays (see _chained_flow_config()), so leaving
        # it stale would make NEW WAFER silently keep re-growing the
        # PREVIOUS wafer's geometry underneath whatever gets run next.
        self.flow_steps = []
        self.completed_steps = []
        if hasattr(self, "_refresh_flow_list"):
            self._refresh_flow_list()

        self._activate_stages()

        # The openings listbox is built from self.wafer, so a fresh
        # Wafer() has to be reflected there too -- otherwise NEW WAFER
        # leaves the previous wafer's openings on screen.
        if hasattr(self, "openings_list"):
            self._refresh_openings_list(select=0)

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
