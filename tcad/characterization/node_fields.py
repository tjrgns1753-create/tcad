"""Copy already-solved DEVSIM node values; no engine import or interpolation."""
from dataclasses import dataclass
import math

FIELD_NAMES = {"potential": "Potential", "electron": "Electrons", "hole": "Holes"}
FIELD_UNITS = {"potential": "V", "electron": "cm^-3", "hole": "cm^-3"}
MAX_CAPTURE_NODES = 20_000
MAX_DISPLAY_NODES = 2_000


@dataclass(frozen=True)
class NodeFields:
    region: str
    xy_um: tuple
    potential: tuple
    electron: tuple
    hole: tuple


def validate_node_fields(fields):
    """Evidence validation, not a new physical model or mesh approval."""
    if not isinstance(fields, NodeFields) or not fields.region or not 0 < len(fields.xy_um) <= MAX_CAPTURE_NODES:
        raise ValueError("Invalid field snapshot or capture resource limit.")
    for key in FIELD_NAMES:
        values = getattr(fields, key)
        if len(values) != len(fields.xy_um) or not all(math.isfinite(v) for v in values):
            raise ValueError("Field array length/non-finite evidence error.")
        if key != "potential" and any(v < 0 for v in values):
            raise ValueError("Negative carrier concentration.")
    if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in fields.xy_um):
        raise ValueError("Invalid node coordinates.")


def capture_node_fields(module, device, region, length_scale_to_cm):
    """Caller must validate the successful bias point before calling.

    Public API only; copies into immutable tuples independent of device lifetime.
    Absence/invalidity is not zero and never triggers a new solve.
    """
    scale = float(length_scale_to_cm)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid node-coordinate length scale.")
    names = set(module.get_node_model_list(device=device, region=region))
    if not {"x", "y", *FIELD_NAMES.values()} <= names:
        raise ValueError("Required solved node fields are missing.")
    read = lambda name: tuple(float(v) for v in module.get_node_model_values(
        device=device, region=region, name=name))
    x = read("x")
    if not 0 < len(x) <= MAX_CAPTURE_NODES:
        raise ValueError("Node field capture resource limit or empty region.")
    arrays = [x, read("y"), *(read(name) for name in FIELD_NAMES.values())]
    if any(len(a) != len(x) or not all(math.isfinite(v) for v in a) for a in arrays):
        raise ValueError("Node field arrays differ in length or contain non-finite values.")
    if any(v < 0 for a in arrays[3:] for v in a):
        raise ValueError("Negative carrier concentration is not displayable.")
    xy = tuple((a / scale, b / scale) for a, b in zip(x, arrays[1]))
    if not all(math.isfinite(v) for pair in xy for v in pair):
        raise ValueError("Converted coordinates are non-finite.")
    fields = NodeFields(region, xy, *arrays[2:])
    validate_node_fields(fields)
    return fields


def field_samples(fields, layer):
    """All actual nodes, linear blue/red range. No decimation or interpolation."""
    if not isinstance(fields, NodeFields) or layer not in FIELD_NAMES:
        raise ValueError("No solved field snapshot.")
    if len(fields.xy_um) > MAX_DISPLAY_NODES:
        raise ValueError("Node display resource limit; no partial map shown.")
    values = getattr(fields, layer)
    lo, hi = min(values), max(values)
    def color(v):
        t = (v-lo)/(hi-lo) if hi > lo else .5
        return f"#{round(255*t):02x}40{round(255*(1-t)):02x}"
    return tuple((x, y, v, color(v)) for (x, y), v in zip(fields.xy_um, values)), lo, hi


def _field_bias_point(fields, result):
    """Shared evidence boundary for displaying/saving the same 2-terminal result."""
    from tcad.characterization.interface import validate_bias_point
    validate_node_fields(fields)
    if result is None or len(result.points) != 1 or result.region != fields.region:
        raise ValueError("Field export needs its own single-bias region result.")
    point = result.points[0]
    validate_bias_point(point)
    contacts = set(point.voltages)
    if (len(contacts) != 2 or contacts != set(point.currents) or
            any(not isinstance(name, str) or not name.strip() for name in contacts)):
        raise ValueError("Field export requires the same two named contacts in voltages and currents.")
    if result.sweep_contact not in point.voltages:
        raise ValueError("Field result lacks its sweep voltage.")
    if (result.metadata.get("current_unit") != "A/cm" or result.metadata.get("device_dimension") != 2 or
            result.metadata.get("current_normalization") != "per_out_of_plane_depth"):
        raise ValueError("Field export is limited to established 2D current units.")
    return point


def field_caption(fields, result, layer):
    """Describe original solved values; never rebase Potential to a contact bias."""
    point = _field_bias_point(fields, result)
    samples, lo, hi = field_samples(fields, layer)
    bias = "; ".join(f"{contact}={float(value):+.6g} V" for contact, value in point.voltages.items())
    text = (f"영역 {fields.region} | {len(samples)} 실제 노드 (actual node samples) | {bias}\n"
            f"{layer}: 선형색 파랑={lo:.4e}, 빨강={hi:.4e} {FIELD_UNITS[layer]}; "
            "보간 없음 (No interpolation).")
    if layer == "potential":
        text += "\nDEVSIM 원시 Potential; 접점 인가전압과 전위 기준이 다를 수 있음."
    return text


def save_node_field_evidence(fields, result, context, path):
    """Single atomic JSON replacement of actual fields plus bias/source evidence.

    Caller must compare context against the current wafer before invoking.
    GUI_SESSION_ONLY provenance is not a serialized canonical state/checkpoint.
    """
    from dataclasses import asdict
    import json
    import os
    from pathlib import Path
    import tempfile
    from tcad.characterization.source_context import source_evidence
    point = _field_bias_point(fields, result)
    payload = {"schema": 1, "sampling": "ACTUAL_NODES_NO_INTERPOLATION", "node_count": len(fields.xy_um),
               "units": {"xy_um": "um", **FIELD_UNITS}, "snapshot": asdict(fields),
               "measurement": {"name": result.name, "region": result.region, "sweep_contact": result.sweep_contact,
                   "metadata": result.metadata, "voltages": point.voltages, "currents": point.currents, "converged": point.converged},
               "source_evidence": source_evidence(context), "physics_scope": "SUPPORTED_MEASUREMENT_NOT_GENERAL_TCAD_APPROVAL"}
    data = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=target.parent,
                                         prefix=".node_fields_", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(target)


def node_near_pixel(fields, layer, transform, px, py, radius=3.0):
    """Nearest displayed node inside a UI hit radius; never an interpolated value."""
    samples, _, _ = field_samples(fields, layer)
    cx0, xmin, xs, sy, ys = transform
    if not all(math.isfinite(v) for v in (*transform, px, py, radius)) or xs <= 0 or ys <= 0 or radius <= 0:
        raise ValueError("Invalid screen coordinate transform.")
    nearest = None
    best = radius * radius
    for x, y, value, _ in samples:
        distance = (cx0+(x-xmin)*xs-px)**2 + (sy-y*ys-py)**2
        if distance <= best:
            nearest, best = (x, y, value), distance
    return nearest
