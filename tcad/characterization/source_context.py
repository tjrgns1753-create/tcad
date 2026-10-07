"""GUI device/result provenance only; no engine import or physical inference."""
from dataclasses import dataclass
import hashlib
from pathlib import Path

@dataclass(frozen=True, eq=False)
class SourceContext:
    mesh_sha256: str
    state: object
    pins: tuple

def capture_source_context(mesh_path, state, pins):
    """Keep the immutable canonical object and exact input mesh/pin signature.

    Holding the state reference prevents id reuse. Unreadable/missing evidence
    is not an identity transition and returns None. No mesh coordinates move.
    """
    if mesh_path is None:
        return None
    try:
        digest=hashlib.sha256()
        with Path(mesh_path).open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024), b''):
                digest.update(block)
        signature=tuple((p.name,p.role,p.x_um,p.y_um,p.target_region) for p in pins)
    except (OSError, TypeError, AttributeError, ValueError):
        return None
    return SourceContext(digest.hexdigest(), state, signature)

def source_context_matches(context, mesh_path, state, pins):
    if not isinstance(context,SourceContext):
        return False
    current=capture_source_context(mesh_path,state,pins)
    return (current is not None and
            context.state is current.state and context.mesh_sha256==current.mesh_sha256 and
            context.pins==current.pins)

def source_evidence(context):
    """Portable subset only. Never serialize a Python id as canonical proof."""
    if not isinstance(context, SourceContext):
        raise ValueError("Source context is missing.")
    return {"mesh_sha256": context.mesh_sha256, "canonical_record": "GUI_SESSION_ONLY",
            "pins": [{"name": p[0], "role": p[1], "x_um": p[2], "y_um": p[3], "target_region": p[4]}
                     for p in context.pins]}
