"""ViennaPS backend: common session/domain/I-O plumbing.

Purely backend-facing (Domain creation, MakeTrench, snapshot/mesh I/O —
no process-recipe logic). Every Etching model (and, in later phases,
Deposition/Oxidation) under tcad/process/ is built on top of this
module; it never depends on them.
"""

from tcad.backends.viennaps.session import is_available, require_viennaps

__all__ = ["is_available", "require_viennaps"]
