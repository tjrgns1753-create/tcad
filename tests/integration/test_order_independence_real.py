#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Order independence, checked by fuzzing the order.

THE PERMUTATIONS BELOW ARE NOT A PROCESS-ORDER SPECIFICATION. They are a
generator used to find states that recur across different orders. No
permutation is a "normal" or "supported" order; the simulator imposes no
order at all.

What is asserted: whenever the same (exposed_materials, intent) pair
occurs — no matter which order produced it — the resolver returns the
same thing. A difference would mean history is leaking into physics.

Cost control: exhaustive for a small number of steps; for more, switch
to deterministic seeded sampling so failures reproduce.

Only ETCHING (isotropic) is wired to the resolver so far (Task 9) — a
deposition step's result carries no "physics_status" at all yet. Those
steps stay in the sweep anyway: they still vary the wafer's exposed
material state that a later etch step sees, and are simply skipped when
building/checking observations (no physics_status to compare).
"""

import itertools
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tcad.process.deposition  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.process import registry

BASE = dict(pr_thickness_um=1.0, silicon_depth_um=5.0, grid_delta_um=0.05,
            x_extent_um=6.0, y_extent_um=6.0)

#: Deliberately fast steps — a sweep runs many flows.
STEPS = [
    ("deposition", "isotropic",
     {**BASE, "rate": 0.1, "deposition_time_s": 0.2, "material": "SiO2"}),
    ("deposition", "isotropic",
     {**BASE, "rate": 0.1, "deposition_time_s": 0.2, "material": "Si3N4"}),
    ("etching", "isotropic",
     {**BASE, "chemistry": "SF6O2", "rate": -0.05, "etch_time_s": 0.2}),
]

SEED = 20260825
MAX_EXHAUSTIVE = 3


def _permutations(steps):
    if len(steps) <= MAX_EXHAUSTIVE:
        return list(itertools.permutations(range(len(steps))))
    rng = random.Random(SEED)
    orders = {tuple(range(len(steps)))}
    while len(orders) < 12:
        order = list(range(len(steps)))
        rng.shuffle(order)
        orders.add(tuple(order))
    return sorted(orders)


def main():
    observations = {}
    orders = _permutations(STEPS)
    print(f"sweeping {len(orders)} orders of {len(STEPS)} steps "
          f"(generator, not a spec)")

    for order in orders:
        domain = None
        for index in order:
            category, model, recipe = STEPS[index]
            first = domain is None
            step_recipe = dict(recipe)
            if first:
                step_recipe["mask_spans_um"] = []
            step = registry.get(category, model)(inherited_domain=domain)

            # Exactly one call to run() per step: run() calls
            # prepare_domain() internally, and prepare_domain() mutates
            # an inherited domain in place for recipes carrying
            # remask_spans_um (inserts a new resist level set). Calling
            # prepare_domain() ourselves first and then run() a second
            # time would apply that mutation twice to the same domain
            # object -- everything needed, including the physics
            # fingerprint, comes from this one call's return value.
            result = step.run(step_recipe, tempfile.mkdtemp(prefix="perm_"))

            physics = result.get("physics_status")
            if physics is not None:
                exposed = frozenset(entry["material"] for entry in physics.get("entries", []))
                key = (exposed, category, model, step_recipe.get("chemistry"))
                fingerprint = (
                    physics.get("resolution"),
                    repr(sorted(
                        (e["material"], e["value"], e["resolution"], e["provenance"])
                        for e in physics.get("entries", []))),
                )
                if key in observations:
                    assert observations[key] == fingerprint, (
                        f"same exposed materials {sorted(exposed)} and same intent "
                        f"({category}/{model}) resolved differently depending on "
                        f"the order taken to get there:\n"
                        f"  {observations[key]}\n  {fingerprint}")
                else:
                    observations[key] = fingerprint

            domain = step.last_domain

    print(f"{len(observations)} distinct (exposed_materials, intent) pairs seen")
    print()
    print("ORDER INDEPENDENCE HELD — equal state and intent resolved equally")


if __name__ == "__main__":
    main()
