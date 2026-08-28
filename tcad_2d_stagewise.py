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
# DESIGN TOKENS — industrial/scientific EDA look
# ============================================================
#
# GUI-visual only: no value here is read by any process/physics code
# path. A single source of truth so every widget across all panels
# (litho/etch/oxidation/deposition/gate_stack/doping/measurement)
# looks consistent without each one carrying its own style= kwargs --
# none of them do today (verified: no widget in this file passes a
# custom ttk `style=`), so retheming the DEFAULT ttk styles here
# cascades everywhere automatically.
#
# Palette named for what it actually is in a fab, not generic UI
# roles: ACCENT is "cleanroom yellow" -- real fabs light the areas
# where photoresist is handled with yellow light because PR is
# UV-sensitive, so an amber/yellow primary accent is not an arbitrary
# brand color choice here.
class Tokens:
    BG_0 = "#17191C"       # outermost chrome: toolbar, status bar
    BG_1 = "#1D2024"       # panel backgrounds (library, inspector, timeline)
    BG_2 = "#121316"       # recessed fields: canvas, entries, log console
    BG_3 = "#25282D"       # raised elements: buttons, selected rows
    LINE = "#33373D"       # hairline dividers between regions
    LINE_STRONG = "#43474E"
    FG = "#D7D9DC"         # primary text
    FG_MUTED = "#82868C"   # secondary labels, captions, units
    FG_DIM = "#585C62"     # disabled / inactive
    ACCENT = "#E8B23D"     # cleanroom yellow — selection, primary action
    ACCENT_DIM = "#8A6B2E"
    RUN = "#4FB477"        # success / converged / running
    STOP = "#D6524B"       # error / non-convergence / destructive
    FONT_UI = "Segoe UI"
    FONT_DATA = "Consolas"  # parameter values, coordinates, log, timeline


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


