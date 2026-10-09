"""GUI device/result provenance only; no engine import or physical inference."""
from dataclasses import dataclass
import hashlib
from pathlib import Path

def missing_device_profile_status(state):
    """Describe unavailable GUI input, not an absence of thermal carriers.

    This is metadata only: it neither queries concentrations nor activates,
    removes or reconstructs any canonical dopant attachment.
    """
    attachments = tuple(getattr(state, 'attachments', ()) or ())
    inactive = [a for a in attachments if getattr(a, 'chemical_state', 'UNKNOWN') != 'ACTIVE']
    reason = 'DOPANT_ACTIVATION_MODEL_MISSING' if inactive else 'DEVICE_PROFILE_NOT_AVAILABLE'
    note = ('Canonical dopant records exist but electrical activation is unresolved; '
            'CHEMICAL/UNKNOWN records are not electrically active device inputs.' if inactive else
            'This GUI request has no available validated device profile. '
            'This does not imply that the semiconductor has no thermal carriers.')
    return {'resolution': 'UNSUPPORTED_BY_MODEL', 'reason_code': reason,
            'entries': [{'parameter': 'measurement_device_input', 'material': '?',
                         'resolution': 'UNSUPPORTED_BY_MODEL', 'provenance': 'DERIVED', 'note': note}]}

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
