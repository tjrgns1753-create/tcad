"""Tier 1 doping-truthfulness -- stop-condition probe: can ONE request end with only SOME of its profiles attached?

Real GUI + real ViennaPS meshing; every doping kind is applied with BOTH a donor and an acceptor component (the multi-profile
requests) on (a) an exact MODELLED virgin-Si wafer and (b) a wafer whose state a refused positive-time LOCOS left unresolved.
Prints, per kind/state: run_doping() result, new active attachments, new refusal events, new unresolved-inventory entries.
Partial = new attachments > 0 AND (refusals > 0 OR ledger entries > 0). Read-only with respect to the repository."""
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")

import tkinter  # noqa: F401,E402
import tcad_2d_stagewise as gui  # noqa: E402

for n in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel"):
    setattr(gui.messagebox, n, lambda *a, **k: None)

KINDS = {
    "Uniform": {"doping_kind": "Uniform", "dope_uniform_region_var": "Si", "dope_uniform_donor_var": 3e16, "dope_uniform_acceptor_var": 1e16},
    "Step Junction": {"doping_kind": "Step Junction", "dope_step_region_var": "Si", "dope_step_axis_var": "x", "dope_step_position_var": 0.0,
                      "dope_step_donor_var": 1e17, "dope_step_acceptor_var": 5e16},
    "Gaussian Implant": {"doping_kind": "Gaussian Implant", "dope_gauss_region_var": "Si", "dope_gauss_axis_var": "x", "dope_gauss_position_var": 0.0,
                         "dope_gauss_straggle_var": 0.3, "dope_gauss_donor_var": 1e18, "dope_gauss_acceptor_var": 2e17,
                         "dope_gauss_donor_species_var": "P", "dope_gauss_acceptor_species_var": "B"},
    "Implant Windows": {"doping_kind": "Implant Windows", "dope_win_region_var": "Si", "dope_win_axis_var": "x",
                        "dope_win_donor_bg_var": 1e15, "dope_win_acceptor_bg_var": 2e15,
                        "dope_win_src_min_var": -1.5, "dope_win_src_max_var": -0.5, "dope_win_src_donor_var": 1e19, "dope_win_src_acceptor_var": 1e18,
                        "dope_win_drn_min_var": 0.5, "dope_win_drn_max_var": 1.5, "dope_win_drn_donor_var": 1e19, "dope_win_drn_acceptor_var": 1e18},
}


def make(refuse):
    app = gui.TCADApplication()
    app.withdraw()
    app.wafer.width_um, app.wafer.silicon_depth_um = 4.0, 1.0
    app.grid_var.set(0.2)
    assert app._materialize_current_wafer()
    if refuse:
        app.panel_category.set(app._PANEL_LABELS["oxidation"])
        app._show_panel_category()
        app.oxidation_method.set("LOCOS (Advanced)")
        app.ox_temp_var.set(1000.0)
        app.ox_time_var.set(0.1)
        app.run_oxidation()
    return app


partial = []
for state_label, refuse in (("MODELLED virgin Si", False), ("UNRESOLVED after refused LOCOS", True)):
    for kind, fields in KINDS.items():
        app = make(refuse)
        try:
            for name, value in fields.items():
                (app.doping_kind if name == "doping_kind" else getattr(app, name)).set(value)
            st0 = app.wafer_state
            ids0, ev0, un0 = {a.attachment_id for a in st0.attachments}, len(st0.events), len(st0.unresolved_inventory)
            ret = app.run_doping(silent=True)
            st = app.wafer_state
            new_att = [a for a in st.attachments if a.attachment_id not in ids0]
            refusals = [e for e in st.events[ev0:] if e.model_status == "UNSUPPORTED_BY_MODEL"]
            ledger = len(st.unresolved_inventory) - un0
            is_partial = bool(new_att) and bool(refusals or ledger)
            partial.append(is_partial)
            print(f"{state_label:32s} | {kind:16s} | returned {ret!s:5s} | new attachments {[(a.polarity, a.species) for a in new_att]} | "
                  f"refusal events {len(refusals)} | ledger entries {ledger} | PARTIAL={is_partial}")
        finally:
            app.destroy()
print("\nANY PARTIAL APPLICATION REPRODUCED:", any(partial))
