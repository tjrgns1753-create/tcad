"""Terminal characterization (I-V, PN-junction I-V, MOS C-V; Vth and
subthreshold slope are future work built on the same
CharacterizationResult shape).

interface.py defines CharacterizationResult (backend-independent).
iv_sweep.py / pn_junction_iv_sweep.py / cv_sweep.py are the only
modules here that drive DevSim directly. io.py and plotting.py consume
only CharacterizationResult.

Public API:
    from tcad.characterization.interface import CharacterizationResult, BiasPoint
    from tcad.characterization.iv_sweep import run_iv_sweep
    from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
    from tcad.characterization.cv_sweep import run_mos_cv_sweep
    from tcad.characterization.io import save_csv, save_json, save_cv_csv
    from tcad.characterization.plotting import save_iv_plot, save_cv_plot
"""

from tcad.characterization.interface import BiasPoint, CharacterizationResult

__all__ = ["CharacterizationResult", "BiasPoint"]
