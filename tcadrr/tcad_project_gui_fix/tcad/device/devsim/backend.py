#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DevSim session helper — mirrors tcad/backends/viennaps/session.py's
pattern (optional import guard + is_available()/require_devsim()) so
device backends follow the same shape as process backends.
"""

from __future__ import annotations

import os
from typing import Any

# DevSim's linear algebra pulls in Intel's OpenMP runtime (libiomp5md.dll,
# via mkl/intel_openmp); ViennaPS/ViennaLS ships its own, separately built
# LLVM OpenMP runtime (libomp140.x86_64.dll). Whichever loads second raises
# a hard, non-Python-catchable "OMP: Error #15: ... already initialized"
# and crashes the process — reproduced deterministically every time a real
# devsim.solve() runs in the same process as an already-imported ViennaPS
# (confirmed: the mesh generation and DevSim import steps before solve()
# always succeed; only solve() crashes). KMP_DUPLICATE_LIB_OK=TRUE is
# Intel's own documented escape hatch for exactly this two-runtime
# collision; it must be set before whichever import first loads either
# runtime's DLL, so it's set here, immediately before `import devsim`.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

try:
    import devsim
except Exception:
    devsim = None


def is_available() -> bool:
    """True if the DevSim Python module imported successfully."""
    return devsim is not None


def require_devsim() -> Any:
    """Return the imported devsim module, or raise if it's unavailable."""
    if devsim is None:
        raise RuntimeError(
            "DevSim is unavailable.\n"
            "Install DevSim first:\n"
            "python -m pip install devsim"
        )
    return devsim
