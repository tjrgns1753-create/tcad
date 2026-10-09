"""Known-undoped input and post-solve analytic checks, not a new transport model."""
import math
from tcad.physics.wafer_state_v2 import WaferStateV2
from tcad.characterization.node_fields import validate_node_fields
from tcad.characterization.interface import validate_bias_point

def intrinsic_refusal_status(reason, note):
    """Result validity only; never modify or activate the canonical wafer."""
    return {'resolution': 'UNSUPPORTED_BY_MODEL', 'reason_code': reason,
            'entries': [{'parameter': 'intrinsic_device_measurement', 'material': 'Si',
                         'resolution': 'UNSUPPORTED_BY_MODEL', 'provenance': 'DERIVED', 'note': note}]}

def known_undoped_si(state):
    if not isinstance(state, WaferStateV2) or len(state.cells)!=1 or state.attachments or state.unresolved_inventory:
        return False
    cell=state.cells[0]
    if cell.material!='Si' or cell.lifecycle!='ACTIVE' or not cell.is_modelled:
        return False
    b=cell.bounds_um
    return (len(state.events)==1 and state.events[0].process_category=='initial_geometry'
            and state.events[0].model_status=='MODELLED' and state.events[0].extent_um==b
            and state.events[0].output_cell_ids==(cell.cell_id,)
            and all(math.isfinite(v) for v in b) and b[1]>b[0] and b[3]>b[2])

def validate_intrinsic_bias(state, axis, voltage):
    if not known_undoped_si(state) or axis not in ('x','y') or not math.isfinite(voltage):
        raise ValueError('INTRINSIC_INPUT_UNSUPPORTED')
    b=state.cells[0].bounds_um
    length=(b[1]-b[0]) if axis=='x' else (b[3]-b[2])
    if abs(voltage)/(length*1e-4)>5.:
        raise ValueError('INTRINSIC_LOW_FIELD_CAPABILITY_UNVERIFIED: maximum 5 V/cm')

def validate_intrinsic_result(state, axis, voltage, fields, result, params, source, ground, *, source_at_max):
    validate_intrinsic_bias(state,axis,voltage)
    validate_node_fields(fields)
    from tcad.device.devsim.doping_mapping import _float32_roundtrip_ulp_um
    bounds=state.cells[0].bounds_um
    observed=(min(p[0] for p in fields.xy_um),max(p[0] for p in fields.xy_um),
              min(p[1] for p in fields.xy_um),max(p[1] for p in fields.xy_um))
    if any(abs(a-b)>_float32_roundtrip_ulp_um(b,1e-4) for a,b in zip(observed,bounds)):
        raise ValueError('INTRINSIC_GEOMETRY_EVIDENCE_MISMATCH')
    if fields.region!='Si' or result.region!='Si' or len(result.points)!=1 or result.metadata.get('current_unit')!='A/cm':
        raise ValueError('INTRINSIC_RESULT_IDENTITY_MISMATCH')
    validate_bias_point(result.points[0],(source,ground),expected_voltages={source:voltage,ground:0.})
    if any(not math.isfinite(params[k]) or params[k]<=0 for k in ('ElectronCharge','n_i','mu_n','mu_p')):
        raise ValueError('INTRINSIC_PARAMETER_EVIDENCE_INVALID')
    ni=params['n_i']; ax=0 if axis=='x' else 1
    length=bounds[1]-bounds[0] if ax==0 else bounds[3]-bounds[2]
    width=bounds[3]-bounds[2] if ax==0 else bounds[1]-bounds[0]
    g=params['ElectronCharge']*(params['mu_n']+params['mu_p'])*ni*width/length
    scale=g*length*1e-4*5.
    point=result.points[0]
    i=point.currents[source]; ig=point.currents[ground]
    expected=g*voltage
    current_error=abs(i-expected)/(abs(expected) if voltage else scale)
    kcl_error=abs(i+ig)/scale
    n_error=max(abs(v/ni-1.) for v in fields.electron)
    p_error=max(abs(v/ni-1.) for v in fields.hole)
    coordinates=[p[ax] for p in fields.xy_um]; lo,hi=min(coordinates),max(coordinates)
    if type(source_at_max) is not bool:
        raise ValueError('INTRINSIC_CONTACT_LOCATION_EVIDENCE_MISSING')
    reference=lo if source_at_max else hi
    target=hi if source_at_max else lo
    p0=fields.potential[coordinates.index(reference)]
    phi_error=max(abs(p-(p0+voltage*(x-reference)/(target-reference))) for x,p in zip(coordinates,fields.potential))/max(abs(voltage),length*1e-4*5.)
    metrics={'current_relative_error':current_error,'kcl_error':kcl_error,'electron_relative_error':n_error,
             'hole_relative_error':p_error,'potential_linearity_error':phi_error}
    limits=(1e-2 if voltage else 1e-4,1e-6,1e-4,1e-4,1e-2)
    if any(not math.isfinite(v) or v>limit for v,limit in zip(metrics.values(),limits)):
        raise ValueError('INTRINSIC_ANALYTIC_VALIDATION_FAILED: '+repr(metrics))
    return metrics
