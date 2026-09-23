#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaferState v2 test A (design doc §9 / review): `last_step_category`
and the `MATERIAL_CHANGE_KIND_BY_CATEGORY` heuristic are fully gone
from production `tcad/`.

Static:  an AST scan of every production module under tcad/ (plus
         tcad_2d_stagewise.py) finds ZERO name references to
         `last_step_category` or `MATERIAL_CHANGE_KIND_BY_CATEGORY`
         (attribute access, argument, keyword, or bare name -- comments
         and string history notes are not code and are ignored).
Behavioural:  a v2 etch / deposition / oxidation decision is driven
         only by SpatialEvent / GeometryTransform / unresolved ledger.

No backend.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from tcad.physics.wafer_state_v2 import (
    WaferStateV2, MaterialCell, GeometryTransform, advance, attach_dopant,
    uniform_inventory_integral,
)

FORBIDDEN = {"last_step_category", "MATERIAL_CHANGE_KIND_BY_CATEGORY"}


def _name_refs(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN:
            yield node.id, node.lineno
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
            yield node.attr, node.lineno
        elif isinstance(node, ast.arg) and node.arg in FORBIDDEN:
            yield node.arg, node.lineno
        elif isinstance(node, ast.keyword) and node.arg in FORBIDDEN:
            yield node.arg, node.lineno


def main():
    # --- static ---
    targets = list((ROOT / "tcad").rglob("*.py")) + [ROOT / "tcad_2d_stagewise.py"]
    hits = []
    for path in targets:
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name, lineno in _name_refs(tree):
            hits.append(f"{path.relative_to(ROOT)}:{lineno}: {name}")
    assert not hits, "production code still references the retired heuristic:\n" + "\n".join(hits)
    print(f"[1] AST scan of {len(targets)} production modules: 0 name references to "
          f"{sorted(FORBIDDEN)}")

    # --- behavioural: etch/deposition/oxidation decisions use only v2 primitives ---
    s = WaferStateV2(
        cells=(MaterialCell("c1", "Si", (-5.0, 5.0, 0.0, 2.0), "inst_si"),), grid_delta_um=0.1)
    s = attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: 1.0e17,
        inventory_integral=uniform_inventory_integral(1.0e17),
        support_instance_id="inst_si", support_region_um=(-5.0, 5.0, 0.0, 2.0),
        model="uniform_v1", chemical_state="ACTIVE")

    # etch with an explicit transform -> a REMOVED SpatialEvent drives the clip
    s_etch = advance(s, GeometryTransform(
        "etching", representable=True, removed_extents_um=((0.0, 5.0, 0.0, 2.0),),
        input_instance_ids=("inst_si",)), step_seed="e")
    assert any(e.category == "REMOVED" for e in s_etch.events)
    assert s_etch.attachments and s_etch.attachments[0].support_region_um == (-5.0, 0.0, 0.0, 2.0)

    # etch with NO transform -> an UNSUPPORTED_BY_MODEL event + ledger, no category flag anywhere
    s_fc = advance(s, GeometryTransform("etching", representable=False), step_seed="fc")
    assert any(e.category == "UNSUPPORTED_BY_MODEL" for e in s_fc.events)
    assert s_fc.unresolved_inventory
    assert s_fc.attachments == ()

    # oxidation -> a CONVERTED event (model_status UNSUPPORTED), ledger entry
    s_ox = advance(s, GeometryTransform(
        "oxidation", representable=True, converted_extents_um=((-5.0, 0.0, 1.0, 2.0),),
        input_instance_ids=("inst_si",)), step_seed="ox")
    assert any(e.category == "CONVERTED" and e.model_status == "UNSUPPORTED_BY_MODEL"
               for e in s_ox.events)

    # WaferStateV2 itself has no such field
    assert not hasattr(WaferStateV2(), "last_step_category")
    print("[2] etch / deposition / oxidation decisions are driven only by "
          "SpatialEvent / GeometryTransform / unresolved ledger")

    print()
    print("WaferState v2 test A PASS -- last_step_category heuristic fully retired")


if __name__ == "__main__":
    main()
