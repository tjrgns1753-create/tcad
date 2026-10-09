"""기존 uniform resistor의 해석 기준 재사용. 엔진 없음, 누락은 실패."""
import math
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'docs/audits/2026-10-01-batch7h-e6i-uniform-resistor-dd/scripts'))
from resistor_judge import theory, TOL_CURRENT, TOL_CONSERVATION, TOL_EQUILIBRIUM, TOL_N_UNIFORM, TOL_PSI_LINEAR
from tcad.characterization.node_fields import NodeFields, validate_node_fields

CASES = (
    ('x_max_pos', 'x', 'max', .001), ('x_max_neg', 'x', 'max', -.001),
    ('x_max_zero', 'x', 'max', 0.), ('x_min_pos', 'x', 'min', .001),
    ('y_max_pos', 'y', 'max', .001), ('y_min_pos', 'y', 'min', .001),
    ('y_max_neg', 'y', 'max', -.001), ('y_max_zero', 'y', 'max', 0.),
)
EXPECTED_PARAMS = {'ElectronCharge': 1.6e-19, 'n_i': 1e10, 'T': 300., 'mu_n': 400.,
                   'mu_p': 200., 'taun': 1e-8, 'taup': 1e-8}


def require(condition, name):
    if not condition:
        raise ValueError(name)


def evaluate(records):
    checks, metrics = [], {}
    try:
        require(set(records) == {row[0] for row in CASES}, 'CASE_SET_MISSING_OR_EXTRA')
        for name, axis, side, voltage in CASES:
            record = records[name]
            require((record['axis'], record['side'], record['voltage']) == (axis, side, voltage), 'REQUEST_IDENTITY')
            require(record['solves'] == 3 and record['device_cleanup'] is True and record['live_api_equal'] is True, 'EXECUTION_EVIDENCE')
            params = record['params']
            require(all(params[k] == value for k, value in EXPECTED_PARAMS.items()), 'PARAMETERS')
            fields = NodeFields(**record['snapshot'])
            validate_node_fields(fields)
            require(len(fields.xy_um) == 73 and fields.region == 'Si', 'SNAPSHOT_SCOPE')
            require(min(fields.electron) > 0 and min(fields.hole) > 0, 'POSITIVE_CARRIERS')
            point = record['measurement']['points'][0]
            require(len(record['measurement']['points']) == 1 and point['converged'] is True, 'BIAS_POINT')
            source = f'Si_{axis}{side}'
            ground = f'Si_{axis}{"min" if side == "max" else "max"}'
            require(point['voltages'] == {source: voltage, ground: 0.}, 'VOLTAGE_RECORD')
            require(set(point['currents']) == {source, ground}, 'CURRENT_CONTACTS')
            require(record['measurement']['region'] == 'Si' and record['measurement']['sweep_contact'] == source, 'RESULT_IDENTITY')
            require(all(math.isfinite(v) for v in point['currents'].values()), 'FINITE_CURRENTS')
            metadata = record['measurement']['metadata']
            require(metadata['current_unit'] == 'A/cm' and metadata['device_dimension'] == 2 and
                    metadata['current_normalization'] == 'per_out_of_plane_depth', 'UNITS')
            require(record['export_equal'] is True and record['success_log_present'] is True, 'GUI_EXPORT_EVIDENCE')
            require(set(record['rendered']) == {'potential', 'electron', 'hole'}, 'FIELD_LAYER_SET')
            for layer, rendered in record['rendered'].items():
                require(rendered['nodes'] == 73 and '영역 Si' in rendered['text'] and
                        'No interpolation' in rendered['text'], 'ACTUAL_MAP')
            coordinates = [pair[0 if axis == 'x' else 1] for pair in fields.xy_um]
            transverse = [pair[1 if axis == 'x' else 0] for pair in fields.xy_um]
            length = (max(coordinates) - min(coordinates)) * 1e-4
            height = (max(transverse) - min(transverse)) * 1e-4
            require(abs(length - (2e-4 if axis == 'x' else .5e-4)) <= 1e-18 and
                    abs(height - (.5e-4 if axis == 'x' else 2e-4)) <= 1e-18, 'ACTUAL_DIMENSIONS')
            reference = theory(1e16, 0., params['n_i'], params['ElectronCharge'], params['mu_n'], params['mu_p'], height, length)
            conductance = reference['G_A_per_V_per_cm_depth']
            isrc, ignd = point['currents'][source], point['currents'][ground]
            current_error = max(abs(isrc - conductance * voltage), abs(ignd + conductance * voltage)) / (conductance * abs(voltage)) if voltage else max(abs(isrc), abs(ignd)) / (conductance * .001)
            kcl = abs(isrc + ignd) / (conductance * .001)
            n_error = max(abs(n / reference['n0'] - 1) for n in fields.electron)
            ground_coordinate = min(coordinates) if side == 'max' else max(coordinates)
            ground_phi = [p for c, p in zip(coordinates, fields.potential) if c == ground_coordinate]
            require(bool(ground_phi), 'GROUND_NODES_MISSING')
            offset = sum(ground_phi) / len(ground_phi)
            fraction = [(c - min(coordinates)) / (max(coordinates) - min(coordinates)) for c in coordinates]
            if side == 'min':
                fraction = [1 - value for value in fraction]
            phi_error = max(abs(p - (offset + voltage * t)) for p, t in zip(fields.potential, fraction)) / max(abs(voltage), .001)
            metrics[name] = {'source_current_A_per_cm': isrc, 'ground_current_A_per_cm': ignd,
                'G_A_per_V_per_cm': conductance, 'current_error': current_error, 'kcl': kcl,
                'n_uniformity': n_error, 'potential_linearity': phi_error}
            for criterion, value, limit in (
                ('current', current_error, TOL_CURRENT if voltage else TOL_EQUILIBRIUM),
                ('kcl', kcl, TOL_CONSERVATION), ('carrier', n_error, TOL_N_UNIFORM),
                ('potential', phi_error, TOL_PSI_LINEAR)):
                checks.append({'name': name + '_' + criterion, 'value': value, 'limit': limit,
                               'pass': math.isfinite(value) and value <= limit})
        require(metrics['x_max_pos']['source_current_A_per_cm'] != 0, 'ZERO_AXIS_REFERENCE')
        ratio = metrics['y_max_pos']['source_current_A_per_cm'] / metrics['x_max_pos']['source_current_A_per_cm']
        checks.append({'name': 'axis_current_ratio', 'value': abs(ratio / 16 - 1), 'limit': TOL_CURRENT,
                       'pass': math.isfinite(ratio) and abs(ratio / 16 - 1) <= TOL_CURRENT})
        return {'pass': all(c['pass'] for c in checks), 'checks': checks, 'metrics': metrics, 'axis_current_ratio': ratio}
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError) as error:
        return {'pass': False, 'error': str(error), 'checks': checks, 'metrics': metrics}
