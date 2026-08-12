#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Process flow orchestration: run several ProcessSteps in sequence so
each one continues from the previous one's geometry and materials,
instead of each rebuilding a fresh wafer.

No global state. The carried geometry is passed explicitly:

    step = StepCls(inherited_domain=<previous step's domain>)

so it lives only on that one step instance. Nothing here (or in
tcad.backends.viennaps.session) keeps a module-level "current flow" —
that was a deliberate design constraint, mirroring how the DevSim
global-device-state problem was handled with explicit cleanup rather
than more hidden state.

Chaining mechanism, step N -> step N+1:
  1. step N's ProcessStep.prepare_domain() records the domain it
     processed on the instance (`step.last_domain`).
  2. after run(), this module persists that domain with
     session.save_domain_state() -> a real ViennaPS .vpsd file, and
     records its structure (materials / level-set count / bounding box
     / grid delta) via session.describe_domain().
  3. both go into the step's ProcessResult
     (domain_state_path / structure).
  4. step N+1 is constructed as StepCls(inherited_domain=domain), where
     domain is either the still-live object or one reloaded from that
     .vpsd via session.load_domain_state() — reload_between_steps
     selects which. Either way step N+1's prepare_domain() returns it
     unchanged: no new Domain, no new MakeTrench.

Single-step behavior is untouched: `registry.get(cat, name)()` with no
inherited_domain builds its own wafer exactly as in Phase 1-12.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from tcad.backends.viennaps import session
from tcad.mesh.interface import ProcessResult
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.process import registry


@dataclass
class FlowStep:
    """One step in a process flow.

    label : optional human-readable name used for this step's output
        subdirectory; defaults to "<NN>_<category>_<name>".
    """

    category: str
    name: str
    recipe: Dict[str, Any] = field(default_factory=dict)
    label: Optional[str] = None


def run_flow(
    steps: List[FlowStep],
    output_dir: str,
    reload_between_steps: bool = False,
) -> List[ProcessResult]:
    """Run `steps` in order, each continuing from the previous geometry.

    Returns one ProcessResult per step, in order. Each result carries
    its own final mesh, plus `domain_state_path` and `structure` so the
    caller can inspect exactly what that step changed.

    reload_between_steps : if True, each step's domain is reloaded from
        the persisted .vpsd file rather than reusing the live object.
        Slower, but proves the persisted state alone is sufficient to
        continue the flow (used by the continuity tests).
    """
    session.require_viennaps()

    if not steps:
        return []

    base_dir = Path(output_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    results: List[ProcessResult] = []
    carried_domain: Optional[Any] = None

    for index, step in enumerate(steps):
        label = step.label or f"{index:02d}_{step.category}_{step.name}"
        step_dir = base_dir / label
        step_dir.mkdir(parents=True, exist_ok=True)

        step_cls = registry.get(step.category, step.name)
        # Explicit injection -- the only channel by which geometry
        # crosses from one step to the next.
        step_instance = step_cls(inherited_domain=carried_domain)

        step_result = step_instance.run(step.recipe, str(step_dir))

        domain = step_instance.last_domain
        state_path = str(step_dir / "domain_state.vpsd")
        session.save_domain_state(domain, state_path)
        structure = session.describe_domain(domain)

        results.append(
            build_process_result(
                step_result,
                domain_state_path=state_path,
                structure=structure,
            )
        )

        carried_domain = (
            session.load_domain_state(state_path) if reload_between_steps else domain
        )

    return results
