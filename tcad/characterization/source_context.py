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
    current=capture_source_context(mesh_path,state,pins)
    return (isinstance(context,SourceContext) and current is not None and
            context.state is current.state and context.mesh_sha256==current.mesh_sha256 and
            context.pins==current.pins)