def _nice_ruler_step(extent, target_ticks=8):
    """A "nice" (1/2/5 * 10^n) tick spacing for a ruler spanning
    `extent` units, aiming for roughly `target_ticks` labelled ticks.
    GUI-display-only; no relation to any mesh/grid resolution."""
    if extent <= 0:
        return 1.0
    raw = extent / max(1, target_ticks)
    import math
    exponent = math.floor(math.log10(raw))
    base = raw / (10 ** exponent)
    nice = 1.0 if base < 1.5 else 2.0 if base < 3.5 else 5.0 if base < 7.5 else 10.0
    return nice * (10 ** exponent)


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

        if config.get("_strip_resist"):
            # Actually remove resist-derived geometry from the current
            # wafer, not just clear GUI flags. Safe to call whether or
            # not resist ever became real geometry:
            # domain.removeMaterial() on an ABSENT material is a
            # confirmed no-op (measured directly against real ViennaPS
            # 4.6.2 before this was written), and it removes ONLY the
            # material named -- LOCOS's own hard mask stays "Mask",
            # never "PHS" (see TCADApplication._RESIST_MATERIAL), so
            # this can never strip a permanent hard mask by mistake.
            from tcad.backends.viennaps import session as _session
            from tcad.backends.viennaps.io import save_volume_mesh

            domain = _session.load_domain_state(config["_resume_state"])
            module = _session.require_viennaps()
            domain.removeMaterial(getattr(module.Material, config["resist_material"]))
            mesh_path = save_volume_mesh(
                domain,
                str(Path(config["output_dir"]) / "stripped"),
                floor_depth_um=config["silicon_depth_um"],
            )
            state_path = str(Path(config["output_dir"]) / "domain_state.vpsd")
            _session.save_domain_state(domain, state_path)
            payload = {
                "success": True,
                "final_mesh": mesh_path,
                "domain_state": state_path,
            }

        elif config.get("_materialize_wafer"):
            # Export the wafer AS IT IS, running no process at all.
            #
            # A wafer exists from the moment it is created, so a step
            # that needs a mesh (doping attaches its profile to one)
            # must not be gated behind "run some other process first" —
            # that would be a prerequisite, and the user chooses the
            # order. This gives that step the current wafer's real
            # geometry instead.
            from tcad.backends.viennaps import session as _session
            from tcad.backends.viennaps.io import save_volume_mesh

            domain = _session.make_mask_spans(
                grid_delta_um=config["grid_delta_um"],
                x_extent_um=config["x_extent_um"],
                y_extent_um=config["y_extent_um"],
                spans_um=[tuple(span) for span in config.get("mask_spans_um") or []],
                mask_height_um=max(config.get("pr_thickness_um", 0.0), 0.1),
                substrate_depth_um=config["silicon_depth_um"] + 1.0,
            )
            mesh_path = save_volume_mesh(
                domain,
                str(Path(config["output_dir"]) / "wafer"),
                floor_depth_um=config["silicon_depth_um"],
            )
            state_path = str(Path(config["output_dir"]) / "domain_state.vpsd")
            _session.save_domain_state(domain, state_path)
            payload = {
                "success": True,
                "final_mesh": mesh_path,
                "domain_state": state_path,
                "step_count": 0,
                "step_meshes": [],
            }

        elif config.get("_flow_steps"):
            # A user-composed process FLOW: several steps, in whatever
            # order the user queued them, each continuing from the
            # previous step's real geometry via
            # ProcessStep(inherited_domain=...). run_flow is the Phase
            # 13/14 machinery this project already verified; the GUI
            # simply had no way in until now.
            from tcad.process.flow import FlowStep, run_flow

            # Resume the real accumulated wafer instead of rebuilding it.
            # Each GUI RUN click is its own subprocess, so a live domain
            # cannot be held between clicks; without this the GUI had to
            # re-run its ENTIRE history every click to get back to the
            # current geometry (O(N^2), and it re-paid for the slowest
            # step forever). The .vpsd written by the previous click
            # carries that geometry directly.
            initial_domain = None
            resume_state = config.get("_resume_state")
            if resume_state:
                from tcad.backends.viennaps import session as _session

                initial_domain = _session.load_domain_state(resume_state)

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
                initial_domain=initial_domain,
            )
            # The LAST step's mesh is the finished device -- that is what
            # doping and device measurement consume. step_meshes carries
            # every INTERMEDIATE step's own mesh too (GUI-display only --
            # run_flow already computed and exported all of them; this
            # just serializes what was already there, so the Process
            # Flow Timeline can show any step's geometry on click,
            # instead of only the final one).
            payload = {
                "success": True,
                "final_mesh": results[-1].volume_mesh_path,
                "step_count": len(results),
                "step_meshes": [r.volume_mesh_path for r in results],
                # The wafer's accumulated state, for the NEXT click to
                # resume from (see "_resume_state" above).
                "domain_state": results[-1].domain_state_path,
                # Physics status and the numerical (under-resolved)
                # warning are separate axes and stay separate all the
                # way to the GUI. Plain JSON only: this crosses a
                # subprocess boundary.
                "physics_status": results[-1].physics_status,
                "numerical_status": results[-1].numerical_status,
                # Every step's own status, same order as step_meshes --
                # results[-1] above only carries the LAST step's, so a
                # non-final step's real status (e.g. an etch wired to
                # the resolver, followed by a step that is not) would
                # otherwise be silently dropped.
                "step_physics_status": [r.physics_status for r in results],
                "step_numerical_status": [r.numerical_status for r in results],
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

        # Vertical view budget for _draw_real_mesh_result, keyed
        # "above"/"below" -- see _quantized_depth_budget()'s own
        # docstring for why this exists (renderer-only fix for the
        # "long deposition erodes the substrate" illusion; the real
        # mesh does not erode -- see docs/investigation_log.md,
        # "Deposition: renderer y-scale artifact"). Reset on NEW WAFER.
        self._viewer_depth_budget_um = {}

        # The ProcessResult (with DopingProfile attached) from the last
        # successful run_doping(), consumed by run_measurement() -- see
        # _make_measurement_panel()'s own docstring. None until doping
        # succeeds.
        self.last_doped_result = None

        # Electrode/Pin system (see tcad.mesh.pin.Pin) -- separate from
        # the existing 2-terminal _make_measurement_panel's own
        # region-extreme-only pins. None until resolve_electrode_pins()
        # succeeds against a real mesh.
        self.electrode_pins = []
        self.last_electrode_import = None
        self._electrode_contact_regions = {}

        # Each category panel's LabelFrame, registered as it is built,
        # so the category selector can show exactly one at a time (see
        # _show_panel_category).
        self._panel_frames = {}

        # Which category's panel is currently shown in the Parameter
        # Inspector (right column) -- holds a _PANEL_LABELS[...] display
        # string, read by _show_panel_category()/add_current_step_to_flow().
        # Created here (not in _make_control_panel, where it used to be
        # created) because the Process Library tree's default selection
        # (_make_process_panel, built first) fires <<TreeviewSelect>>
        # synchronously and needs this to already exist.
        self.panel_category = tk.StringVar(value=self._PANEL_LABELS["oxidation"])

        # Per-flow-step result mesh paths, populated after a real
        # RUN PROCESS FLOW (see run_process_flow / worker_main's
        # "_flow_steps" branch) so the bottom timeline can show any
        # step's own geometry on click, not just the final one.
        self.flow_step_meshes = []

        # Which completed step's geometry the viewer currently shows --
        # None means "the real current wafer" (self.last_final_mesh);
        # an index into flow_step_meshes means the user clicked that
        # timeline chip (see _view_flow_step). Initialized here (not in
        # _make_flow_panel, which builds the timeline that sets it)
        # because redraw() can run earlier, during _make_control_panel's
        # own construction (_make_lithography_panel's initial
        # _refresh_openings_list() -> _on_opening_selected() -> redraw()).
        self._viewing_step_index = None

        # Per-x real-current-top-surface lookup, rebuilt by
        # _draw_real_mesh_result() on every successful real-mesh render
        # (see its own comment). Defaults to "the y=0 datum everywhere"
        # so redraw()'s PR overlay has something safe to call before any
        # real mesh has ever been drawn, or if a real-mesh draw attempt
        # fails partway (meshio missing, corrupt file, etc.) -- rather
        # than reading a stale lookup from a DIFFERENT, no-longer-
        # current mesh, or crashing on a missing attribute.
        self._real_mesh_top_um = lambda x_um: 0.0

        # The .vpsd holding the wafer's ACCUMULATED geometry, written by
        # the last successful run. The next RUN click resumes from this
        # instead of re-running the whole history to rebuild it -- see
        # _chained_flow_config(). None until a step succeeds, and reset
        # by NEW WAFER.
        self.last_domain_state = None
        # Whatever the most recent step reported about its own physics
        # knowledge (Resolution/Provenance) and mesh resolution. None
        # until a step succeeds; nothing produces a real value yet.
        self.last_physics_status = None

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

        # SESSION STATE markers actually reached, accumulated by
        # _mark_stage_done(). Stage 0 ("Si wafer") is true from the
        # moment a wafer exists, which is now.
        self._stages_done = {0}

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
        """Global ttk theme -- industrial/scientific EDA look.

        Configures the DEFAULT style of every ttk widget class
        (TFrame, TLabel, TButton, ...), not named per-widget styles, so
        every existing panel (none of which pass a custom `style=`
        kwarg -- confirmed by grep across this file) picks this up
        automatically. A few named variants (Accent/Run/Danger.TButton,
        Header/Section/Mono/Caption.TLabel, Toolbar/Inspector/Canvas
        .TFrame) exist for the specific spots that need to stand out
        from the base look; everything else inherits the base.
        """
        T = Tokens
        self.configure(bg=T.BG_0)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=T.BG_1, foreground=T.FG,
                        font=(T.FONT_UI, 9), bordercolor=T.LINE,
                        darkcolor=T.BG_1, lightcolor=T.BG_1,
                        troughcolor=T.BG_2, focuscolor=T.ACCENT)

        style.configure("TFrame", background=T.BG_1)
        style.configure("TLabel", background=T.BG_1, foreground=T.FG)
        style.configure("TLabelframe", background=T.BG_1, bordercolor=T.LINE,
                        relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=T.BG_1,
                        foreground=T.FG_MUTED, font=(T.FONT_UI, 9, "bold"))
        style.configure("TSeparator", background=T.LINE)

        style.configure("TButton", background=T.BG_3, foreground=T.FG,
                        bordercolor=T.LINE_STRONG, relief="flat",
                        font=(T.FONT_UI, 9), padding=(8, 5))
        style.map("TButton",
                   background=[("active", T.LINE_STRONG), ("disabled", T.BG_1)],
                   foreground=[("disabled", T.FG_DIM)])

        style.configure("TEntry", fieldbackground=T.BG_2, foreground=T.FG,
                        insertcolor=T.ACCENT, bordercolor=T.LINE,
                        font=(T.FONT_DATA, 9), padding=4)
        style.map("TEntry", fieldbackground=[("disabled", T.BG_1)])

        style.configure("TCombobox", fieldbackground=T.BG_2, background=T.BG_3,
                        foreground=T.FG, arrowcolor=T.FG_MUTED,
                        bordercolor=T.LINE, font=(T.FONT_DATA, 9), padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", T.BG_2)],
                   foreground=[("readonly", T.FG)])
        self.option_add("*TCombobox*Listbox.background", T.BG_2)
        self.option_add("*TCombobox*Listbox.foreground", T.FG)
        self.option_add("*TCombobox*Listbox.selectBackground", T.ACCENT_DIM)
        self.option_add("*TCombobox*Listbox.font", (T.FONT_DATA, 9))

        style.configure("TScrollbar", background=T.BG_3, troughcolor=T.BG_1,
                        bordercolor=T.BG_1, arrowcolor=T.FG_MUTED)

        style.configure("Treeview", background=T.BG_1, fieldbackground=T.BG_1,
                        foreground=T.FG, bordercolor=T.LINE, relief="flat",
                        font=(T.FONT_UI, 9), rowheight=26)
        style.map("Treeview",
                   background=[("selected", T.ACCENT_DIM)],
                   foreground=[("selected", "#111111")])
        style.configure("Treeview.Heading", background=T.BG_0,
                        foreground=T.FG_MUTED, relief="flat",
                        font=(T.FONT_UI, 8, "bold"))
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        # --- named variants for spots that must stand apart -----------
        style.configure("Toolbar.TFrame", background=T.BG_0)
        style.configure("Inspector.TFrame", background=T.BG_1)
        style.configure("Canvas.TFrame", background=T.BG_2)
        style.configure("Status.TFrame", background=T.BG_0)

        style.configure("Header.TLabel", background=T.BG_0, foreground=T.FG,
                        font=(T.FONT_UI, 14, "bold"))
        style.configure("SubHeader.TLabel", background=T.BG_0,
                        foreground=T.FG_MUTED, font=(T.FONT_UI, 9))
        style.configure("Section.TLabel", background=T.BG_1,
                        foreground=T.FG_MUTED,
                        font=(T.FONT_UI, 8, "bold"))
        style.configure("Mono.TLabel", background=T.BG_1, foreground=T.FG,
                        font=(T.FONT_DATA, 9))
        style.configure("Caption.TLabel", background=T.BG_1,
                        foreground=T.FG_MUTED, font=(T.FONT_UI, 8))
        style.configure("Unit.TLabel", background=T.BG_1,
                        foreground=T.FG_DIM, font=(T.FONT_DATA, 8))
        style.configure("StatusText.TLabel", background=T.BG_0,
                        foreground=T.FG_MUTED, font=(T.FONT_DATA, 8))

        style.configure("Accent.TButton", background=T.ACCENT,
                        foreground="#1A1400", font=(T.FONT_UI, 9, "bold"),
                        bordercolor=T.ACCENT, padding=(10, 6))
        style.map("Accent.TButton",
                   background=[("active", "#F2C05C"), ("disabled", T.BG_3)],
                   foreground=[("disabled", T.FG_DIM)])

        style.configure("Run.TButton", background=T.RUN, foreground="#0C1F14",
                        font=(T.FONT_UI, 9, "bold"), bordercolor=T.RUN,
                        padding=(10, 6))
        style.map("Run.TButton",
                   background=[("active", "#63CC8E"), ("disabled", T.BG_3)],
                   foreground=[("disabled", T.FG_DIM)])

        style.configure("Danger.TButton", background=T.BG_1,
                        foreground=T.STOP, bordercolor=T.STOP,
                        font=(T.FONT_UI, 9), padding=(10, 6))
        style.map("Danger.TButton",
                   background=[("active", "#3A1F1E"), ("disabled", T.BG_1)],
                   foreground=[("disabled", T.FG_DIM)])

        style.configure("Toolbar.TButton", background=T.BG_0,
                        foreground=T.FG_MUTED, bordercolor=T.BG_0,
                        relief="flat", font=(T.FONT_UI, 9), padding=(9, 5))
        style.map("Toolbar.TButton",
                   background=[("active", T.BG_1)],
                   foreground=[("active", T.FG), ("disabled", T.FG_DIM)])

        # Viewer layer switch (GEOMETRY/DOPING/POTENTIAL/...): a
        # Radiobutton group styled as a flat tab strip, not a checkbox
        # list -- the ttk "selected" state (which tab is active) is what
        # distinguishes it from a plain Toolbar.TButton, so it needs its
        # own style+layout rather than reusing that one.
        style.layout("LayerTab.TButton", style.layout("TButton"))
        style.configure("LayerTab.TButton", background=T.BG_1,
                        foreground=T.FG_MUTED, bordercolor=T.LINE,
                        relief="flat", font=(T.FONT_UI, 8, "bold"),
                        padding=(8, 4))
        style.map("LayerTab.TButton",
                   background=[("selected", T.ACCENT), ("active", T.BG_3)],
                   foreground=[("selected", "#1A1400"), ("active", T.FG)])

        # Same flat-toggle idea as LayerTab.TButton, but on the toolbar's
        # own (darker) background -- used for MESH, the one checkbox-style
        # toggle living in the top toolbar rather than the viewer strip.
        style.layout("ToolbarToggle.TButton", style.layout("TButton"))
        style.configure("ToolbarToggle.TButton", background=T.BG_0,
                        foreground=T.FG_MUTED, bordercolor=T.BG_0,
                        relief="flat", font=(T.FONT_UI, 9), padding=(9, 5))
        style.map("ToolbarToggle.TButton",
                   background=[("selected", T.ACCENT), ("active", T.BG_1)],
                   foreground=[("selected", "#1A1400"), ("active", T.FG)])

        self._toolbar_frame_style = "Toolbar.TFrame"

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    def _make_header(self):
        T = Tokens
        header = ttk.Frame(self, style="Toolbar.TFrame", padding=(14, 9))
        header.pack(fill="x")

        # --- brand block --------------------------------------------
        brand = ttk.Frame(header, style="Toolbar.TFrame")
        brand.pack(side="left")
        ttk.Label(brand, text="TCAD", style="Header.TLabel").pack(side="left")
        ttk.Label(brand, text="2D", style="Header.TLabel",
                  foreground=T.ACCENT).pack(side="left", padx=(4, 0))
        ttk.Label(brand, text="   PROCESS → MESH → DEVICE",
                  style="SubHeader.TLabel").pack(side="left", padx=(6, 0))

        def _vsep(parent):
            ttk.Separator(parent, orient="vertical").pack(
                side="left", fill="y", padx=14, pady=2)

        _vsep(header)

        # --- PROJECT group --------------------------------------------
        project = ttk.Frame(header, style="Toolbar.TFrame")
        project.pack(side="left")
        ttk.Label(project, text="PROJECT", style="Caption.TLabel").pack(
            side="left", padx=(0, 6))
        ttk.Button(project, text="NEW", style="Toolbar.TButton",
                   command=self.reset).pack(side="left")
        ttk.Button(project, text="SAVE", style="Toolbar.TButton",
                   command=self.save_project).pack(side="left")
        ttk.Button(project, text="LOAD", style="Toolbar.TButton",
                   command=self.load_project).pack(side="left")

        _vsep(header)

        # --- RUN group --------------------------------------------------
        # Aliases onto the SAME handlers the bottom Process Flow Timeline's
        # own buttons use (run_process_flow / run_measurement) -- no new
        # execution path, just a toolbar shortcut to it.
        run_group = ttk.Frame(header, style="Toolbar.TFrame")
        run_group.pack(side="left")
        ttk.Label(run_group, text="RUN", style="Caption.TLabel").pack(
            side="left", padx=(0, 6))
        self.toolbar_run_button = ttk.Button(
            run_group, text="▶ FLOW", style="Run.TButton",
            command=self.run_process_flow,
        )
        self.toolbar_run_button.pack(side="left")
        ttk.Button(run_group, text="SOLVE", style="Toolbar.TButton",
                   command=self.run_measurement).pack(side="left", padx=(4, 0))
        self.toolbar_stop_button = ttk.Button(
            run_group, text="■ STOP", style="Danger.TButton",
            state="disabled",
        )
        self.toolbar_stop_button.pack(side="left", padx=(4, 0))
        # Execution today is a single blocking subprocess.run() call
        # (run_process_flow / worker_main) with no cancellation hook --
        # making STOP real needs a non-blocking execution model, which is
        # an execution-architecture change, not a visual one. The button
        # stays visible (so the control surface reads as complete) and
        # disabled (so it never lies about what it can do); hovering
        # explains why, in the same status bar every other hint uses.
        for seq, text in (
            ("<Enter>", "STOP is disabled: runs execute synchronously "
                        "today and cannot be cancelled mid-solve."),
            ("<Leave>", "Ready"),
        ):
            self.toolbar_stop_button.bind(
                seq, lambda _e, t=text: self.status_var.set(t))

        _vsep(header)

        # --- MESH overlay toggle ----------------------------------------
        # A view-only overlay (draw the real triangle edges on top of the
        # material fill), independent of which layer (Geometry/Doping/...)
        # is selected in the viewer's own layer strip -- see
        # _make_cross_section. Purely additive to redraw()/
        # _draw_real_mesh_result; no mesh DATA is changed by toggling it.
        self.mesh_overlay_var = tk.BooleanVar(value=False)
        mesh_btn = ttk.Checkbutton(
            header, text="MESH", variable=self.mesh_overlay_var,
            style="ToolbarToggle.TButton", command=self.redraw,
        )
        mesh_btn.pack(side="left")

        # --- status (right) ----------------------------------------------
        backend = ("VIENNAPS READY" if viennaps_session.is_available()
                   else "VIENNAPS NOT INSTALLED")
        ttk.Label(header, text=backend,
                  foreground=T.RUN if viennaps_session.is_available() else T.STOP,
                  background=T.BG_0, font=(T.FONT_UI, 9, "bold"),
                  ).pack(side="right")

        from tcad.device.devsim import backend as _devsim_backend
        devsim_ready = _devsim_backend.is_available()
        ttk.Label(header, text=("DEVSIM READY" if devsim_ready
                                 else "DEVSIM NOT INSTALLED"),
                  foreground=T.RUN if devsim_ready else T.FG_DIM,
                  background=T.BG_0, font=(T.FONT_UI, 9, "bold"),
                  ).pack(side="right", padx=(0, 16))

    # --------------------------------------------------------
    # STATUS BAR
    # --------------------------------------------------------

    def _make_status(self):
        T = Tokens
        self.status_var = tk.StringVar(value="Ready")
        bar = ttk.Frame(self, style="Status.TFrame", padding=(10, 3))
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status_var, style="StatusText.TLabel",
                  anchor="w").pack(side="left", fill="x", expand=True)
        ttk.Label(bar, text="TCAD 2D · REAL PROCESS FLOW · V2",
                  style="StatusText.TLabel").pack(side="right")

    # --------------------------------------------------------
    # BODY
    # --------------------------------------------------------

    def _make_body(self):
        T = Tokens
        # Vertical split: main 3-column work area on top, Process Flow
        # Timeline + Log console docked at the bottom -- the same
        # arrangement a layout/schematic EDA tool uses (canvas + tool
        # panels above a persistent bottom console dock).
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        main = ttk.Frame(outer)
        main.pack(fill="both", expand=True)

        self._make_process_panel(main)
        self._make_cross_section(main)
        self._make_control_panel(main)

        ttk.Separator(outer).pack(fill="x")

        dock = ttk.Frame(outer, style="Inspector.TFrame")
        dock.pack(fill="x", side="bottom")
        self._make_flow_panel(dock)
        self._make_log_panel(dock)

    # --------------------------------------------------------
    # PROCESS LIBRARY (left column)
    # --------------------------------------------------------

    #: (group label, key) -- key matches self._panel_frames / _PANEL_LABELS,
    #: set by each _make_*_panel as it builds its own LabelFrame. Grouped
    #: the way a real process library is organized: steps that build
    #: geometry, then the steps that turn geometry into a measurable
    #: device, then the one structural shortcut (gate_stack) that stands
    #: apart from the rest (see gate_stack.py -- it is intentionally
    #: terminal and does not chain like the others).
    _LIBRARY_GROUPS = (
        ("PROCESS", ("oxidation", "litho", "etch", "deposition",
                     "metallization")),
        ("DEVICE", ("doping", "measurement", "electrodes")),
        ("STRUCTURES", ("gate_stack",)),
    )

    def _make_process_panel(self, parent):
        T = Tokens
        panel = ttk.Frame(parent, style="Inspector.TFrame", width=230)
        panel.pack(side="left", fill="y")
        panel.pack_propagate(False)

        # --- session state: the litho micro-step checklist -------------
        # Kept from the previous single-column layout -- it tracks real
        # process_stage progress (see _activate_stages, called from
        # process_pr_coat/run_etch/... throughout this file) and is not
        # itself a navigation control, so it sits above the Process
        # Library tree rather than inside it.
        state_box = ttk.Frame(panel, style="Inspector.TFrame", padding=(10, 10, 10, 4))
        state_box.pack(fill="x")
        ttk.Label(state_box, text="SESSION STATE", style="Section.TLabel").pack(anchor="w")

        stages = [
            "Si wafer", "Film / oxide", "PR coat", "Mask alignment",
            "Exposure", "Develop", "Etch", "PR strip",
        ]
        self.stage_labels = []
        for index, name in enumerate(stages):
            label = ttk.Label(
                state_box, text=f"○ {index + 1:02d}  {name}",
                style="Caption.TLabel", padding=(2, 2),
            )
            label.pack(anchor="w")
            self.stage_labels.append(label)

        ttk.Separator(panel).pack(fill="x", pady=(6, 0))

        # --- Process Library tree ---------------------------------------
        lib_box = ttk.Frame(panel, style="Inspector.TFrame", padding=(10, 8, 10, 10))
        lib_box.pack(fill="both", expand=True)
        ttk.Label(lib_box, text="PROCESS LIBRARY", style="Section.TLabel").pack(anchor="w")

        tree = ttk.Treeview(lib_box, show="tree", selectmode="browse", height=14)
        tree.pack(fill="both", expand=True, pady=(4, 0))
        self.library_tree = tree

        self._library_tree_keys = {}
        for group_label, keys in self._LIBRARY_GROUPS:
            group_id = tree.insert("", "end", text=group_label, open=True, tags=("group",))
            for key in keys:
                item_id = tree.insert(group_id, "end", text=self._PANEL_LABELS[key])
                self._library_tree_keys[item_id] = key
        tree.tag_configure("group", foreground=T.FG_DIM)

        def _on_tree_select(_event=None):
            selection = tree.selection()
            if not selection:
                return
            key = self._library_tree_keys.get(selection[0])
            if key is None:
                return  # a group header, not a selectable category
            self.panel_category.set(self._PANEL_LABELS[key])
            self._show_panel_category()

        tree.bind("<<TreeviewSelect>>", _on_tree_select)

        # Select the first real category by default (matches the old
        # Combobox's initial value, "litho").
        first_leaf = next(iter(self._library_tree_keys))
        tree.selection_set(first_leaf)

    # --------------------------------------------------------
    # CROSS SECTION (center viewer)
    # --------------------------------------------------------

    #: Visualization layers for the center viewer. "geometry" and
    #: "doping" read data this GUI already has on hand (the real mesh /
    #: self.last_doped_result). "potential"/"electron"/"hole" need
    #: node-level DevSim field data the measurement worker does not
    #: serialize back today (only terminal currents) -- the toggle exists
    #: so the surface is complete, but shows an honest placeholder rather
    #: than fabricated field data until that plumbing exists.
    _VIEWER_LAYERS = ("geometry", "doping", "potential", "electron", "hole")
    _VIEWER_LAYER_LABELS = {
        "geometry": "GEOMETRY", "doping": "DOPING", "potential": "POTENTIAL",
        "electron": "ELECTRON", "hole": "HOLE",
    }

    def _make_cross_section(self, parent):
        T = Tokens
        frame = ttk.Frame(parent, style="Inspector.TFrame")
        frame.pack(side="left", fill="both", expand=True, padx=1)

        # --- viewer toolbar: title + layer switch ------------------------
        vtool = ttk.Frame(frame, style="Inspector.TFrame", padding=(10, 6))
        vtool.pack(fill="x")
        ttk.Label(vtool, text="2D STRUCTURE / PROCESS VIEWER",
                  style="Section.TLabel").pack(side="left")

        layer_box = ttk.Frame(vtool, style="Inspector.TFrame")
        layer_box.pack(side="right")
        self.viewer_layer_var = tk.StringVar(value="geometry")
        self._layer_buttons = {}
        for layer in self._VIEWER_LAYERS:
            btn = ttk.Radiobutton(
                layer_box, text=self._VIEWER_LAYER_LABELS[layer],
                value=layer, variable=self.viewer_layer_var,
                style="LayerTab.TButton",
                command=self.redraw,
            )
            btn.pack(side="left", padx=(0, 2))
            self._layer_buttons[layer] = btn

        ttk.Separator(frame).pack(fill="x")

        # --- canvas --------------------------------------------------------
        canvas_host = ttk.Frame(frame, style="Canvas.TFrame", padding=1)
        canvas_host.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        self.canvas = tk.Canvas(
            canvas_host, bg=T.BG_2, highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Configure>", lambda event: self.redraw())

        self._mask_drag_start_um = None
        self._mask_drag_rect_id = None

        self.canvas.bind("<ButtonPress-1>", self._on_mask_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_mask_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_mask_drag_end)

        # Live cursor coordinate readout -- the signature element: this
        # domain is measured in microns, so a coordinate readout is what
        # makes the viewer read as an instrument rather than a picture.
        # Purely a display of the SAME x0/x1/surface_y/scale redraw()
        # already computes each frame; stored on self so the motion
        # handler (bound once, here) can reach the latest values without
        # redraw() needing to know this readout exists.
        self._viewer_scale = None  # set by redraw(): (x0, x_min, x_scale, surface_y, y_scale)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", lambda _e: self.coord_var.set(""))

        # --- coordinate / legend strip -------------------------------------
        readout = ttk.Frame(frame, style="Canvas.TFrame", padding=(10, 3))
        readout.pack(fill="x", padx=10, pady=(0, 8))
        self.coord_var = tk.StringVar(value="")
        ttk.Label(readout, textvariable=self.coord_var, style="Mono.TLabel",
                  background=T.BG_2).pack(side="left")
        self.legend_frame = ttk.Frame(readout, style="Canvas.TFrame")
        self.legend_frame.pack(side="right")
        # Static swatches from the single _MATERIAL_COLORS source of
        # truth _draw_real_mesh_result() also fills from -- built once,
        # not per-redraw, since the palette itself never changes.
        for name, color in self._MATERIAL_COLORS.items():
            chip = tk.Frame(self.legend_frame, width=10, height=10, bg=color,
                             highlightthickness=1, highlightbackground=T.LINE_STRONG)
            chip.pack(side="left", padx=(8, 2))
            chip.pack_propagate(False)
            ttk.Label(self.legend_frame, text=name, style="Caption.TLabel",
                      background=T.BG_2).pack(side="left")

    def _on_canvas_motion(self, event):
        """Update the live X/Y (um) readout from the last scale redraw()
        computed. GUI-only -- reads canvas pixel coords back through the
        same linear map redraw() used, no new geometry math."""
        if not self._viewer_scale:
            self.coord_var.set("")
            return
        x0, x_min, x_scale, surface_y, y_scale = self._viewer_scale
        if not x_scale or not y_scale:
            self.coord_var.set("")
            return
        x_um = x_min + (event.x - x0) / x_scale
        y_um = (surface_y - event.y) / y_scale
        self.coord_var.set(f"X {x_um:+8.3f} µm   Y {y_um:+8.3f} µm")

    # --------------------------------------------------------
    # CONTROL PANEL
    # --------------------------------------------------------

    #: Category selector contents. Keys match self._panel_frames, set
    #: by each _make_*_panel as it builds its own LabelFrame.
    _PANEL_ORDER = (
        "oxidation",
        "litho",
        "etch",
        "deposition",
        "metallization",
        "doping",
        "gate_stack",
        "measurement",
        "electrodes",
    )
    _PANEL_LABELS = {
        "oxidation": "Oxidation",
        "litho": "Lithography",
        "etch": "Etching",
        "deposition": "Deposition",
        "metallization": "Metallization",
        "doping": "Doping",
        "gate_stack": "Geometry (MOSFET gate stack)",
        "measurement": "Device measurement",
        "electrodes": "Electrodes (pin placement)",
    }

    #: Single source of truth for material -> canvas color, shared by
    #: _draw_real_mesh_result() (the fill) and _make_cross_section()'s
    #: legend swatches (built once from this same dict), so they cannot
    #: drift apart. Loosely follows real IC-layout layer-color
    #: convention (diffusion greens/tans, poly red-orange, oxide blue,
    #: metals distinct saturated hues) re-tuned to sit on a dark canvas,
    #: not a literal reproduction of any one tool's palette.
    _MATERIAL_COLORS = {
        "Si": "#8A8F98",
        "Mask": Tokens.ACCENT,       # cleanroom-yellow PR -- see Tokens' own docstring
        "SiO2": "#5B8DBE",
        "Polymer": "#C98A3D",
        "PolySi": "#C1503F",         # real-fab poly convention: red/orange
        "TiN": "#8B6BC9",
        "W": "#D6A23D",
        "Cu": "#C0632E",
        "PHS": "#e8a0bd",         # photoresist -- same pink as the litho placeholder, see _RESIST_MATERIAL
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
        T = Tokens
        frame = ttk.Frame(parent, style="Inspector.TFrame", padding=(10, 6))
        frame.pack(fill="x")

        ttk.Label(frame, text="PROCESS FLOW TIMELINE", style="Section.TLabel").pack(anchor="w")

        # --- row 1: completed steps, as clickable chips -------------------
        # Each chip shows that step's REAL geometry (its own exported
        # mesh, see run_process_flow/run_etch/etc. populating
        # self.flow_step_meshes alongside self.completed_steps) when
        # clicked, instead of always showing only the latest state.
        self.timeline_canvas = tk.Canvas(
            frame, height=44, bg=T.BG_1, highlightthickness=0,
        )
        self.timeline_canvas.pack(fill="x", pady=(4, 6))
        self._timeline_chip_hits = []  # [(x0, x1, step_index), ...]
        self.timeline_canvas.bind("<Button-1>", self._on_timeline_click)

        ttk.Separator(frame).pack(fill="x", pady=(0, 6))

        # --- row 2: queued (not yet run) steps + reorder/run controls ----
        queue_row = ttk.Frame(frame, style="Inspector.TFrame")
        queue_row.pack(fill="x")

        queue_left = ttk.Frame(queue_row, style="Inspector.TFrame")
        queue_left.pack(side="left", fill="both", expand=True)
        ttk.Label(queue_left, text="Queued (ADD TO FLOW to append; runs top "
                                     "to bottom, each continuing from the "
                                     "previous geometry):",
                  style="Caption.TLabel").pack(anchor="w")

        list_row = ttk.Frame(queue_left, style="Inspector.TFrame")
        list_row.pack(fill="x", pady=(2, 0))
        self.flow_list = tk.Listbox(
            list_row, height=3, exportselection=False,
            bg=T.BG_2, fg=T.FG, selectbackground=T.ACCENT_DIM,
            selectforeground="#1A1400", highlightthickness=1,
            highlightbackground=T.LINE, relief="flat",
            font=(T.FONT_DATA, 9),
        )
        self.flow_list.pack(side="left", fill="both", expand=True)

        btn_col = ttk.Frame(queue_row, style="Inspector.TFrame")
        btn_col.pack(side="left", padx=(8, 0))
        row1 = ttk.Frame(btn_col, style="Inspector.TFrame")
        row1.pack(fill="x")
        for text, command in (
            ("↑", lambda: self._move_flow_step(-1)),
            ("↓", lambda: self._move_flow_step(1)),
            ("Remove", self.remove_flow_step),
            ("Clear", self.clear_flow),
        ):
            ttk.Button(row1, text=text, style="Toolbar.TButton",
                       command=command).pack(side="left", padx=(0, 3))

        self.run_flow_button = ttk.Button(
            btn_col, text="▶ RUN PROCESS FLOW", style="Run.TButton",
            command=self.run_process_flow,
        )
        self.run_flow_button.pack(fill="x", pady=(4, 0))

        self._refresh_flow_list()
        self._refresh_completed_timeline()

    def _timeline_chip_label(self, index, recipe):
        category = recipe.get("_process_category", "?")
        model = recipe.get("_process_model_key", "?")
        return f"{index + 1:02d}  {category}/{model}"

    def _refresh_completed_timeline(self):
        """Redraw the completed-steps chip strip from
        self.completed_steps / self.flow_step_meshes. Read-only view of
        already-computed state -- draws nothing that wasn't already
        produced by a real run_flow()/ProcessStep.run() call."""
        if not hasattr(self, "timeline_canvas"):
            return
        T = Tokens
        canvas = self.timeline_canvas
        canvas.delete("all")
        self._timeline_chip_hits = []

        if not self.completed_steps:
            canvas.create_text(
                10, 22, anchor="w", fill=T.FG_DIM, font=(T.FONT_UI, 9),
                text="No steps run yet — build a recipe on the right and "
                     "press RUN, or queue steps below and RUN PROCESS FLOW.",
            )
            return

        x = 10
        for index, recipe in enumerate(self.completed_steps):
            label = self._timeline_chip_label(index, recipe)
            text_w = 8 * len(label) + 20
            x1 = x + text_w
            viewing = self._viewing_step_index == index
            fill = T.ACCENT if viewing else T.BG_3
            outline = T.ACCENT if viewing else T.LINE_STRONG
            text_color = "#1A1400" if viewing else T.FG
            canvas.create_rectangle(x, 8, x1, 36, fill=fill, outline=outline)
            canvas.create_text(
                (x + x1) / 2, 22, text=label, fill=text_color,
                font=(T.FONT_DATA, 9),
            )
            self._timeline_chip_hits.append((x, x1, index))
            x = x1 + 6
            if index < len(self.completed_steps) - 1:
                canvas.create_text(x, 22, text="→", fill=T.FG_DIM,
                                    font=(T.FONT_UI, 10))
                x += 16

        # "LIVE" chip: return to the actual latest state (self.last_final_mesh)
        # after having clicked back to view an earlier step.
        live_fill = T.RUN if self._viewing_step_index is None else T.BG_3
        live_outline = T.RUN if self._viewing_step_index is None else T.LINE_STRONG
        x1 = x + 60
        canvas.create_rectangle(x, 8, x1, 36, fill=live_fill, outline=live_outline)
        canvas.create_text((x + x1) / 2, 22, text="LIVE",
                            fill="#0C1F14" if self._viewing_step_index is None else T.FG,
                            font=(T.FONT_DATA, 9, "bold"))
        self._timeline_chip_hits.append((x, x1, "live"))

    def _on_timeline_click(self, event):
        for x0, x1, target in self._timeline_chip_hits:
            if x0 <= event.x <= x1:
                self._view_flow_step(target)
                return

    def _view_flow_step(self, target):
        """Show a specific completed step's own real geometry in the
        viewer (target = an index into self.completed_steps), or
        "live" to return to the actual latest state
        (self.last_final_mesh, the real current wafer). Display-only:
        does not re-run anything or change process state -- the same
        mesh files run_flow already exported are just read again.
        """
        if target == "live":
            self._viewing_step_index = None
        elif 0 <= target < len(self.flow_step_meshes):
            self._viewing_step_index = target
        else:
            return  # no mesh recorded for this step (older payload) -- ignore
        self._refresh_completed_timeline()
        self.redraw()

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
        #
        # `all_steps` stays the wafer's full HISTORY (what gets recorded
        # and shown in the timeline). What actually RUNS is decided the
        # same way a standalone click decides it: resume the accumulated
        # .vpsd and run only the queued steps, or replay everything when
        # resuming is not available -- see _chained_flow_config().
        all_steps = self.completed_steps + self.flow_steps
        state = self.last_domain_state
        can_resume = (
            state and Path(state).exists() and not self._locos_in_history()
        )

        output_dir = tempfile.mkdtemp(prefix="tcad2d_flow_")
        config_file = Path(output_dir) / "flow.json"
        result_file = Path(output_dir) / "result.json"

        config_file.write_text(
            json.dumps(
                (
                    {
                        "_flow_steps": self.flow_steps,
                        "_resume_state": state,
                        "output_dir": output_dir,
                    }
                    if can_resume
                    else {"_flow_steps": all_steps, "output_dir": output_dir}
                ),
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
        # `etched` means "this wafer has actually been etched" -- it
        # gates the trench-opening placeholder in redraw(). Setting it
        # for ANY completed flow claimed an etch that a flow of, say,
        # oxidation + deposition never performed.
        if any(step.get("_process_category") == "etching" for step in all_steps):
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
        self.last_domain_state = result.get("domain_state")
        self.last_physics_status = result.get("physics_status")
        self._log_physics_status(result)
        # The above logs only the LAST step's status. A multi-step flow
        # can have earlier steps with their own real status (e.g. an
        # etch wired to the resolver, queued before a step that is not)
        # -- log each step's own entry too, so nothing is silently lost.
        step_physics = result.get("step_physics_status", [])
        step_numerical = result.get("step_numerical_status", [])
        for index, (physics, numerical) in enumerate(
            zip(step_physics, step_numerical)
        ):
            if physics or numerical:
                self._log(f"\n-- step {index + 1}/{len(all_steps)} --\n")
                self._log_physics_status(
                    {"physics_status": physics, "numerical_status": numerical}
                )
        # One mesh path per step in self.completed_steps, same order --
        # lets the Process Flow Timeline show any step's own real
        # geometry on click (see _on_timeline_step_click), not only the
        # final one. Falls back to an empty list on an older worker
        # payload rather than raising, so the timeline degrades to
        # "final mesh only" instead of crashing.
        #
        # When resuming, the worker only ran the QUEUED steps, so its
        # step_meshes cover just those; the earlier steps' meshes are
        # the ones this session already recorded. Concatenating keeps
        # the index-for-index alignment with completed_steps that the
        # timeline depends on. (Replaying returns meshes for every step,
        # so the previous list is replaced outright.)
        step_meshes = result.get("step_meshes", [])
        self.flow_step_meshes = (
            self.flow_step_meshes + step_meshes if can_resume else step_meshes
        )
        self.flow_steps = []
        self._refresh_flow_list()

        self._update_process_buttons()
        self.redraw()

    def _locos_in_history(self):
        """True if any step already run was a LOCOS oxidation.

        LOCOS keeps per-domain bookkeeping that lives only in the
        process that created it: `io.register_locos_export()` and
        `register_locos_unwrapped()` are keyed by `id(domain)`, and the
        unwrapped entry holds live ViennaLS level-set objects. A .vpsd
        round-trip cannot carry either, so a resumed LOCOS domain
        reports `is_locos_registered() == False` and a following
        LOCOS-on-LOCOS oxidation would refuse outright (thermal.py
        raises NotImplementedError for exactly this).

        Measured, so the scope of the problem is known rather than
        assumed: a LOCOS domain round-tripped through .vpsd still
        EXPORTS all three materials correctly (Mask/Si/SiO2, same
        extents as the live-domain export), so ordinary chaining after
        LOCOS is fine — it is specifically LOCOS-after-LOCOS that needs
        the live objects.

        Rather than trade that away for speed, a history containing
        LOCOS falls back to replaying the recipes, which is what the GUI
        did for every step before state carry existed.
        """
        return any(
            step.get("_process_category") == "oxidation"
            and "mask_material" in step
            for step in self.completed_steps
        )

    def _chained_flow_config(self, recipe, output_dir):
        """Config for one RUN click, continuing the real current wafer.

        Preferred path: hand the worker the .vpsd the PREVIOUS click
        left behind, so this click runs exactly ONE step on the
        accumulated geometry. That is what "each RUN takes the previous
        result as its input" means literally.

        Fallback path: replay `completed_steps + [recipe]` from a fresh
        wafer. This is what every click used to do, and it is still
        correct -- just O(N^2), because the Nth click re-runs all N
        steps and therefore re-pays for the slowest one (a 30s
        oxidation, say) on every subsequent click. It is kept for the
        two cases where resuming cannot be trusted: no usable state file
        yet, and a LOCOS history (see _locos_in_history).

        Called AFTER the ADD TO FLOW interception (self._pending_flow_add
        returns before this), so `recipe` here is always something about
        to run now, not merely queued.
        """
        state = self.last_domain_state
        can_resume = (
            state
            and Path(state).exists()
            and not self._locos_in_history()
        )
        if can_resume:
            return {
                "_flow_steps": [recipe],
                "_resume_state": state,
                "output_dir": output_dir,
            }
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
            "metallization": self.run_metallization,
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
                "Only Oxidation, Etching, Deposition, Metallization and Geometry "
                "are real "
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

        T = Tokens
        # GUI-only: the inspector is taller than most windows once the
        # Etch recipe's fields are stacked, which previously pushed the
        # RUN button below the window edge with no way to reach it.
        # Hosting it in a scrollable canvas keeps every widget reachable
        # at any window height. No process/physics logic is affected --
        # `panel` is still the same ttk.Frame the sub-panels build into.
        scroll_host = ttk.Frame(parent, style="Inspector.TFrame", width=320)
        scroll_host.pack(side="right", fill="y")
        scroll_host.pack_propagate(False)

        header = ttk.Frame(scroll_host, style="Inspector.TFrame", padding=(12, 8, 12, 6))
        header.pack(fill="x")
        ttk.Label(header, text="PARAMETER INSPECTOR", style="Section.TLabel").pack(anchor="w")
        self.inspector_title_var = tk.StringVar(value=self.panel_category.get())
        ttk.Label(header, textvariable=self.inspector_title_var,
                  style="Header.TLabel", background=T.BG_1,
                  font=(T.FONT_UI, 12, "bold")).pack(anchor="w")
        ttk.Separator(scroll_host).pack(fill="x")

        scroll_area = ttk.Frame(scroll_host, style="Inspector.TFrame")
        scroll_area.pack(fill="both", expand=True)

        scroll_canvas = tk.Canvas(
            scroll_area, bg=T.BG_1, highlightthickness=0, borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(
            scroll_area, orient="vertical", command=scroll_canvas.yview,
        )
        scroll_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)

        panel = ttk.Frame(scroll_canvas, style="Inspector.TFrame", width=320)
        panel_window = scroll_canvas.create_window(
            (0, 0), window=panel, anchor="nw", width=320,
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

        # Category selection now comes from the Process Library tree
        # (_make_process_panel) writing into self.panel_category; this
        # panel only needs to react to it. Every category's panel is
        # still built once into one fixed container with exactly one
        # shown at a time (see _show_panel_category) -- stacking all
        # seven made the inspector several screens long regardless of
        # what the user was doing.
        self.panel_category.trace_add(
            "write",
            lambda *_a: self.inspector_title_var.set(self.panel_category.get()),
        )

        ttk.Button(
            panel, text="+ ADD TO FLOW", style="Accent.TButton",
            command=self.add_current_step_to_flow,
        ).pack(fill="x", padx=12, pady=(10, 4))

        panel_container = ttk.Frame(panel, style="Inspector.TFrame")
        panel_container.pack(fill="x")

        self._make_lithography_panel(panel_container)
        self._make_etch_panel(panel_container)
        self._make_oxidation_panel(panel_container)
        self._make_deposition_panel(panel_container)
        self._make_metallization_panel(panel_container)
        self._make_geometry_panel(panel_container)
        self._make_doping_panel(panel_container)
        self._make_measurement_panel(panel_container)
        self._make_electrode_panel(panel_container)

        self._show_panel_category()

        # etch_button/oxidation_button/deposition_button (created above)
        # are required by _update_process_buttons(); call it only after
        # all panels exist so widget creation order / visual layout is
        # unchanged, only the timing of this refresh call moves.
        self._update_process_buttons()

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
            bg=Tokens.BG_2, fg=Tokens.FG,
            selectbackground=Tokens.ACCENT_DIM,
            selectforeground="#1A1400",
            highlightthickness=1, highlightbackground=Tokens.LINE,
            relief="flat", font=(Tokens.FONT_DATA, 9),
        )
        self.openings_list.pack(fill="x", padx=12)
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
            style="Run.TButton",
            command=self.run_etch,
        )
        self.etch_button.pack(
            fill="x",
            padx=12,
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

        # Thermal oxidation and LOCOS are INDEPENDENT choices, the same
        # way each etch or deposition model is. LOCOS used to be a
        # checkbox on the thermal recipe, which made it read as a
        # modifier of ordinary oxidation and let its special-case logic
        # (its own from-scratch pad-oxide+mask geometry, its mask
        # material, its elastic contact mode) reach into the plain path.
        # As a separate method, selecting "Thermal oxidation" cannot
        # touch any of it -- see run_oxidation(), where the LOCOS branch
        # is the only place mask keys are built at all.
        self.oxidation_method = tk.StringVar(value="Thermal oxidation")

        ttk.Label(
            frame,
            text="Oxidation process",
            style="Caption.TLabel",
        ).pack(anchor="w", pady=(6, 1))

        ttk.Combobox(
            frame,
            textvariable=self.oxidation_method,
            state="readonly",
            values=["Thermal oxidation", "LOCOS"],
        ).pack(fill="x")

        self.oxidation_button = ttk.Button(
            frame,
            text="5b. START OXIDATION — VIENNAPS",
            style="Run.TButton",
            command=self.run_oxidation,
        )
        self.oxidation_button.pack(
            fill="x",
            padx=12,
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

            is_locos = self.oxidation_method.get() == "LOCOS"

            # Plain thermal oxidation builds NO mask, ever. It oxidizes
            # whatever surface the wafer currently has -- that is the
            # whole step. `mask_spans_um: []` is this project's own
            # "bare wafer, no lithography" convention (prepare_domain()),
            # and on a chained run the inherited domain is used
            # untouched.
            #
            # This used to send the lithography panel's mask window
            # through unconditionally, which built a real Mask solid that
            # plain oxidation never tells ViennaPS about -- measured, the
            # oxide then grew across the whole top surface INCLUDING on
            # top of that Mask (SiO2 at y +1.00..+1.10 over Mask at
            # y -0.00..+0.96), oxide floating on a mask rather than grown
            # from silicon.
            #
            # LOCOS builds its own pad-oxide-first geometry and its own
            # mask; that is why the mask keys live in ITS branch only.
            mask_keys = self._mask_recipe_keys() if is_locos else {"mask_spans_um": []}

            # Photoresist on the wafer is REPORTED, never acted on and
            # never blocked. Two measurements say why it cannot be used
            # as an oxidation mask, neither guessed:
            #   * oxidizing a domain that carries resist grows SiO2 ON
            #     TOP of the Mask (oxide y=[0.994,1.059] over Mask
            #     y=[0,0.994]) -- resist sandwiched between the oxide and
            #     the silicon it supposedly grew from;
            #   * passing mask_material to prevent that DESTROYS the
            #     resist instead (a 1.0um Mask collapsed to
            #     y=[-0.002,0.006]), this project's own documented
            #     mask-erosion failure for a mask with no pad-oxide
            #     buffer under it.
            # The physical reason for both is that a furnace oxidation
            # runs at 900-1200 C and photoresist is gone far below that.
            # So: say what will happen, in the log, and run the step the
            # user asked for.
            if not is_locos and self._resist_spans_um() is not None:
                self._log(
                    "\nNOTE: photoresist is present on the wafer. It is not "
                    "used as an oxidation mask — photoresist does not survive "
                    "a furnace oxidation — so this step oxidizes the exposed "
                    "surface.\n"
                )

            recipe = {
                "_process_category": "oxidation",
                "_process_model_key": "thermal",

                **mask_keys,

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

            if is_locos:
                # Presence of this key is the plain (absent) vs LOCOS
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

        model_label = "LOCOS" if is_locos else "thermal oxidation"

        self._log(
            f"\n================================\n"
            f"REAL VIENNAPS {model_label.upper()} START\n"
            f"================================\n"
            f"1. {'Pad oxide + mask (LOCOS)' if is_locos else 'current wafer surface'}\n"
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
        self.last_domain_state = result.get("domain_state")
        self.last_physics_status = result.get("physics_status")
        self._log_physics_status(result)
        # Keep flow_step_meshes aligned index-for-index with
        # completed_steps (see run_process_flow's own comment) so the
        # bottom timeline can show this step's geometry on click even
        # when it was run as a standalone RUN click, not via RUN
        # PROCESS FLOW.
        self.flow_step_meshes.append(self.last_final_mesh)

        self._mark_stage_done(1)

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
        self.dep_epitaxy_material_var = self._material_field(
            epitaxy_frame, "Epitaxial material", "Si",
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

        # Blanket vs. selective/lift-off, user-chosen -- NOT forced by
        # whether a mask happens to exist (see the collision this fixes
        # in tcad/process/deposition/isotropic.py's own comment: this
        # key used to be conflated with the mask/resist geometry's own
        # material tag, which made growth-exclusion unconditional
        # whenever a mask existed at all). Only Isotropic/Directional/
        # Conformal CVD honor this -- the other 4 models have their own,
        # different selectivity mechanism (material_rates) or none.
        ttk.Label(
            frame, text="Deposition mode", style="Caption.TLabel",
        ).pack(anchor="w", padx=12, pady=(6, 1))
        self.dep_mask_mode_var = tk.StringVar(value=self._DEPOSITION_MODE_BLANKET)
        ttk.Combobox(
            frame,
            textvariable=self.dep_mask_mode_var,
            state="readonly",
            values=[self._DEPOSITION_MODE_BLANKET, self._DEPOSITION_MODE_SELECTIVE],
        ).pack(fill="x", padx=12)
        ttk.Label(
            frame,
            text=(
                "Selective excludes growth from the current mask/resist "
                "(Isotropic, Directional, Conformal CVD only)."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(anchor="w", padx=12, pady=(1, 0))

        self.deposition_button = ttk.Button(
            frame,
            text="5c. START DEPOSITION — VIENNAPS",
            style="Run.TButton",
            command=self.run_deposition,
        )
        self.deposition_button.pack(
            fill="x",
            padx=12,
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

    #: Metallization method -> the deposition model that actually runs it.
    #: Metallization IS deposition at the backend (a metal film grown on
    #: the current surface), so this reuses the registered deposition
    #: models rather than adding a parallel implementation. The subset is
    #: the physically meaningful one: TEOS/PE-CVD are oxide chemistries
    #: and selective epitaxy grows crystalline semiconductor, none of
    #: which deposit metal.
    _METALLIZATION_METHODS = {
        "Sputter / PVD (directional)": "directional",
        "CVD (conformal)": "single_particle_cvd",
        "Plating / CVD (isotropic)": "isotropic",
    }

    #: Metals actually present in ViennaPS's own Material enum (verified
    #: against the installed 4.6.2 enum, not assumed -- note there is no
    #: Al, which is why the default is W).
    _METAL_OPTIONS = [
        "W", "Cu", "TiN", "Ti", "Ta", "TaN", "Co", "Ru", "Ni", "Pt",
        "Mo", "Au", "Cr", "Metal",
    ]

    def _make_metallization_panel(self, parent):
        """Metallization as its own category.

        A real flow names this step separately from "deposition" (see
        the PN-junction-diode sequence in CLAUDE.md: oxidation ->
        lithography -> doping -> metallization -> lithography), and it
        answers a different question -- WHICH METAL and by which
        method -- so it gets its own category rather than being buried
        as one material choice inside the deposition panel.

        It is deliberately a thin layer over the deposition registry:
        run_metallization() emits `_process_category: "deposition"`, so
        every chaining, masking and state-carry behavior is the same
        code path the deposition panel already uses, and there is no
        second implementation to keep in sync.
        """
        frame = ttk.LabelFrame(parent, text="Metallization recipe", padding=10)
        self._panel_frames["metallization"] = frame
        frame.pack(fill="x", pady=10)

        ttk.Label(frame, text="Metallization method").pack(anchor="w")
        self.metal_method = tk.StringVar(value="Sputter / PVD (directional)")
        ttk.Combobox(
            frame,
            textvariable=self.metal_method,
            state="readonly",
            values=list(self._METALLIZATION_METHODS),
        ).pack(fill="x")

        ttk.Label(frame, text="Metal", style="Caption.TLabel").pack(
            anchor="w", padx=12, pady=(6, 1),
        )
        self.metal_material_var = tk.StringVar(value="W")
        ttk.Combobox(
            frame,
            textvariable=self.metal_material_var,
            state="readonly",
            values=self._METAL_OPTIONS,
        ).pack(fill="x", padx=12)

        # Same defaults the deposition panel uses for the same two
        # models, which tests/integration/test_phase3_deposition_real.py
        # already exercises against real ViennaPS.
        self.metal_rate_var = self._field(frame, "Rate (µm/s)", 0.05)
        self.metal_time_var = self._field(frame, "Deposition time (s)", 0.5)
        self.metal_grid_var = self._field(frame, "Grid delta (µm)", 0.05)

        # See the Deposition panel's matching toggle. Default Blanket
        # here specifically matches this panel's OWN help text below
        # ("lift-off geometry"), which unconditional mask_material used
        # to contradict (metal was excluded from the mask, the opposite
        # of lift-off) -- see docs/investigation_log.md, "Deposition:
        # renderer y-scale artifact ... unconditional mask exclusion".
        ttk.Label(
            frame, text="Deposition mode", style="Caption.TLabel",
        ).pack(anchor="w", padx=12, pady=(6, 1))
        self.metal_mask_mode_var = tk.StringVar(value=self._DEPOSITION_MODE_BLANKET)
        ttk.Combobox(
            frame,
            textvariable=self.metal_mask_mode_var,
            state="readonly",
            values=[self._DEPOSITION_MODE_BLANKET, self._DEPOSITION_MODE_SELECTIVE],
        ).pack(fill="x", padx=12)

        self.metallization_button = ttk.Button(
            frame,
            text="RUN METALLIZATION",
            style="Run.TButton",
            command=self.run_metallization,
        )
        self.metallization_button.pack(fill="x", padx=12, pady=(12, 3))

        ttk.Label(
            frame,
            text=(
                "Metal is deposited on the CURRENT surface. Blanket mode: "
                "with a developed resist present, metal lands in the "
                "openings AND on top of the resist (lift-off geometry). "
                "Selective mode excludes the resist/mask instead."
            ),
            foreground="#555",
            wraplength=310,
        ).pack(anchor="w", pady=5)

    def run_metallization(self):
        """Deposit a metal film, through the deposition registry."""
        model_key = self._METALLIZATION_METHODS.get(self.metal_method.get())
        if model_key is None:
            messagebox.showinfo("Backend status", "Unknown metallization method.")
            return

        if not viennaps_session.is_available():
            messagebox.showerror(
                "ViennaPS",
                "ViennaPS is not installed.\n\nRun:\npython -m pip install ViennaPS",
            )
            return

        self._note_if_blanket_resist("metallization")

        try:
            recipe = {
                "_process_category": "deposition",
                "_process_model_key": model_key,
                **self._mask_recipe_keys_for_current_step(),
                "pr_thickness_um": self.wafer.pr_thickness_um,
                "silicon_depth_um": self.wafer.silicon_depth_um,
                "grid_delta_um": float(self.metal_grid_var.get()),
                "x_extent_um": self.wafer.width_um,
                "y_extent_um": 8.0,
                "deposition_time_s": float(self.metal_time_var.get()),
                "material": self.metal_material_var.get(),
            }
            if model_key == "directional":
                recipe["direction"] = [0.0, 1.0, 0.0]
                recipe["directional_velocity"] = float(self.metal_rate_var.get())
            else:
                recipe["rate"] = float(self.metal_rate_var.get())
            if model_key == "single_particle_cvd":
                recipe["sticking_probability"] = 0.1
            if self.metal_mask_mode_var.get() == self._DEPOSITION_MODE_SELECTIVE:
                recipe["deposit_exclude_material"] = recipe["mask_material"]
        except ValueError:
            messagebox.showerror(
                "Metallization recipe", "All recipe values must be numeric."
            )
            return

        if self._pending_flow_add:
            self._append_flow_step(recipe)
            return

        self._run_single_step(
            recipe,
            start_log=(
                f"\n================================\n"
                f"REAL VIENNAPS METALLIZATION START\n"
                f"================================\n"
                f"{self.metal_method.get()} — "
                f"{self.metal_material_var.get()}, "
                f"{recipe['deposition_time_s']}s\n"
            ),
            done_log="REAL VIENNAPS METALLIZATION COMPLETE",
            stage_index=1,
            history_label=(
                f"Metallization {self.metal_material_var.get()} "
                f"({self.metal_method.get()})"
            ),
            process_stage="deposited",
        )

    def _materialize_current_wafer(self):
        """Export the wafer as it is, running no process. True on success.

        Only used when something needs a real mesh and none exists yet —
        i.e. nothing has been run on this wafer. It is NOT a process
        step: it appends nothing to completed_steps, marks no stage, and
        changes no resist state. It just gives the current wafer a
        geometry so the step the user actually asked for can proceed
        instead of being refused.
        """
        if not viennaps_session.is_available():
            messagebox.showerror(
                "ViennaPS",
                "ViennaPS is not installed.\n\nRun:\npython -m pip install ViennaPS",
            )
            return False

        output_dir = tempfile.mkdtemp(prefix="tcad2d_wafer_")
        config_file = Path(output_dir) / "wafer.json"
        result_file = Path(output_dir) / "result.json"
        config_file.write_text(
            json.dumps({
                "_materialize_wafer": True,
                "output_dir": output_dir,
                "grid_delta_um": float(self.grid_var.get()),
                "x_extent_um": self.wafer.width_um,
                "y_extent_um": 8.0,
                "silicon_depth_um": self.wafer.silicon_depth_um,
                "pr_thickness_um": self.wafer.pr_thickness_um,
                # Whatever resist is really on the wafer right now, from
                # the same single source every other consumer reads.
                "mask_spans_um": self._resist_spans_um() or [],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._log("\nExporting the current wafer geometry (no process run)...\n")
        self.update_idletasks()
        try:
            completed = subprocess.run(
                [
                    sys.executable, str(Path(__file__).resolve()),
                    "--worker", str(config_file), str(result_file),
                ],
                capture_output=True, text=True, timeout=300,
            )
        except Exception as exc:
            messagebox.showerror("ViennaPS", str(exc))
            return False

        if not result_file.exists():
            messagebox.showerror(
                "ViennaPS",
                "Worker did not produce a result file.\n\n"
                + completed.stderr[-4000:],
            )
            return False

        result = json.loads(result_file.read_text(encoding="utf-8"))
        if not result.get("success"):
            messagebox.showerror(
                "ViennaPS", result.get("error", "Unknown ViennaPS error.")
            )
            return False

        self.last_final_mesh = result.get("final_mesh")
        self.last_domain_state = result.get("domain_state")
        self.wafer.processed = True
        self.redraw()
        return True

    def _strip_resist_from_geometry(self):
        """Actually remove resist-derived geometry. True on success.

        Only called when a real domain already exists (last_domain_state
        set) -- if none does, there is no real geometry to strip, and
        process_pr_strip()'s state-only path already covers that case.
        """
        if not viennaps_session.is_available():
            messagebox.showerror(
                "ViennaPS",
                "ViennaPS is not installed.\n\nRun:\npython -m pip install ViennaPS",
            )
            return False

        output_dir = tempfile.mkdtemp(prefix="tcad2d_strip_")
        config_file = Path(output_dir) / "strip.json"
        result_file = Path(output_dir) / "result.json"
        config_file.write_text(
            json.dumps({
                "_strip_resist": True,
                "_resume_state": self.last_domain_state,
                "output_dir": output_dir,
                "silicon_depth_um": self.wafer.silicon_depth_um,
                "resist_material": self._RESIST_MATERIAL,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._log("\nRemoving resist geometry from the wafer...\n")
        self.update_idletasks()
        try:
            completed = subprocess.run(
                [
                    sys.executable, str(Path(__file__).resolve()),
                    "--worker", str(config_file), str(result_file),
                ],
                capture_output=True, text=True, timeout=300,
            )
        except Exception as exc:
            messagebox.showerror("ViennaPS", str(exc))
            return False

        if not result_file.exists():
            messagebox.showerror(
                "ViennaPS",
                "Worker did not produce a result file.\n\n"
                + completed.stderr[-4000:],
            )
            return False

        result = json.loads(result_file.read_text(encoding="utf-8"))
        if not result.get("success"):
            messagebox.showerror(
                "ViennaPS", result.get("error", "Unknown ViennaPS error.")
            )
            return False

        self.last_final_mesh = result.get("final_mesh")
        self.last_domain_state = result.get("domain_state")
        return True

    def _run_single_step(
        self, recipe, start_log, done_log, stage_index, history_label,
        process_stage,
    ):
        """Execute one built recipe the same way every RUN button does.

        Deliberately a NEW helper used only by metallization rather than
        a refactor of run_etch/run_oxidation/run_deposition: those three
        are working, individually verified paths, and rewriting them to
        share this would put three known-good behaviors at risk to save
        duplication that is not currently causing a bug.
        """
        output_dir = tempfile.mkdtemp(prefix="tcad2d_metal_")
        config_file = Path(output_dir) / "recipe.json"
        result_file = Path(output_dir) / "result.json"

        config_file.write_text(
            json.dumps(
                self._chained_flow_config(recipe, output_dir),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._log(start_log)
        self.update_idletasks()

        try:
            completed = subprocess.run(
                [
                    sys.executable, str(Path(__file__).resolve()),
                    "--worker", str(config_file), str(result_file),
                ],
                capture_output=True, text=True, timeout=900,
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
            self._log("\nVIENNAPS FAILED\n")
            return

        self.wafer.processed = True
        self.process_stage = process_stage
        self.last_final_mesh = result.get("final_mesh")
        self.completed_steps.append(recipe)
        self.last_domain_state = result.get("domain_state")
        self.last_physics_status = result.get("physics_status")
        self._log_physics_status(result)
        self.flow_step_meshes.append(self.last_final_mesh)

        self._mark_stage_done(stage_index)
        self.history.append(history_label)
        self._log(
            f"\n================================\n"
            f"{done_log}\n"
            f"================================\n"
            f"mesh: {self.last_final_mesh}\n"
        )
        self._update_process_buttons()
        self.redraw()

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

        self._note_if_blanket_resist("deposition")

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

                # Fresh wafer -> mask_left_um/mask_right_um/mask_spans_um
                # (MakeTrench/make_mask_spans); chained onto an earlier
                # step -> remask_spans_um instead, so a mask applied
                # mid-flow (see _mask_recipe_keys_for_current_step) isn't
                # silently ignored the way it used to be.
                **self._mask_recipe_keys_for_current_step(),

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
                    "material": self.dep_isotropic_material_var.get(),
                })

            elif model_key == "directional":

                recipe.update({
                    "direction": [0.0, 1.0, 0.0],
                    "directional_velocity": float(self.dep_directional_velocity_var.get()),
                    "deposition_time_s": float(self.dep_directional_time_var.get()),
                    "material": self.dep_directional_material_var.get(),
                })

            elif model_key == "single_particle_cvd":

                recipe.update({
                    "rate": float(self.dep_cvd_rate_var.get()),
                    "sticking_probability": float(self.dep_cvd_sticking_var.get()),
                    "deposition_time_s": float(self.dep_cvd_time_var.get()),
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
                    # "material_rates" names the SEED surface growth is
                    # selective to; "material" is what gets grown.
                    "material_rates": [
                        {"material": "Si", "rate": float(self.dep_epitaxy_rate_var.get())},
                    ],
                    "deposition_time_s": float(self.dep_epitaxy_time_var.get()),
                    "material": self.dep_epitaxy_material_var.get(),
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

            # Only these 3 models honor deposit_exclude_material (see
            # their own maskMaterial= wiring); exclude wherever the
            # CURRENT recipe's own mask/resist geometry is tagged, so
            # "Selective" always matches what's actually in the domain
            # this run, not a hardcoded material name.
            if (
                model_key in ("isotropic", "directional", "single_particle_cvd")
                and self.dep_mask_mode_var.get() == self._DEPOSITION_MODE_SELECTIVE
            ):
                recipe["deposit_exclude_material"] = recipe["mask_material"]

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
        self.last_domain_state = result.get("domain_state")
        self.last_physics_status = result.get("physics_status")
        self._log_physics_status(result)
        # Keep flow_step_meshes aligned index-for-index with
        # completed_steps (see run_process_flow's own comment) so the
        # bottom timeline can show this step's geometry on click even
        # when it was run as a standalone RUN click, not via RUN
        # PROCESS FLOW.
        self.flow_step_meshes.append(self.last_final_mesh)

        self._mark_stage_done(1)

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
            style="Run.TButton",
            command=self.run_gate_stack,
        )
        self.gate_stack_button.pack(
            fill="x",
            padx=12,
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

    def _clear_state_for_gate_stack(self):
        """Gate stack is terminal and builds its own geometry from
        scratch, so nothing from the previous wafer may survive it.

        Four fields carry state across RUN clicks, and all four must be
        cleared here: completed_steps/flow_step_meshes/last_domain_state
        (added when RUN clicks started resuming an accumulated .vpsd —
        without clearing last_domain_state the next RUN resumes the
        PRE-gate-stack wafer) and last_physics_status, which was
        overlooked in the same way — without clearing it, a status
        panel or log read after a gate-stack build would still show the
        PRE-gate-stack step's physics/numerical status.
        """
        self.completed_steps = []
        self.flow_step_meshes = []
        self.last_domain_state = None
        self.last_physics_status = None

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

                # Si and SiO2 get genuinely shared (not merely
                # coincident) mesh vertices at their boundary, needed
                # for tcad.device.devsim.mesh_import.import_process_
                # result's interface_region_pairs to find a real
                # Si-SiO2 interface at all (see save_locos_volume_
                # mesh's own dedupe_materials docstring: gate_stack's
                # raw per-material export has ZERO shared indices
                # between materials even where their coordinates
                # coincide exactly). Restricted to Si+SiO2 only,
                # exactly like the already-shipped gate C-V test's own
                # usage -- deduping every touching pair (including the
                # source/drain metal pads) is documented to crash
                # DevSim's create_device() for this topology.
                "dedupe_materials": ["Si", "SiO2"],
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
        self._clear_state_for_gate_stack()

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
        # Donor and acceptor are independent, both non-negative inputs
        # (e.g. Donor=1e16, Acceptor=5e15) -- net = donor - acceptor is
        # computed in run_doping(), matching how apply_step_junction_doping
        # already takes donor_conc_cm3/acceptor_conc_cm3 as two separate
        # values rather than one pre-signed number. Only the resulting
        # net value is ever passed to apply_uniform_doping()/DopingRegion
        # -- this is a GUI-only change, doping.py's net-doping-only
        # architecture is untouched.
        self.dope_uniform_donor_var = self._field(
            uniform_frame, "Donor conc. (cm^-3, >= 0)", 1.0e17,
        )
        self.dope_uniform_acceptor_var = self._field(
            uniform_frame, "Acceptor conc. (cm^-3, >= 0)", 0.0,
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
        self.dope_gauss_donor_var = self._field(
            gaussian_frame, "Donor peak conc (cm^-3, >= 0)", 1.0e17,
        )
        self.dope_gauss_acceptor_var = self._field(
            gaussian_frame, "Acceptor peak conc (cm^-3, >= 0)", 0.0,
        )
        self.dope_gauss_donor_species_var = self._field(
            gaussian_frame, "Donor species (label only, not used in the physics model)", "P",
        )
        self.dope_gauss_acceptor_species_var = self._field(
            gaussian_frame, "Acceptor species (label only, not used in the physics model)", "B",
        )

        windows_frame = ttk.Frame(doping_params_container)
        self.dope_win_region_var = self._field(
            windows_frame, "Region", "Si",
        )
        self.dope_win_axis_var = self._field(
            windows_frame, "Axis (x/y)", "x",
        )
        self.dope_win_donor_bg_var = self._field(
            windows_frame, "Background donor conc (cm^-3, >= 0)", 0.0,
        )
        self.dope_win_acceptor_bg_var = self._field(
            windows_frame, "Background acceptor conc (cm^-3, >= 0)", 1.0e17,
        )
        self.dope_win_src_min_var = self._field(
            windows_frame, "Source window min (µm)", -1.6,
        )
        self.dope_win_src_max_var = self._field(
            windows_frame, "Source window max (µm)", -0.6,
        )
        self.dope_win_src_donor_var = self._field(
            windows_frame, "Source window donor conc (cm^-3, >= 0)", 1.0e20,
        )
        self.dope_win_src_acceptor_var = self._field(
            windows_frame, "Source window acceptor conc (cm^-3, >= 0)", 0.0,
        )
        self.dope_win_drn_min_var = self._field(
            windows_frame, "Drain window min (µm)", 0.6,
        )
        self.dope_win_drn_max_var = self._field(
            windows_frame, "Drain window max (µm)", 1.6,
        )
        self.dope_win_drn_donor_var = self._field(
            windows_frame, "Drain window donor conc (cm^-3, >= 0)", 1.0e20,
        )
        self.dope_win_drn_acceptor_var = self._field(
            windows_frame, "Drain window acceptor conc (cm^-3, >= 0)", 0.0,
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

        # SiO2-barrier exclusion -- see docs/investigation_log.md,
        # "SiO2 doesn't block doping". A REAL geometric threshold
        # (measured directly from the mesh), not a fake energy-derived
        # number -- see CLAUDE.md's "no fake physics parameters" rule.
        # Default 0.0 = any measurable SiO2 above the doped region
        # blocks doping there (the most conservative reading available
        # without a real implant-energy model to compute an actual
        # penetration depth). Shared across all 4 kinds -- lives on
        # `frame` itself, not inside any per-kind frame.
        self.dope_barrier_threshold_var = self._field(
            frame, "SiO2 barrier min thickness (µm)", 0.0,
        )

        self.doping_button = ttk.Button(
            frame,
            text="APPLY DOPING",
            style="Run.TButton",
            command=self.run_doping,
        )
        self.doping_button.pack(
            fill="x",
            padx=12,
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

    def _doping_is_stale(self) -> bool:
        """True when the doping profile describes a mesh a later step replaced.

        Doping attaches to the mesh that existed when it ran. Any process
        step afterwards produces a new mesh, and the old profile then
        describes geometry that no longer exists — measurement would
        silently solve the wafer as it was BEFORE that step.
        """
        if self.last_doped_result is None:
            return False
        attached = getattr(self.last_doped_result, "volume_mesh_path", None)
        return bool(attached and attached != self.last_final_mesh)

    def run_doping(self, silent: bool = False):
        """Apply the selected doping kind. Returns True on success.

        `silent` suppresses only the success POPUP -- the log line and
        the auto-switch to the doping color overlay still happen either
        way. Needed because run_measurement() calls this internally to
        re-attach stale doping to the current mesh; without `silent`,
        that internal call pops its own "Doping applied" dialog in the
        middle of a MEASURE click, which reads as an error interrupting
        the solve the user actually asked for (see
        docs/investigation_log.md, "Doping: five confirmed gaps",
        item 3). Whether DevSim itself then solves successfully is
        reported separately, by run_measurement().
        """

        # Doping runs on the wafer as it is. It used to refuse until some
        # other process had run, which is exactly the kind of
        # prerequisite the user must never meet: a wafer exists from the
        # moment it is created, and doping virgin silicon is a real
        # step. If no mesh has been produced yet, the current wafer is
        # exported now and doped.
        if not (self.last_final_mesh and Path(self.last_final_mesh).exists()):
            if not self._materialize_current_wafer():
                return False

        kind = self.doping_kind.get()

        try:

            process_result = build_process_result(
                {"final_mesh": self.last_final_mesh, "snapshots": []}
            )

            if kind == "Uniform":

                region = self.dope_uniform_region_var.get()
                donor = float(self.dope_uniform_donor_var.get())
                acceptor = float(self.dope_uniform_acceptor_var.get())
                conc = donor - acceptor
                doped_result = apply_uniform_doping(
                    process_result, {region: conc},
                )
                summary = (
                    f"region={region!r} donor={donor:.3e} "
                    f"acceptor={acceptor:.3e} -> net_doping_cm3={conc:.3e}"
                )

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
                donor = float(self.dope_gauss_donor_var.get())
                acceptor = float(self.dope_gauss_acceptor_var.get())
                donor_species = self.dope_gauss_donor_species_var.get()
                acceptor_species = self.dope_gauss_acceptor_species_var.get()
                doped_result = apply_gaussian_implant_doping(
                    process_result, region=region, junction_axis=axis,
                    peak_position_um=position, straggle_um=straggle,
                    donor_peak_conc_cm3=donor, acceptor_peak_conc_cm3=acceptor,
                    donor_species=donor_species, acceptor_species=acceptor_species,
                )
                summary = (
                    f"region={region!r} axis={axis!r} "
                    f"peak@{position}um straggle={straggle}um "
                    f"donor={donor:.3e}({donor_species}) "
                    f"acceptor={acceptor:.3e}({acceptor_species}) -> "
                    f"peak_net_cm3={donor - acceptor:.3e}"
                )

            elif kind == "Implant Windows":

                region = self.dope_win_region_var.get()
                axis = self.dope_win_axis_var.get()
                donor_bg = float(self.dope_win_donor_bg_var.get())
                acceptor_bg = float(self.dope_win_acceptor_bg_var.get())
                src_min = float(self.dope_win_src_min_var.get())
                src_max = float(self.dope_win_src_max_var.get())
                src_donor = float(self.dope_win_src_donor_var.get())
                src_acceptor = float(self.dope_win_src_acceptor_var.get())
                drn_min = float(self.dope_win_drn_min_var.get())
                drn_max = float(self.dope_win_drn_max_var.get())
                drn_donor = float(self.dope_win_drn_donor_var.get())
                drn_acceptor = float(self.dope_win_drn_acceptor_var.get())
                windows = [
                    {"min_um": src_min, "max_um": src_max,
                     "donor_conc_cm3": src_donor, "acceptor_conc_cm3": src_acceptor},
                    {"min_um": drn_min, "max_um": drn_max,
                     "donor_conc_cm3": drn_donor, "acceptor_conc_cm3": drn_acceptor},
                ]
                doped_result = apply_implant_windows_doping(
                    process_result, region=region, axis=axis,
                    donor_background_cm3=donor_bg, acceptor_background_cm3=acceptor_bg,
                    windows=windows,
                )
                summary = (
                    f"region={region!r} axis={axis!r} "
                    f"background_net={donor_bg - acceptor_bg:.3e} "
                    f"source_net={src_donor - src_acceptor:.3e} "
                    f"drain_net={drn_donor - drn_acceptor:.3e}"
                )

            else:

                messagebox.showinfo(
                    "Doping",
                    "Unknown doping kind selected.",
                )

                return False

        except ValueError:

            messagebox.showerror(
                "Doping recipe",
                "All numeric recipe values must be numeric.",
            )

            return False

        except Exception as exc:

            messagebox.showerror(
                "Doping",
                str(exc),
            )

            return False

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

        # Show the result where the user can actually see it: the
        # existing P/N color overlay (_doping_color_segments) was
        # already implemented correctly but invisible by default,
        # because the layer selector defaults to "geometry". Switch to
        # it automatically instead of requiring the user to know the
        # selector exists.
        self.viewer_layer_var.set("doping")
        self.redraw()

        if not silent:
            messagebox.showinfo(
                "Doping",
                f"Doping profile attached ({kind}).\n\n{summary}\n\n"
                f"No DevSim solve was run -- this only attaches the "
                f"DopingProfile object and reports it in the process log.",
            )

        return True

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
            style="Run.TButton",
            command=self.run_measurement,
        )
        self.measure_button.pack(
            fill="x",
            padx=12,
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
            # A statement of what is missing from the DEVICE, not an
            # instruction about process order: a drift-diffusion solve
            # needs a doping profile because without one there are no
            # carriers to solve for.
            messagebox.showinfo(
                "Device measurement",
                "This wafer carries no doping profile, so there is no device "
                "to measure — a drift-diffusion solve has no carrier "
                "concentrations without one.",
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

        if self._doping_is_stale():
            # Re-apply the SAME doping specification to the CURRENT mesh
            # instead of solving the geometry as it was before the last
            # process step. Not a prerequisite: nothing is refused, and
            # the user is told what happened.
            self._log(
                "\nNOTE: the doping profile was attached to an earlier mesh. "
                "Re-applying the same doping to the current geometry before "
                "measuring.\n"
            )
            if not self.run_doping(silent=True):
                return
            doped_result = self.last_doped_result

        region = doped_result.doping.regions[0].region
        kind = doped_result.doping.kind

        from tcad.device.devsim.mesh_import import import_process_result, derive_barrier_covered_windows
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

        exclude_windows = None
        if kind != "implant_windows":
            # implant_windows never reaches the apply_doping() call below
            # that consumes exclude_windows (it routes through the robust
            # solve path, which registers NetDoping itself) -- deriving
            # barrier windows for it would be a wasted real mesh read.
            try:
                # Barrier stacking is always along y in this project's
                # fixed 2D convention (x lateral, y depth/growth),
                # regardless of which axis the user picked for the
                # measurement CONTACTS -- so this must NOT reuse `axis`.
                exclude_windows = derive_barrier_covered_windows(
                    doped_result, doped_region=region,
                    barrier_material="SiO2", axis="x",
                    min_barrier_thickness_um=float(self.dope_barrier_threshold_var.get()),
                )
                if exclude_windows:
                    total_excluded_um = sum(
                        w["max_um"] - w["min_um"] for w in exclude_windows
                    )
                    self._log(
                        f"\nSiO2 barrier exclusion: {len(exclude_windows)} "
                        f"window(s) totaling {total_excluded_um:.4f}um excluded "
                        f"from doping (min thickness "
                        f"{float(self.dope_barrier_threshold_var.get()):.4f}um): "
                        f"{exclude_windows}\n"
                    )
            except Exception as exc:
                # Barrier detection is best-effort: if it fails (material
                # absent, mesh unreadable), fall back to no exclusion --
                # never let a diagnostic feature block the actual measurement.
                exclude_windows = None
                self._log(f"\n(Could not derive SiO2 barrier windows: {exc!r})\n")

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
                    exclude_windows=exclude_windows, exclude_axis="x",
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
    # ELECTRODES (CAD pin placement, 4-terminal)
    # --------------------------------------------------------

    def _make_electrode_panel(self, parent):
        """CAD-style electrode placement -- coordinate pins resolved to
        real DevSim contacts via tcad.device.devsim.contact_probe,
        distinct from _make_measurement_panel's own region-extreme-only
        2-terminal flow (that panel is unmodified by this feature)."""
        frame = ttk.LabelFrame(parent, text="Electrodes (CAD pin placement)", padding=10)
        self._panel_frames["electrodes"] = frame
        frame.pack(fill="x", pady=10)

        ttk.Label(
            frame,
            text=(
                "Place named pins at real wafer coordinates (um); RESOLVE "
                "checks each against the real mesh before any DevSim "
                "contact is created."
            ),
            foreground="#555", wraplength=310,
        ).pack(anchor="w", pady=(0, 6))

        self.electrode_listbox = tk.Listbox(frame, height=5)
        self.electrode_listbox.pack(fill="x", pady=(0, 4))

        pin_row = ttk.Frame(frame)
        pin_row.pack(fill="x")
        self.pin_name_var = self._field(pin_row, "Name", "Source")
        self.pin_role_var = self._field(pin_row, "Role", "Source")
        self.pin_x_var = self._field(pin_row, "X (um)", 1.0)
        self.pin_y_var = self._field(pin_row, "Y (um)", 0.0)

        ttk.Button(
            frame, text="ADD PIN", command=self._on_add_pin_clicked,
        ).pack(fill="x", pady=(4, 2))

        ttk.Button(
            frame, text="RESOLVE PINS", style="Run.TButton",
            command=self._on_resolve_pins_clicked,
        ).pack(fill="x", pady=(2, 2))

        self.dc_drain_v_var = self._field(frame, "Drain V", 0.1)
        self.dc_gate_v_var = self._field(frame, "Gate V", 1.0)
        self.dc_body_v_var = self._field(frame, "Body V", 0.0)

        ttk.Button(
            frame, text="DC OPERATING POINT", command=self._on_dc_operating_point_clicked,
        ).pack(fill="x", pady=(6, 2))

    def add_electrode_pin(self, name, role, x_um, y_um, target_region=None):
        """Programmatic pin add (used by the GUI's own ADD PIN button
        and directly by tests). Duplicate NAMES are rejected here
        (dict-like uniqueness); duplicate POSITIONS are caught later by
        resolve_electrode_pins() via find_duplicate_pin_positions()."""
        from tcad.mesh.pin import Pin
        if any(p.name == name for p in self.electrode_pins):
            messagebox.showerror("Electrode", f"A pin named {name!r} already exists.")
            return False
        self.electrode_pins.append(Pin(name=name, role=role, x_um=x_um, y_um=y_um, target_region=target_region))
        self.electrode_listbox.insert("end", f"{name} ({role}) @ ({x_um:.3f}, {y_um:.3f}) um")
        return True

    def _on_add_pin_clicked(self):
        try:
            x_um = float(self.pin_x_var.get())
            y_um = float(self.pin_y_var.get())
        except ValueError:
            messagebox.showerror("Electrode", "X/Y must be numeric.")
            return
        self.add_electrode_pin(self.pin_name_var.get(), self.pin_role_var.get(), x_um, y_um)

    def resolve_electrode_pins(self):
        """Validates every placed pin against the real current mesh,
        then imports them all as real DevSim point contacts in ONE
        import_process_result call. Returns the ImportedDevice on
        success; None (with a messagebox reporting every collected
        error) if any pin is invalid. Never raises to the caller.

        Wafer->domain conversion deliberately does NOT use
        self.wafer.width_um: gate_stack builds geometry from its own
        independent gs_x_extent_var (self.wafer.width_um is never
        updated by run_gate_stack -- unlike etch/oxidation/deposition,
        which all read x_extent_um from self.wafer.width_um directly).
        The real domain width is measured from the actual mesh instead,
        matching this project's own centered-domain convention.
        """
        if not self.electrode_pins:
            messagebox.showinfo("Electrode", "No pins placed yet.")
            return None
        if self.last_final_mesh is None:
            messagebox.showinfo("Electrode", "No real mesh exists yet -- run a process step first.")
            return None

        from tcad.mesh.viennaps_adapter import build_process_result
        from tcad.device.devsim.contact_probe import (
            validate_pin_placement, find_duplicate_pin_positions, PinPlacementError,
        )
        from tcad.device.devsim.mesh_import import import_process_result

        process_result = build_process_result({"final_mesh": self.last_final_mesh, "snapshots": []})
        contactable = {r.name for r in process_result.material_regions if r.name not in ("SiO2", "Si3N4", "Mask")}

        duplicates = find_duplicate_pin_positions(self.electrode_pins)
        if duplicates:
            names = ", ".join(" & ".join(p.name for p in group) for group in duplicates)
            messagebox.showerror("Electrode", f"Pins at the same position: {names}")
            return None

        import meshio
        mesh = meshio.read(process_result.volume_mesh_path)
        real_width_um = float(mesh.points[:, 0].max() - mesh.points[:, 0].min())

        errors = []
        point_contacts = []
        half_width = real_width_um / 2.0
        for pin in self.electrode_pins:
            try:
                region = validate_pin_placement(process_result, pin, real_width_um, contactable)
                point_contacts.append({
                    "name": pin.name, "region": region,
                    "x_domain_um": pin.x_um - half_width, "y_um": pin.y_um,
                    "radius_um": 0.1,
                })
            except PinPlacementError as exc:
                errors.append(f"{exc.pin.name}: {exc.reason} -- {exc.detail}")

        if errors:
            messagebox.showerror("Electrode", "Invalid pin placement:\n\n" + "\n".join(errors))
            return None

        imported = import_process_result(
            process_result, mesh_name="gui_electrode_mesh", device_name="gui_electrode_device",
            point_contacts=point_contacts, length_scale_to_cm=1.0e-4,
            # Needed for setup_mosfet_potential_equation's own
            # interface_name -- the Si/SiO2 interface tying the Si
            # transport region to the oxide's potential-only region
            # (see run_dc_operating_point). Harmless when either
            # material is absent from this mesh (import_process_result
            # skips a pair with no matching regions/shared edges).
            interface_region_pairs=[("Si", "SiO2")],
        )
        self.last_electrode_import = imported
        # Which real MaterialRegion each contact actually landed on --
        # read by run_dc_operating_point() to tell a contact that is
        # genuinely on Si/SiO2 apart from one that resolved onto a
        # covering electrode (e.g. this device's own W/Cu/TiN pads),
        # which needs different handling there.
        self._electrode_contact_regions = {pc["name"]: pc["region"] for pc in point_contacts}
        self._log(f"\nElectrodes resolved: {sorted(imported.contacts)}\n")
        return imported

    def _on_resolve_pins_clicked(self):
        self.resolve_electrode_pins()

    def run_dc_operating_point(self, drain_voltage, gate_voltage, body_voltage=0.0):
        """Requires resolve_electrode_pins() to have already succeeded
        this session, and a Source/Drain/Gate pin (Body optional) to be
        among the resolved contacts. Contact names are the Pin names
        themselves (point_contacts in resolve_electrode_pins names each
        contact after its Pin's own `name` field)."""
        if self.last_electrode_import is None:
            messagebox.showinfo("Electrode", "Resolve pins first.")
            return None

        imported = self.last_electrode_import
        contacts_by_role = {p.role: p.name for p in self.electrode_pins}
        missing = [r for r in ("Source", "Drain", "Gate") if r not in contacts_by_role]
        if missing:
            messagebox.showerror(
                "Electrode",
                f"No pin with role {missing!r} among the resolved pins -- "
                f"a DC operating point needs Source, Drain and Gate pins "
                f"(Body optional).",
            )
            return None

        source_contact = contacts_by_role["Source"]
        drain_contact = contacts_by_role["Drain"]
        gate_contact = contacts_by_role["Gate"]
        body_contact = contacts_by_role.get("Body")
        for name in (source_contact, drain_contact, gate_contact) + (
            (body_contact,) if body_contact else ()
        ):
            if name not in imported.contacts:
                messagebox.showerror(
                    "Electrode",
                    f"Pin {name!r} did not resolve to a real DevSim contact "
                    f"(resolved contacts: {imported.contacts}).",
                )
                return None

        # Source/Drain/Body carry full electron/hole drift-diffusion
        # (solve_mosfet_dc_operating_point's own equilibrium+transport
        # stages), which only exists on the real Si region in this
        # project's device physics -- a pin that resolved onto a
        # COVERING electrode (e.g. this device's own W/Cu source/drain
        # pads) cannot be idealized around the way the gate below is:
        # confirmed by direct execution that giving such a region its
        # own potential-only equation gets it through the EQUILIBRIUM
        # stage, then fails once transport turns on ("Cannot find
        # equation index" for ElectronContinuityEquation) -- a metal
        # has no Electrons/Holes continuity equation in this project's
        # physics, so there is no complete fix, only a refusal that
        # says why.
        regions_by_name = self._electrode_contact_regions
        si_role_contacts = [("Source", source_contact), ("Drain", drain_contact)]
        if body_contact:
            si_role_contacts.append(("Body", body_contact))
        wrong_region = [
            (role, contact, regions_by_name.get(contact))
            for role, contact in si_role_contacts
            if regions_by_name.get(contact) != "Si"
        ]
        if wrong_region:
            detail = "; ".join(f"{role} ({contact!r}) is on {region!r}" for role, contact, region in wrong_region)
            messagebox.showerror(
                "Electrode",
                f"A DC operating point needs Source/Drain/Body contacts "
                f"directly on the silicon -- {detail}. Place these pins "
                f"on an exposed Si surface (not on a covering electrode "
                f"pad) and resolve again.",
            )
            return None

        from tcad.device.devsim import backend as devsim_backend
        from tcad.device.devsim.doping_mapping import apply_doping
        from tcad.mesh.interface import DopingProfile, DopingRegion
        from tcad.characterization.dc_operating_point import solve_mosfet_dc_operating_point

        module = devsim_backend.require_devsim()

        # A device this panel just built via resolve_electrode_pins()
        # carries no doping unless the Doping panel was run first on
        # the SAME mesh (its ProcessResult is rebuilt fresh from
        # self.last_final_mesh, doping is not stored in the mesh file
        # itself). CreateSiliconPotentialOnly's own equations reference
        # NetDoping unconditionally, so a solve needs SOME NetDoping
        # registered on the Si region -- if none was applied, this is
        # honestly zero (intrinsic Si), not an invented dopant level.
        doping = None
        doped_result = self.last_doped_result
        if (
            doped_result is not None
            and getattr(doped_result, "doping", None) is not None
            and getattr(doped_result, "volume_mesh_path", None) == self.last_final_mesh
        ):
            doping = doped_result.doping
        if doping is None:
            doping = DopingProfile(kind="uniform", regions=[DopingRegion(region="Si", net_doping_cm3=0.0)])
            self._log("\n(No doping profile applied yet -- Si region treated as intrinsic, NetDoping=0, for this solve.)\n")

        try:
            apply_doping(imported.device, doping, length_scale_to_cm=1.0e-4)

            gate_region = regions_by_name.get(gate_contact)
            if gate_region != "SiO2":
                # The Gate pin resolved to the real gate ELECTRODE (e.g.
                # TiN) rather than the buried oxide beneath it -- expected:
                # a real probe lands on the exposed metal, never on the
                # oxide it covers. The gate is potential-only in every
                # stage of this solve (no carrier transport, unlike
                # Source/Drain/Body above), so extending the SAME
                # idealized-contact treatment mosfet_equation.py already
                # uses for the real oxide onto this region is a complete
                # fix, not a partial one -- confirmed by direct execution
                # that it converges through both the equilibrium AND
                # drift-diffusion stages.
                from devsim.python_packages.simple_physics import (
                    SetOxideParameters, CreateOxidePotentialOnly, CreateOxideContact,
                )
                SetOxideParameters(imported.device, gate_region, 300.0)
                CreateOxidePotentialOnly(imported.device, gate_region, "log_damp")
                CreateOxideContact(imported.device, gate_region, gate_contact)

            op_point = solve_mosfet_dc_operating_point(
                device=imported.device, si_region="Si", oxide_region="SiO2",
                source_contact=source_contact, drain_contact=drain_contact,
                gate_contact=gate_contact, interface_name="Si_SiO2_interface",
                drain_voltage=drain_voltage, gate_voltage=gate_voltage,
                body_contact=body_contact, body_voltage=body_voltage,
            )
        except Exception as exc:
            messagebox.showerror("Electrode", f"DC operating point solve failed:\n\n{exc}")
            return None
        finally:
            try:
                module.delete_device(device=imported.device)
                module.delete_mesh(mesh=imported.mesh)
            except Exception:
                pass
            self.last_electrode_import = None

        self._log(
            f"\n================================\n"
            f"DC OPERATING POINT\n"
            f"================================\n"
            f"Vd={drain_voltage:+.4f}V Vg={gate_voltage:+.4f}V Vb={body_voltage:+.4f}V\n"
            f"currents={op_point.currents}\n"
        )
        messagebox.showinfo(
            "Electrode",
            f"DC operating point solved.\n\ncurrents={op_point.currents}",
        )
        return op_point

    def _on_dc_operating_point_clicked(self):
        try:
            vd = float(self.dc_drain_v_var.get())
            vg = float(self.dc_gate_v_var.get())
            vb = float(self.dc_body_v_var.get())
        except ValueError:
            messagebox.showerror("Electrode", "Drain/Gate/Body V must be numeric.")
            return
        self.run_dc_operating_point(drain_voltage=vd, gate_voltage=vg, body_voltage=vb)

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    def _make_log_panel(
        self,
        parent,
    ):

        T = Tokens
        frame = ttk.Frame(parent, style="Inspector.TFrame", padding=(10, 4, 10, 8))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="LOG / CONSOLE", style="Section.TLabel").pack(anchor="w")

        self.log = tk.Text(
            frame,
            height=7,
            state="disabled",
            bg=T.BG_2, fg=T.FG,
            insertbackground=T.FG,
            selectbackground=T.ACCENT_DIM,
            highlightthickness=1,
            highlightbackground=T.LINE,
            relief="flat",
            padx=6, pady=4,
            font=(T.FONT_DATA, 9),
        )

        self.log.pack(fill="both", expand=True, pady=(2, 0))

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
        # Dense inspector row: small muted caption label, monospace
        # value entry directly beneath it -- every one of the 7 category
        # panels (litho/etch/oxidation/deposition/gate_stack/doping/
        # measurement) builds its parameter rows through this ONE
        # helper, so retheming it here restyles all of them at once.
        ttk.Label(
            parent,
            text=label,
            style="Caption.TLabel",
        ).pack(
            anchor="w",
            padx=12,
            pady=(6, 1),
        )

        variable = tk.StringVar(
            value=str(value)
        )

        ttk.Entry(
            parent,
            textvariable=variable,
        ).pack(
            fill="x",
            padx=12,
        )

        return variable

    #: Curated subset of vps.Material -- the full enum has ~80 entries
    #: (see viennaps.Material), most irrelevant to a 2D Si process flow.
    #: These are what this project's own recipes/tests already deposit
    #: or reference (SiO2, Si3N4, PolySi, W, TiN, Cu -- see
    #: gate_stack.py and material_colors in redraw()) plus a generic
    #: "Metal" for a sputter target with no specific alloy chosen.
    #: Every entry verified present in ViennaPS 4.6.2's own Material
    #: enum. Si/SiGe/aSi are here for selective epitaxy, which grows
    #: semiconductor rather than a film: Si is homoepitaxy (and, being
    #: the same material as the substrate, simply merges into it), SiGe
    #: is the heteroepitaxial case that needs its own region.
    _DEPOSITION_MATERIAL_OPTIONS = [
        "SiO2", "Si3N4", "PolySi", "Si", "SiGe", "aSi",
        "W", "TiN", "Cu", "Metal", "Ta", "Ti",
    ]

    #: The material tag lithographic PHOTORESIST is represented as in
    #: real ViennaPS geometry -- deliberately NOT "Mask". LOCOS's own
    #: hard mask, and any other permanent mask, keeps using "Mask"
    #: unchanged (see run_oxidation's `is_locos` branch, which sets
    #: mask_material="Mask" explicitly AFTER _mask_recipe_keys() runs).
    #:
    #: Root cause this exists to fix, measured directly against real
    #: ViennaPS 4.6.2 (see docs/investigation_log.md, "PR Strip removes
    #: nothing"): resist and LOCOS's hard mask both used to be tagged
    #: Material.Mask, so PR STRIP had no way to remove ONLY the resist
    #: without also risking a permanent hard mask, and settled for
    #: removing neither (state-flags only). "PHS" (polyhydroxystyrene,
    #: a real photoresist base polymer -- confirmed present in ViennaPS
    #: 4.6.2's own Material enum) was chosen over the more obvious
    #: "Polymer" because Polymer is NOT free: Bosch DRIE
    #: (bosch_drie.py) and Fluorocarbon etching (fluorocarbon.py) both
    #: already use Material.Polymer for their OWN passivation chemistry
    #: -- tagging resist as Polymer would silently collide with those
    #: models' own bookkeeping. Confirmed PHS is used nowhere else in
    #: this codebase before adopting it here.
    _RESIST_MATERIAL = "PHS"

    #: Deposition/Metallization "mode" toggle labels -- see
    #: tcad/process/deposition/isotropic.py's own comment for why a
    #: SEPARATE recipe key (deposit_exclude_material) was needed rather
    #: than reusing mask_material for this. Blanket is the default for
    #: both panels: it matches the physically common case (a film that
    #: is later patterned by a SEPARATE etch, not one that already
    #: excludes the mask during growth) and, for Metallization
    #: specifically, matches its own existing help text's claim of
    #: lift-off geometry.
    _DEPOSITION_MODE_BLANKET = "Blanket (deposits over mask)"
    _DEPOSITION_MODE_SELECTIVE = "Selective (masked regions excluded)"

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
            style="Caption.TLabel",
        ).pack(
            anchor="w",
            padx=12,
            pady=(6, 1),
        )

        variable = tk.StringVar(value=default)

        ttk.Combobox(
            parent,
            textvariable=variable,
            state="readonly",
            values=self._DEPOSITION_MATERIAL_OPTIONS,
        ).pack(
            fill="x",
            padx=12,
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
            # Resist, not a hard mask -- see _RESIST_MATERIAL. LOCOS's
            # own branch (run_oxidation) overwrites this back to "Mask"
            # for its real hard mask, so this default is safe for it.
            "mask_material": self._RESIST_MATERIAL,
        }

    def _mask_recipe_keys_for_current_step(self):
        """Mask portion of a recipe, aware of whether the step about to
        run will build a FRESH wafer or continue an already-processed
        one -- a real fab flow masks, etches, oxidizes and deposits in
        whatever order the design needs (see CLAUDE.md's PN-junction-diode
        textbook flow: oxidation -> lithography -> doping ->
        metallization -> lithography again), and each of those
        lithography steps must apply to the ACTUAL current topology, not
        just the original wafer.

        `_mask_recipe_keys()` only ever produces mask_left_um/mask_right_um
        /mask_spans_um, which `prepare_domain()` only honours when
        building a FRESH domain -- on an inherited (chained) domain they
        are silently ignored (with a warning). `remask_spans_um` is the
        counterpart for that case (see session.remask_domain(), built
        for gate patterning earlier and reused here verbatim: same
        mechanism, same "apply a new mask on top of whatever geometry
        already exists" need, no reason for etch/deposition to need a
        second implementation of it).

        Whether THIS step will be fresh or chained isn't known from the
        step alone -- it depends on whether anything already ran or is
        already queued ahead of it (self.completed_steps / self.flow_steps),
        exactly the same condition _chained_flow_config() uses to decide
        what a standalone RUN click continues from.

        REAL BUG, found by the user actually running deposition after an
        earlier step and getting a mask (and the shape of an earlier
        step) they never asked for: this used to return remask_spans_um
        UNCONDITIONALLY for any chained step, derived from
        self.wafer.mask_openings_um -- a value that persists from
        whatever it last was (GUI default, or a previous litho session)
        and never clears itself. So every chained etch/deposition
        silently re-masked using stale/default litho state, whether or
        not the user had touched Lithography for THIS step. Worse,
        deposition's own duplicateTopLevelSet() (see run_deposition())
        duplicates the domain's CURRENT top level set -- which the
        just-inserted mask now was -- so the "new" material's starting
        shape was the mask box, not the real prior surface: this is
        also why an unrelated earlier step's geometry appeared to
        "come back."

        Both questions are now answered from ONE place, `_resist_spans_um()`
        -- the real resist state -- instead of each process panel deciding
        for itself from GUI defaults. See that method for the table and
        for what the defaults-driven version actually produced.
        """
        spans = self._resist_spans_um()
        is_first_step = not (self.completed_steps or self.flow_steps)

        if spans is None:
            # No resist on the wafer. A process step is not a lithography
            # step: it must not invent one. On a FRESH wafer that means
            # the explicit bare-wafer recipe (`mask_spans_um: []`, this
            # project's own convention -- see prepare_domain()); on an
            # inherited domain it means no mask keys at all, which
            # prepare_domain() already treats as "continue untouched".
            return {"mask_spans_um": []} if is_first_step else {}

        if is_first_step:
            return {
                "mask_left_um": self.wafer.mask_left_um,
                "mask_right_um": self.wafer.mask_right_um,
                "mask_spans_um": spans,
                "mask_material": self._RESIST_MATERIAL,
            }
        return {"remask_spans_um": spans, "mask_material": self._RESIST_MATERIAL}

    def _note_if_blanket_resist(self, action: str) -> None:
        """Record — never block — that a step will be masked everywhere.

        An undeveloped blanket resist covers the whole wafer, so this
        step is masked at every x and leaves the geometry unchanged.
        That is the physically correct consequence, but with no
        explanation it looks like the button did nothing.

        This is a LOG note, not a dialog and not a return value. A modal
        confirm is still a block, and telling the user to run a
        different step first is still a prescribed order: the user picks
        a process, that process runs on the current wafer, and the
        result is whatever it physically is.
        """
        if self.wafer.pr_present and not self.wafer.developed:
            self._log(
                f"\nNOTE: an undeveloped blanket photoresist covers the whole "
                f"wafer, so this {action} is masked everywhere and the wafer "
                f"geometry will not change.\n"
            )

    def _resist_spans_um(self):
        """The OPAQUE resist spans implied by the wafer's CURRENT resist
        state, or None when the wafer carries no resist at all.

        This is the single source of truth for "what is the resist doing
        right now", read by both the recipe builder
        (_mask_recipe_keys_for_current_step) and the canvas overlay
        (redraw). Sharing it is the point: while the two derived resist
        shape independently, what was drawn and what was simulated could
        disagree, and did.

            resist state            -> spans returned
            ------------------------------------------------------------
            no resist               -> None      (no mask at all)
            coated, not developed   -> ONE full-width span (blanket film)
            developed               -> opaque complement of the openings

        The middle row is the one that was missing, and its absence is
        what made PR COAT behave as coat+align+expose+develop in one
        click. Verified against real ViennaPS 4.6.2 before this existed:
        oxidation -> PR COAT (nothing else) -> deposition put `Mask` only
        OUTSIDE mask_openings_um and deposited Si3N4 only INSIDE them --
        an already-developed pattern produced by a bare coat.

        A blanket coat needs no new geometry path: mask_spans_from_openings
        with NO openings already returns exactly one span covering the
        whole wafer (its own documented behavior, and what
        tests/unit/test_mask_spans_from_openings_mock.py pins).
        """
        from tcad.process.base import mask_spans_from_openings

        if not self.wafer.pr_present:
            return None

        openings = self.wafer.mask_openings_um if self.wafer.developed else []
        return [
            list(span)
            for span in mask_spans_from_openings(openings, self.wafer.width_um)
        ]

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

        Also refreshes the bottom Process Flow Timeline's completed-step
        chips (see _refresh_completed_timeline) -- called here rather
        than threaded through every individual run_*() success path
        because this method is ALREADY called from every one of them,
        plus reset(), so it is the one existing hook guaranteed to run
        exactly when self.completed_steps changes.

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

        # Doping is a process category like any other, so it is never
        # greyed out. It used to be disabled until some other process
        # had produced a mesh, which is a prerequisite by another name:
        # the button simply looked broken, with no way to find out why.
        # run_doping() now exports the current wafer itself when no mesh
        # exists yet (see _materialize_current_wafer).
        self.doping_button.configure(state="normal")

        # Device measurement is characterization, not a process step, and
        # a solve genuinely has nothing to work with until a doping
        # profile exists. It stays clickable so pressing it explains
        # that (see run_measurement) instead of silently doing nothing.
        self.measure_button.configure(state="normal")

        if hasattr(self, "_refresh_completed_timeline"):
            self._refresh_completed_timeline()

    def process_pr_coat(self):
        # No stage gate -- see run_etch()'s own matching comment. This
        # was the last of the litho micro-steps still hard-gated to
        # "only from a pristine, untouched wafer" (process_stage ==
        # "wafer" literally), so once ANY other step ran once, this
        # button could never fire again -- silently, with no error, no
        # log line, nothing -- exactly contradicting the same
        # "processes work in any order" requirement etch/oxidation/
        # deposition/PR strip were already relaxed for.
        #
        # This button is the ONLY thing that puts resist on the wafer,
        # and resist is the only thing that lets a later step be masked
        # (see _resist_spans_um()). What it puts there is a BLANKET
        # film; mask_openings_um does not enter the picture until
        # DEVELOP. Not clicking it means no mask, which is what makes a
        # plain oxidation/deposition/etch blanket.
        if not self._read_lithography_fields():
            return

        # Coating puts resist on the whole wafer and nothing else. The
        # three flags below are the whole point: a coat must also CLEAR
        # any leftover state from a previous lithography cycle, because
        # `developed` used to be set once and never reset except by NEW
        # WAFER -- so coat -> develop -> strip -> coat left the fresh
        # coat already "developed", in the recipe and on the canvas.
        self.wafer.pr_present = True
        self.wafer.developed = False
        self.wafer.stripped = False

        self.process_stage = "pr_coated"
        self.history.append("PR coat")
        self._mark_stage_done(2)
        self._log(
            "\nSTEP: PR COAT\n"
            f"PR thickness = {self.wafer.pr_thickness_um} um\n"
            "Blanket resist over the whole wafer (no pattern yet -- "
            "DEVELOP is what opens it)."
        )
        self._update_process_buttons()
        self.redraw()

    def process_mask_alignment(self):
        if not self._read_lithography_fields():
            return

        # Aligning a photomask changes no wafer geometry and no resist
        # state -- the mask is process INPUT, not something that gets
        # added to the wafer. Only the selected window changes.
        self.process_stage = "aligned"
        self.history.append("Mask alignment")
        self._mark_stage_done(3)
        self._log(
            "\nSTEP: MASK ALIGNMENT\n"
            f"Opening = "
            f"{self.wafer.mask_right_um - self.wafer.mask_left_um} um\n"
            "Mask is process input; wafer geometry unchanged."
        )
        self._update_process_buttons()
        self.redraw()

    def process_exposure(self):
        if not self._read_lithography_fields():
            return

        if not self.wafer.pr_present:
            # A result, not a refusal, and no instruction to run some
            # other step first: the step ran against the wafer as it is
            # and had nothing to act on.
            self._log(
                "\nSTEP: EXPOSURE\n"
                "There is no photoresist on the wafer, so there is nothing "
                "to expose. Nothing changed.\n"
            )

        # Exposure changes resist CHEMISTRY, not geometry: nothing is
        # removed until DEVELOP.
        self.process_stage = "exposed"
        self.history.append("Exposure")
        self._mark_stage_done(4)
        self._log(
            "\nSTEP: EXPOSURE\n"
            f"Dose = {self.wafer.exposure_dose}\n"
            "Latent image only; resist geometry unchanged until develop."
        )
        self._update_process_buttons()
        self.redraw()

    def process_develop(self):
        if not self.wafer.pr_present:
            self._log(
                "\nSTEP: DEVELOP\n"
                "There is no photoresist on the wafer, so there is nothing "
                "to develop. Nothing changed.\n"
            )
            self._update_process_buttons()
            self.redraw()
            return

        # First and only lithography step that changes resist GEOMETRY.
        self.wafer.developed = True
        self.process_stage = "developed"
        self.history.append("Develop")
        self._mark_stage_done(5)
        self._log(
            "\nSTEP: DEVELOP\n"
            f"Develop time = {self.wafer.develop_time_s} s\n"
            "Developed PR opening is now the etch mask."
        )
        self._update_process_buttons()
        self.redraw()

    def process_pr_strip(self):
        if not self.wafer.pr_present:
            self._log(
                "\nSTEP: PR STRIP\n"
                "There is no photoresist on the wafer to strip. "
                "Nothing changed.\n"
            )
            self._update_process_buttons()
            self.redraw()
            return

        # If resist ever became real geometry (some real step ran since
        # it was coated -- see _RESIST_MATERIAL), remove it from the
        # live domain too, not just the state flags below. Only PHS
        # (resist) is targeted; LOCOS's own hard mask stays "Mask" and
        # is never touched by this.
        if self.last_domain_state and Path(self.last_domain_state).exists():
            if not self._strip_resist_from_geometry():
                return

        self.wafer.pr_present = False
        self.wafer.developed = False
        self.wafer.stripped = True
        self.process_stage = "stripped"
        self.history.append("PR strip")
        self._mark_stage_done(7)
        self._log(
            "\nSTEP: PR STRIP\n"
            "Resist removed from the process state and, where it had "
            "become real geometry, from the wafer itself.\n"
        )
        self._update_process_buttons()
        self.redraw()

    # --------------------------------------------------------
    # ETCH OPERATION
    # --------------------------------------------------------

    def _log_etch_material_summary(self, pre_mesh_path, post_mesh_path, open_windows_um):
        """Log, per material, how much moved in the OPEN (unmasked)
        window(s) between two real exported meshes -- so the user can
        see whether an etch reached a given material without having to
        infer it from the render alone. Never changes what the etch
        DID (see docs/investigation_log.md, "Etch is correct, GUI
        gives no feedback about whether the target material was
        reached") -- this is diagnostic only.
        """
        if not open_windows_um:
            self._log("\n(No open window -- resist fully covers the wafer, nothing exposed to etch.)\n")
            return
        try:
            import meshio

            def read(path):
                m = meshio.read(path)
                tri = next(c for c in m.cells if c.type == "triangle")
                tags = m.cell_data["Material"][m.cells.index(tri)]
                names = {}
                for attr in dir(viennaps_session.require_viennaps().Material):
                    if attr.startswith("_"):
                        continue
                    v = getattr(viennaps_session.require_viennaps().Material, attr)
                    if isinstance(v, viennaps_session.require_viennaps().Material):
                        names[int(v)] = attr
                pts = m.points
                by_mat = {}
                for t, tag in zip(tri.data, tags):
                    by_mat.setdefault(names.get(int(tag), str(tag)), []).append(t)
                return pts, by_mat

            def top_in_window(pts, by_mat, material, lo, hi):
                node_idxs = set()
                for t in by_mat.get(material, []):
                    node_idxs.update(t)
                ys = [pts[n][1] for n in node_idxs if lo <= pts[n][0] <= hi]
                return max(ys) if ys else None

            pts_pre, by_mat_pre = read(pre_mesh_path)
            pts_post, by_mat_post = read(post_mesh_path)
            materials = sorted(set(by_mat_pre) | set(by_mat_post))
            noise_floor_um = 0.001

            lines = ["\nETCH RESULT BY MATERIAL (open window only):"]
            for lo, hi in open_windows_um:
                lines.append(f"  Window x=[{lo:.3f}, {hi:.3f}]:")
                for material in materials:
                    before = top_in_window(pts_pre, by_mat_pre, material, lo, hi)
                    after = top_in_window(pts_post, by_mat_post, material, lo, hi)
                    if before is None and after is None:
                        continue
                    if after is None:
                        lines.append(f"    {material}: fully cleared (was present, now gone here)")
                    elif before is None:
                        lines.append(f"    {material}: newly exposed here (top={after:.4f})")
                    else:
                        moved = before - after
                        if abs(moved) < noise_floor_um:
                            status = "unchanged (not yet reached)" if material == "Si" else "unchanged"
                            lines.append(f"    {material}: {status} (top={after:.4f})")
                        else:
                            lines.append(f"    {material}: etched {moved:.4f}um (top {before:.4f} -> {after:.4f})")
            self._log("\n".join(lines) + "\n")
        except Exception as exc:
            # Diagnostic-only: never let this block or corrupt a real
            # etch result.
            self._log(f"\n(Could not compute the etch material summary: {exc!r})\n")

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

        self._note_if_blanket_resist("etch")

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

                # Fresh wafer -> mask_left_um/mask_right_um/mask_spans_um
                # (MakeTrench/make_mask_spans); chained onto an earlier
                # step -> remask_spans_um instead, so a mask applied
                # mid-flow (see _mask_recipe_keys_for_current_step) isn't
                # silently ignored the way it used to be.
                **self._mask_recipe_keys_for_current_step(),

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
                })

            elif model_key == "isotropic":

                recipe.update({
                    "rate":
                        -abs(float(
                            self.isotropic_rate_var.get()
                        )),
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
        # Captured BEFORE being overwritten below: this is the real,
        # per-material-tagged volume mesh the wafer had going INTO this
        # etch (the previous step's export, or None on a fresh wafer's
        # first-ever step). `result["snapshots"]` is deliberately NOT
        # used here -- those are raw saveSurfaceMesh() .vtp snapshots
        # with no Material cell_data at all, so they cannot feed
        # _log_etch_material_summary()'s volume-mesh reader.
        pre_etch_mesh = self.last_final_mesh
        resist_spans = self._resist_spans_um()
        self.last_final_mesh = result.get("final_mesh")
        if pre_etch_mesh and result.get("final_mesh"):
            from tcad.physics.doping import implant_windows_from_mask_spans
            open_windows_domain_um = [
                [w["min_um"], w["max_um"]]
                for w in implant_windows_from_mask_spans(
                    resist_spans if resist_spans is not None else [],
                    self.wafer.width_um, conc_cm3=0.0,
                )
            ]
            self._log_etch_material_summary(
                pre_etch_mesh, result["final_mesh"], open_windows_domain_um,
            )
        self.completed_steps.append(recipe)
        self.last_domain_state = result.get("domain_state")
        self.last_physics_status = result.get("physics_status")
        self._log_physics_status(result)
        # Keep flow_step_meshes aligned index-for-index with
        # completed_steps (see run_process_flow's own comment) so the
        # bottom timeline can show this step's geometry on click even
        # when it was run as a standalone RUN click, not via RUN
        # PROCESS FLOW.
        self.flow_step_meshes.append(self.last_final_mesh)

        self._mark_stage_done(6)

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

    def _quantized_depth_budget(self, key, depth_um):
        """Monotonically-non-decreasing, coarsely-quantized version of
        a real mesh depth, used ONLY to pick the render scale.

        `key` is "above" or "below" (self._viewer_depth_budget_um,
        reset on NEW WAFER). The stored budget only grows, and only
        when the real depth exceeds it by more than 5% -- and then it
        grows with 20% headroom, not to the exact new depth -- so
        small real fluctuations (sub-percent, or a one-off single-digit
        percent growth) reuse the existing scale instead of triggering
        a redraw-to-redraw rescale. A genuinely large growth still
        rescales (correctly -- the drawing must compress to keep
        fitting), just in coarse, infrequent steps instead of
        continuously drifting. Always returns >= depth_um, so the
        canvas can never overflow.
        """
        budget = self._viewer_depth_budget_um.get(key, 0.0)
        if depth_um > budget * 1.05:
            budget = depth_um * 1.2
            self._viewer_depth_budget_um[key] = budget
        return max(budget, depth_um)

    @staticmethod
    def _material_surface_profile(triangle_data, points, tags, material_tag, x_min, x_max, n_buckets=60):
        """Per-x (bucketed) (x_lo, x_hi, y_top, y_bot) for one material
        tag, from real mesh triangle/point data. Pure function -- no
        canvas, no Tk -- so it is unit-testable without a display and
        reusable for both the doping-tint overlay and, later, any
        other per-x-aware drawing.

        Replaces computing ONE global (min, max) over every node of
        the material and drawing a single rectangle across the WHOLE
        x-range, which over-paints wherever the real surface height
        varies across x (see docs/investigation_log.md, "renderer
        draws doping color using a global bounding box").
        """
        if x_max <= x_min:
            return []
        bucket_width = (x_max - x_min) / n_buckets
        tops = [None] * n_buckets
        bots = [None] * n_buckets

        def bucket_of(x):
            idx = int((x - x_min) / bucket_width)
            return min(max(idx, 0), n_buckets - 1)

        for tri, tag in zip(triangle_data, tags):
            if int(tag) != material_tag:
                continue
            for n in tri:
                x, y = points[n][0], points[n][1]
                b = bucket_of(x)
                if tops[b] is None or y > tops[b]:
                    tops[b] = y
                if bots[b] is None or y < bots[b]:
                    bots[b] = y

        segments = []
        for b in range(n_buckets):
            if tops[b] is None:
                continue
            segments.append(
                (x_min + b * bucket_width, x_min + (b + 1) * bucket_width, tops[b], bots[b])
            )
        return segments

    def _draw_real_mesh_result(self, canvas, x0, x1, surface_y, bottom_y, mesh_path=None):
        """Draw a real ViennaPS mesh (.vtu volume mesh) instead of the
        placeholder rectangle in redraw(). Returns True on success;
        False if the mesh can't be read (meshio/ViennaPS unavailable,
        file missing, no triangle cells, degenerate bounds, etc.), so
        the caller falls back to the placeholder in that case -- this
        must never raise.

        mesh_path : which mesh to draw. Defaults to self.last_final_mesh
        (the real current wafer) when None -- every existing caller
        keeps that behavior unchanged. The Process Flow Timeline (see
        _view_flow_step) passes an EARLIER step's own mesh instead, so
        clicking a timeline chip shows that step's real geometry without
        touching self.last_final_mesh or any process state.

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
        mesh_path = mesh_path if mesh_path is not None else self.last_final_mesh
        if not mesh_path or not Path(mesh_path).exists():
            return False

        try:
            import meshio

            if not viennaps_session.is_available():
                return False
            module = viennaps_session.require_viennaps()

            mesh = meshio.read(mesh_path)
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
            # Use a QUANTIZED depth budget, not the raw mesh depth, so
            # a real but tiny growth (this project measured SiO2
            # thickness changing by ~0.003um -- numerical noise -- while
            # y_max still crept up across a 40x deposition-time
            # increase) doesn't silently rescale the WHOLE drawing on
            # every redraw. A single shared y_scale maps both the
            # growing top layer and the unchanged lower layers, so any
            # rescale visually compresses layers that did not change --
            # reading as "the substrate eroded" even though the raw
            # mesh, checked directly, shows it did not (see
            # docs/investigation_log.md, "Deposition: renderer y-scale
            # artifact"). The physics/mesh are untouched; only which
            # SCALE the renderer picks changes.
            depth_below = self._quantized_depth_budget("below", depth_below)
            depth_above = self._quantized_depth_budget("above", depth_above)
            y_scale = x_scale
            if depth_below > 1e-9:
                y_scale = min(y_scale, available_below / depth_below)
            if depth_above > 1e-9:
                y_scale = min(y_scale, available_above / depth_above)

            # Real mesh coordinates for the cursor readout (_on_canvas_motion)
            # and the ruler (redraw()) -- overwrites the wafer-coordinate
            # default redraw() set before calling this function.
            self._viewer_scale = (x0, x_min, x_scale, surface_y, y_scale)

            material_colors = self._MATERIAL_COLORS
            material_names = {}

            def to_canvas(node_idx):
                px, py = points[node_idx][0], points[node_idx][1]
                return x0 + (px - x_min) * x_scale, surface_y - py * y_scale

            by_material = {}
            for idx, tag in enumerate(tags):
                by_material.setdefault(tag, []).append(idx)

            # Real current top surface, in wafer-x (um) -> mesh-y (um),
            # binned coarsely (40 bins across the mesh width -- this is
            # for POSITIONING a GUI guide overlay, not physics, so it
            # doesn't need grid-cell resolution). redraw()'s mask-window
            # guide uses this to sit the PR block on the ACTUAL current
            # surface instead of the original y=0 datum -- using y=0
            # unconditionally is what let a PR block draw partly
            # overlapping/underneath real oxide that had already grown
            # above y=0 (found by direct visual inspection, not assumed).
            n_bins = 40
            bin_top = [-1e18] * n_bins
            bin_w = (x_max - x_min) / n_bins if x_max > x_min else 1.0
            for tri in triangle_data:
                for node_idx in tri:
                    px, py = points[node_idx][0], points[node_idx][1]
                    b = max(0, min(n_bins - 1, int((px - x_min) / bin_w)))
                    if py > bin_top[b]:
                        bin_top[b] = py

            def _real_top_um(x_um):
                b = max(0, min(n_bins - 1, int((x_um - x_min) / bin_w)))
                v = bin_top[b]
                return v if v > -1e17 else 0.0

            self._real_mesh_top_um = _real_top_um

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

            # MESH overlay (toolbar checkbox, see _make_header): the raw
            # triangle edges on top of the material fill -- a display
            # toggle only, drawn from the same triangle_data already
            # read above, no new mesh data.
            if self.mesh_overlay_var.get():
                # Same decimation cap as the per-triangle fallback fill
                # above -- an unrefined region can carry tens of
                # thousands of triangles, and drawing every edge as its
                # own canvas item would freeze the GUI, not just be slow.
                for tag, indices in by_material.items():
                    draw_indices = indices
                    if len(draw_indices) > _MAX_RENDERED_TRIANGLES:
                        draw_indices = rng.sample(draw_indices, _MAX_RENDERED_TRIANGLES)
                    for i in draw_indices:
                        coords = []
                        for node_idx in triangle_data[i]:
                            coords.extend(to_canvas(node_idx))
                        canvas.create_polygon(
                            coords, fill="", outline=Tokens.BG_0, width=1,
                        )

            # p/n doping overlay: a translucent red (p-type, net
            # negative) / blue (n-type, net positive) tint over whatever
            # doped region(s) exist, so a doping change is visible on
            # screen instead of only in the log. Drawn last so it sits
            # on top of the material fill; stipple keeps the material
            # silhouette underneath legible rather than hiding it.
            # Layer-gated: only the DOPING layer shows this tint (see
            # the viewer's layer switch, _make_cross_section) -- GEOMETRY
            # shows the bare material fill, matching what each layer
            # name promises.
            if self.viewer_layer_var.get() == "doping" and self.last_doped_result is not None and getattr(
                self.last_doped_result, "doping", None
            ) is not None:
                for region_name in {r.region for r in self.last_doped_result.doping.regions}:
                    region_tag = next(
                        (t for t, n in material_names.items() if n == region_name),
                        None,
                    )
                    if region_tag is None:
                        continue
                    profile = self._material_surface_profile(
                        triangle_data, points, tags, region_tag, x_min, x_max,
                    )
                    if not profile:
                        continue

                    for x_lo_um, x_hi_um, color in self._doping_color_segments(
                        region_name, x_min, x_max
                    ):
                        if x_hi_um <= x_lo_um:
                            continue
                        for seg_x_lo, seg_x_hi, seg_y_top, seg_y_bot in profile:
                            # Intersect this surface bucket with the
                            # doping color segment's own x-range (e.g.
                            # step_junction only tints one side).
                            lo = max(seg_x_lo, x_lo_um)
                            hi = min(seg_x_hi, x_hi_um)
                            if hi <= lo:
                                continue
                            cx_lo = x0 + (lo - x_min) * x_scale
                            cx_hi = x0 + (hi - x_min) * x_scale
                            cy_top = surface_y - seg_y_top * y_scale
                            cy_bot = surface_y - seg_y_bot * y_scale
                            canvas.create_rectangle(
                                cx_lo, cy_top, cx_hi, cy_bot,
                                fill=color, outline="", stipple="gray50",
                            )

            canvas.create_text(
                x0 + 5, surface_y + 12,
                text="REAL VIENNAPS MESH",
                anchor="w", fill=Tokens.FG_DIM,
                font=(Tokens.FONT_UI, 8, "italic"),
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

        # Viewing-step indicator -- the viewer's own toolbar header
        # (_make_cross_section) already carries the static title, so
        # this line is reserved for what the old static title used to
        # sit on top of: a note when the canvas is showing an EARLIER
        # Process Flow Timeline step instead of the live wafer state
        # (see _view_flow_step).
        if self._viewing_step_index is not None:
            step_no = self._viewing_step_index + 1
            canvas.create_text(
                x0, 14, anchor="w",
                text=f"VIEWING STEP {step_no:02d} / {len(self.completed_steps):02d}"
                     "  —  click LIVE on the timeline below to return",
                fill=Tokens.ACCENT, font=(Tokens.FONT_UI, 9, "bold"),
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
        # Which mesh the VIEWER shows -- the real current wafer, unless
        # the user clicked an earlier Process Flow Timeline chip (see
        # _view_flow_step), in which case that step's own real mesh is
        # shown instead. Purely a display choice: self.last_final_mesh
        # (what doping/measurement actually operate on) is untouched
        # either way.
        display_mesh = self.last_final_mesh
        if self._viewing_step_index is not None and 0 <= self._viewing_step_index < len(self.flow_step_meshes):
            display_mesh = self.flow_step_meshes[self._viewing_step_index]

        # Whether a REAL PHYSICAL mesh exists to draw -- mesh existence
        # only. This must never depend on lithography UI state (PR
        # COAT/ALIGN/EXPOSURE/DEVELOP change wafer.pr_present/developed
        # and process_stage, never last_final_mesh) -- conflating the
        # two used to make PR COAT after a real process (e.g. real
        # oxidation) hide the real SiO2/doping under a blank placeholder,
        # even though nothing was actually lost. Litho-stage visuals
        # (PR film / mask box / UV rays) are drawn independently, below,
        # positioned on top of whatever real_mesh_available finds here.
        real_mesh_available = bool(
            self.wafer.processed
            and display_mesh
            and Path(display_mesh).exists()
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
        # Resist comes from the wafer's real resist state, not from the
        # stage string: a stage list said "resist exists" for `etched`/
        # `oxidized`/`deposited` too, which is a guess about what the
        # user did rather than a record of it.
        pr_present = self.wafer.pr_present
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

        # Default cursor-readout scale (wafer coords, 0..width_um) --
        # _draw_real_mesh_result overwrites this with the real mesh's
        # own (centred) coordinate system when it succeeds, later below.
        self._viewer_scale = (x0, 0.0, scale, surface_y, scale)

        # --- micron ruler (top edge) ---------------------------------
        # Wafer-coordinate ticks (0..width_um) -- exact for the litho
        # placeholder drawn below; a reasonable guide even once a real
        # mesh is drawn on top (its own x_extent_um is normally the same
        # value this wafer was built with). The cursor readout
        # (_on_canvas_motion) is what needs to be numerically exact, and
        # it always uses the real mesh's own scale once one exists.
        T = Tokens
        ruler_y = 34
        canvas.create_line(x0, ruler_y, x1, ruler_y, fill=T.LINE_STRONG)
        step_um = _nice_ruler_step(self.wafer.width_um)
        tick = 0.0
        while tick <= self.wafer.width_um + 1e-9:
            tx = x0 + tick * scale
            canvas.create_line(tx, ruler_y - 4, tx, ruler_y + 4, fill=T.LINE_STRONG)
            canvas.create_text(
                tx, ruler_y - 12, text=f"{tick:g}", fill=T.FG_DIM,
                font=(T.FONT_DATA, 7), anchor="s",
            )
            tick += step_um
        canvas.create_text(
            x1, ruler_y - 12, text="µm", fill=T.FG_DIM,
            font=(T.FONT_DATA, 7, "italic"), anchor="s",
        )

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

        # Litho-stage placeholder visuals (PR film / mask / opening) --
        # gated on `not real_mesh_available`, same rule the flat Si
        # placeholder rectangle already follows above. Pre-existing
        # behavior before this redesign drew these UNCONDITIONALLY, so
        # e.g. a real post-oxidation mesh (process_stage "oxidized" is
        # in `pr_present`'s stage list) had a pink PR block floating
        # over the real ViennaPS silhouette -- confirmed by actually
        # running a real oxidation through the redesigned GUI, not
        # assumed. Once a real mesh exists it already shows whatever
        # PR/mask/oxide state is real, so the placeholder no longer
        # applies, exactly like the Si rectangle's own case.
        if not real_mesh_available and pr_present and not opening_open:

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

        if not real_mesh_available and mask_present:

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

        if not real_mesh_available and opening_open:

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
            if not self._draw_real_mesh_result(canvas, x0, x1, surface_y, bottom_y,
                                                mesh_path=display_mesh):
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

        # Current PR/mask, drawn as real solid material -- on top of the
        # REAL mesh's ACTUAL current surface once one exists, not a
        # fixed y=0 datum. This is the same "PR fills the gaps between
        # mask openings" picture the pre-real-mesh placeholder above
        # already draws (that block stays exactly as it was, still
        # gated to "no real mesh yet"); this is its counterpart for
        # once a real mesh IS on screen -- self.wafer.mask_openings_um
        # is what any NEXT chained etch/deposition/masked-oxidation
        # step actually reads (see _mask_recipe_keys_for_current_step()),
        # so it needs to stay visible after a real mesh from an earlier
        # step is showing, not just before the first real step.
        #
        # The ORIGINAL version of this drew PR at a FIXED height
        # (surface_y, i.e. the y=0 datum) regardless of what the real
        # mesh's own current top surface was -- fine on a bare wafer
        # (nothing real to conflict with), but once real oxide had
        # already grown ABOVE y=0, that fixed height let the PR block
        # sit partly UNDER/overlapping the real oxide instead of on top
        # of it (confirmed by direct visual inspection). Fixed by
        # positioning each PR segment on self._real_mesh_top_um(), the
        # per-x lookup _draw_real_mesh_result() builds from the actual
        # mesh triangles, falling back to the y=0 datum when no real
        # mesh exists yet (mirrors the placeholder block's own datum).
        #
        # Gated on the SAME `pr_present` litho-stage condition the
        # pre-real-mesh placeholder uses (minus the "already through a
        # real step" tail values) -- NOT merely on a mask window being
        # configured. self.wafer.mask_openings_um keeps whatever value
        # it last had regardless of what the user just clicked, so
        # drawing PR from its presence alone made PR appear after ANY
        # real step (oxidation, etch, ...) whether or not the user ever
        # asked for lithography -- reading as "oxidizing now always
        # implies PR comes next," the opposite of every other fix this
        # session (order is the user's choice; clicking one step must
        # not draw a DIFFERENT step the user never clicked). PR now
        # shows only once the user has actually clicked through PR
        # COAT (or a later litho stage) since the process_stage last
        # changed -- exactly what they clicked, nothing implied.
        #
        # WHAT is drawn now comes from _resist_spans_um(), the same
        # method the recipe builder reads, so the preview cannot disagree
        # with the simulation again. It used to derive its own shape here
        # -- always "resist in the gaps between the openings", i.e. an
        # already-DEVELOPED pattern -- so a bare PR COAT (blanket film,
        # no openings yet) was drawn as though it had also been aligned,
        # exposed and developed. That is the same defect the recipe had,
        # in the renderer.
        #
        # Still gated on process_stage, not on wafer.pr_present: this
        # block previews resist that is NOT yet part of any geometry.
        # Once a real step runs WITH resist, the resist is a genuine
        # `Mask` material in the exported mesh and _draw_real_mesh_result
        # already draws it -- drawing it again here would double it.
        pr_pending = self.process_stage in (
            "pr_coated", "aligned", "exposed", "developed",
        )
        resist_spans_um = self._resist_spans_um() if pr_pending else None

        # Litho-stage visuals on top of a REAL mesh -- the on-real-mesh
        # counterparts of the no-real-mesh placeholder blocks above (PR
        # film / mask box / UV rays / exposed-PR highlight), positioned
        # relative to the real current surface via _real_mesh_top_um()
        # instead of a fixed y=0 datum. Gated on `real_mesh_available`
        # alone (mesh existence), NOT on litho state -- lithography
        # status display and physical mesh rendering are independent:
        # neither hides the other. mask_present/exposed_now/resist_spans_um
        # decide WHAT litho visual to draw, real_mesh_available decides
        # WHERE (on the real surface vs. the fixed placeholder datum).
        if real_mesh_available and (resist_spans_um or mask_present):
            half_width = self.wafer.width_um / 2.0
            _vx0, _vxmin, _vxs, _vsy, v_yscale = self._viewer_scale

            def _real_top_canvas_y(wafer_lo_um, wafer_hi_um):
                # Highest real point spanned by this segment -- sitting
                # the PR/mask block there avoids clipping into real
                # material even where the surface isn't flat (an etched
                # step, say); a real spin-on / rigid mask would clear
                # the highest point it spans, not the average.
                samples = [wafer_lo_um, (wafer_lo_um + wafer_hi_um) / 2, wafer_hi_um]
                top_um = max(self._real_mesh_top_um(s - half_width) for s in samples)
                return surface_y - top_um * v_yscale

            pr_height_px = max(6.0, self.wafer.pr_thickness_um * v_yscale)

            if resist_spans_um:
                # _resist_spans_um() works in DOMAIN coordinates (centred
                # on 0, the convention every recipe uses); this canvas
                # block works in WAFER coordinates (0..width_um). Failing
                # to convert is a documented trap in this project -- see
                # CLAUDE.md's PN-diode entry, where the same mix-up put a
                # junction 0.1um from the domain edge and still produced
                # a plausible-looking result.
                for lo_dom, hi_dom in resist_spans_um:
                    lo_um = lo_dom + half_width
                    hi_um = hi_dom + half_width
                    base_y = _real_top_canvas_y(lo_um, hi_um)
                    canvas.create_rectangle(
                        x0 + lo_um * scale, base_y - pr_height_px,
                        x0 + hi_um * scale, base_y,
                        fill="#e8a0bd", outline="#803252",
                    )

                if exposed_now:
                    # Exposed (soluble) PR under EVERY mask opening --
                    # on-real-mesh counterpart of the no-real-mesh
                    # `exposed_now` highlight above.
                    for op_lo_um, op_hi_um in sorted(self.wafer.mask_openings_um):
                        base_y = _real_top_canvas_y(op_lo_um, op_hi_um)
                        canvas.create_rectangle(
                            x0 + op_lo_um * scale, base_y - pr_height_px,
                            x0 + op_hi_um * scale, base_y,
                            fill="#f6dce7", outline="#803252", stipple="gray50",
                        )
                    canvas.create_text(
                        (opening_x0 + opening_x1) / 2,
                        _real_top_canvas_y(self.wafer.mask_left_um, self.wafer.mask_right_um)
                        - pr_height_px / 2,
                        text="EXPOSED PR", fill="#803252",
                    )

                canvas.create_text(
                    x0 + 5, _real_top_canvas_y(0.0, 0.0) - pr_height_px / 2 - 12,
                    anchor="w",
                    text=(
                        # Describes the resist AS IT IS. It must not name or
                        # predict a step the user has not chosen.
                        "PR — developed (patterned)"
                        if self.wafer.developed
                        else "PR — blanket coat (not patterned)"
                    ),
                    fill="#803252", font=(Tokens.FONT_UI, 8),
                )

            if mask_present:
                # Photomask held above the wafer during alignment/
                # exposure -- opaque wherever there is no opening, sat
                # a fixed gap above the real PR film's own top surface
                # (a rigid mask does not conform to wafer topology; the
                # no-real-mesh placeholder above uses the same fixed gap
                # from its own y=0 datum).
                mask_gap_px = 45
                edge_um = 0.0
                for op_lo_um, op_hi_um in sorted(self.wafer.mask_openings_um):
                    if op_lo_um > edge_um:
                        base_y = _real_top_canvas_y(edge_um, op_lo_um) - pr_height_px
                        canvas.create_rectangle(
                            x0 + edge_um * scale, base_y - mask_gap_px,
                            x0 + op_lo_um * scale, base_y,
                            fill="#202020", outline="#111",
                        )
                    edge_um = max(edge_um, op_hi_um)
                if edge_um < self.wafer.width_um:
                    base_y = _real_top_canvas_y(edge_um, self.wafer.width_um) - pr_height_px
                    canvas.create_rectangle(
                        x0 + edge_um * scale, base_y - mask_gap_px,
                        x1, base_y,
                        fill="#202020", outline="#111",
                    )

                for op_lo_um, op_hi_um in sorted(self.wafer.mask_openings_um):
                    base_y = _real_top_canvas_y(op_lo_um, op_hi_um) - pr_height_px
                    canvas.create_text(
                        x0 + (op_lo_um + op_hi_um) / 2 * scale,
                        base_y - mask_gap_px - 12,
                        text="MASK OPENING", fill="#155ea8",
                    )

                if exposed_now:
                    # UV illumination through the mask opening -- same
                    # single "selected" opening the no-real-mesh
                    # placeholder's UV rays use.
                    ray_bottom_y = (
                        _real_top_canvas_y(self.wafer.mask_left_um, self.wafer.mask_right_um)
                        - pr_height_px
                    )
                    ray_top_y = ray_bottom_y - mask_gap_px
                    for offset in range(5):
                        ray_x = (
                            opening_x0 + (offset + 0.5) * (opening_x1 - opening_x0) / 5
                        )
                        canvas.create_line(
                            ray_x, ray_top_y, ray_x, ray_bottom_y,
                            fill="#2e86de", arrow="last",
                        )
                    canvas.create_text(
                        (opening_x0 + opening_x1) / 2, ray_top_y - 10,
                        text="UV EXPOSURE", fill="#2e86de",
                    )

        # POTENTIAL / ELECTRON / HOLE layers need per-node DevSim field
        # data (Potential/Electrons/Holes), which run_measurement's
        # worker does not serialize back to the GUI today -- only
        # terminal currents (see run_measurement / _make_measurement_panel).
        # Rather than silently ignoring the layer switch or fabricating
        # a fake field map, say plainly that the data isn't there yet.
        # This is the one honest limitation flagged in the redesign plan.
        selected_layer = self.viewer_layer_var.get()
        if selected_layer in ("potential", "electron", "hole"):
            T = Tokens
            canvas.create_rectangle(
                x0, surface_y - 20, x1, surface_y + 20,
                fill=T.BG_1, outline=T.LINE_STRONG,
            )
            canvas.create_text(
                (x0 + x1) / 2, surface_y,
                text=f"{self._VIEWER_LAYER_LABELS[selected_layer]} field data not "
                     "available — device measurement does not export per-node "
                     "field values yet (terminal currents only).",
                fill=T.FG_MUTED, font=(T.FONT_UI, 9), justify="center",
                width=x1 - x0 - 40,
            )

    # --------------------------------------------------------
    # STAGES
    # --------------------------------------------------------

    def _mark_stage_done(self, *indices):
        """Light up the SESSION STATE markers for steps that actually ran.

        The markers used to be driven by passing a RANGE to
        _activate_stages: running a single oxidation called
        _activate_stages(0..6), which lit PR coat, Mask alignment,
        Exposure, Develop AND Etch -- five steps the user never ran. That
        is a leftover from when the GUI enforced one fixed sequence, and
        it is exactly the "one step shows the next step's result"
        complaint, in the one place where it is purely cosmetic.

        Now each step marks only its own marker, accumulated in
        self._stages_done, so the panel reports history instead of
        predicting a recipe.
        """
        self._stages_done.update(indices)
        self._activate_stages(*self._stages_done)

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

    def _log_physics_status(self, result):
        """Report what the physics did and did not know.

        Never blocks and never hides: an UNKNOWN result still ran, and
        the log says which parameter was unknown and what was passed
        instead.
        """
        physics = result.get("physics_status")
        if physics:
            self._log(f"\nPHYSICS: {physics.get('resolution', 'UNKNOWN')}\n")
            for entry in physics.get("entries", []):
                self._log(
                    f"  {entry.get('parameter')} [{entry.get('material')}]: "
                    f"{entry.get('resolution')} / {entry.get('provenance')}"
                    f" — {entry.get('note', '')}\n"
                )
        numerical = result.get("numerical_status")
        if numerical and numerical.get("under_resolved_x"):
            count = len(numerical["under_resolved_x"])
            self._log(
                f"\nNUMERICAL: {count} x positions carry a layer thinner than "
                f"one grid cell; the geometry there is under-resolved. "
                f"Reduce grid delta to resolve it.\n"
            )

    # --------------------------------------------------------
    # RESET
    # --------------------------------------------------------

    def reset(self):

        self.wafer = Wafer()
        self.recipe = BoschRecipe()
        self.last_doped_result = None
        self.last_final_mesh = None
        self._viewer_depth_budget_um = {}
        self.history = []
        self.process_stage = "wafer"

        # Both must clear here: completed_steps is what every standalone
        # RUN click now replays (see _chained_flow_config()), so leaving
        # it stale would make NEW WAFER silently keep re-growing the
        # PREVIOUS wafer's geometry underneath whatever gets run next.
        self.flow_steps = []
        self.completed_steps = []
        self.flow_step_meshes = []
        # Must clear too: resuming a NEW wafer from the OLD wafer's
        # accumulated geometry would silently keep building on it.
        self.last_domain_state = None
        self.last_physics_status = None
        if hasattr(self, "_refresh_flow_list"):
            self._refresh_flow_list()

        # A fresh wafer exists, and nothing has been done to it yet.
        self._stages_done = {0}
        self._activate_stages(*self._stages_done)

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
