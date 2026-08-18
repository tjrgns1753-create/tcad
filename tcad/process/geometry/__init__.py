"""Geometry category — importing this package registers all built-in
geometry-construction models with tcad.process.registry.

Unlike etching/deposition/oxidation, models here do not run a
ViennaPS Process() at all -- they are one-shot, multi-material geometry
constructions (the same "zero duration" convention
deposition/geometric_trench.py already established for a different
reason). See gate_stack.py's own module docstring for why this category
exists rather than folding into ProcessStep.prepare_domain() the way
mask_spans_um did.
"""

from tcad.process.geometry import gate_stack

__all__ = ["gate_stack"]
