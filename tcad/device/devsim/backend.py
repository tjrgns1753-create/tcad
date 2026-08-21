#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DevSim session helper — mirrors tcad/backends/viennaps/session.py's
pattern (optional import guard + is_available()/require_devsim()) so
device backends follow the same shape as process backends.
"""

from __future__ import annotations

import glob
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


def _default_devsim_math_libs() -> "str | None":
    """A working DEVSIM_MATH_LIBS value for this machine, or None.

    Found necessary by real execution, not assumed: DevSim's own default
    search (`libopenblas.so:liblapack.so:libblas.so`, its own hardcoded
    fallback) looks for the UNVERSIONED `.so` symlink, which a
    `pip install devsim` alone does not provide — Debian/Ubuntu's
    `libblas3`/`libopenblas0` packages (a common, often-preinstalled
    dependency) ship only the VERSIONED `libblas.so.3` via
    /etc/alternatives, pointing at a real BLAS+LAPACK implementation
    (confirmed: `libblas.so.3` on this project's own dev container
    resolves, through that alternatives symlink, to OpenBLAS, which
    bundles LAPACK — one path is enough). Without this, `import devsim`
    raises `RuntimeError: Issues initializing DEVSIM.` even though the
    package is genuinely installed, which previously surfaced to users
    as a misleading "DevSim is not installed" message.

    Only ever used when the caller has not already set DEVSIM_MATH_LIBS
    (see the `setdefault` below) and only when a candidate file is
    actually found on disk, so this can only help: a system where none
    of these paths exist behaves exactly as before (DevSim's own error,
    unchanged).
    """
    candidates = []
    for libdir in glob.glob("/usr/lib/*-linux-gnu") + ["/usr/lib64", "/usr/lib"]:
        candidates += [
            os.path.join(libdir, "libblas.so.3"),
            os.path.join(libdir, "libopenblas.so.0"),
        ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


if "DEVSIM_MATH_LIBS" not in os.environ:
    _math_libs = _default_devsim_math_libs()
    if _math_libs is not None:
        os.environ["DEVSIM_MATH_LIBS"] = _math_libs

_import_error: Exception | None = None
try:
    import devsim
except Exception as exc:  # capture WHY, not just that it failed
    devsim = None
    _import_error = exc


def is_available() -> bool:
    """True if the DevSim Python module imported successfully."""
    return devsim is not None


def require_devsim() -> Any:
    """Return the imported devsim module, or raise if it's unavailable.

    The error message distinguishes "genuinely not installed" from
    "installed but failed to import" (e.g. a missing BLAS/LAPACK
    library) — the two look identical from `is_available()` alone, but
    need different fixes, and reporting the wrong one sends a user with
    a real environment problem to `pip install` a package that is
    already there. See `_default_devsim_math_libs()` for the specific,
    real-execution-confirmed case this project hit.
    """
    if devsim is None:
        if _import_error is not None:
            raise RuntimeError(
                "DevSim is installed but failed to import:\n\n"
                f"{_import_error}\n\n"
                "This is usually a missing or misconfigured BLAS/LAPACK "
                "library, not a missing package — reinstalling DevSim will "
                "not fix it. If a BLAS/LAPACK library IS installed, try "
                "setting DEVSIM_MATH_LIBS to its path explicitly."
            ) from _import_error
        raise RuntimeError(
            "DevSim is unavailable.\n"
            "Install DevSim first:\n"
            "python -m pip install devsim"
        )
    return devsim
