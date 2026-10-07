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
    return NodeFields(region, xy, *arrays[2:])


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
