"""해석식 합성 정상/오류 wrapper 검사. 실제 엔진 증거를 생성하지 않는다."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def deny(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals', 'tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
from judge import CASES, EXPECTED_PARAMS, evaluate, theory
from tcad.characterization.node_fields import NodeFields, field_caption
from tcad.characterization.interface import BiasPoint, CharacterizationResult, current_unit_metadata


def main():
    records = {}
    xy = tuple((-1 + (i % 9) / 4, -.5 + (i // 9) / 16) for i in range(73))
    for name, axis, side, voltage in CASES:
        source, ground = f'Si_{axis}{side}', f'Si_{axis}{"min" if side == "max" else "max"}'
        reference = theory(1e16, 0, 1e10, 1.6e-19, 400, 200, .5e-4 if axis == 'x' else 2e-4, 2e-4 if axis == 'x' else .5e-4)
        coordinate = [p[0 if axis == 'x' else 1] for p in xy]
        fraction = [(c - min(coordinate)) / (max(coordinate) - min(coordinate)) for c in coordinate]
        if side == 'min':
            fraction = [1 - value for value in fraction]
        fields = NodeFields('Si', xy, tuple(.3576 + voltage * t for t in fraction),
                            (reference['n0'],) * 73, (reference['p0'],) * 73)
        current = reference['G_A_per_V_per_cm_depth'] * voltage
        result = CharacterizationResult('synthetic', 'none', 'Si', source,
            [BiasPoint({source: voltage, ground: 0}, {source: current, ground: -current})], current_unit_metadata(2))
        records[name] = {'axis': axis, 'side': side, 'voltage': voltage, 'solves': 3,
            'device_cleanup': True, 'live_api_equal': True, 'params': EXPECTED_PARAMS,
            'snapshot': asdict(fields), 'measurement': asdict(result), 'export_equal': True,
            'success_log_present': True, 'rendered': {layer: {'nodes': 73, 'text': field_caption(fields, result, layer)}
                                                   for layer in ('potential', 'electron', 'hole')}}
    verdict = evaluate(records)
    assert verdict['pass'] is True and verdict['axis_current_ratio'] == 16
    for fault in ('missing', 'wrong_sign', 'wrong_axis_size', 'nan', 'missing_ground', 'empty_point', 'changed_parameters'):
        bad = deepcopy(records)
        row = bad['x_max_pos']
        if fault == 'missing':
            bad.pop('y_max_zero')
        if fault == 'wrong_sign':
            row['measurement']['points'][0]['currents']['Si_xmax'] *= -1
        if fault == 'wrong_axis_size':
            row['snapshot']['xy_um'] = [(x * 2, y) for x, y in row['snapshot']['xy_um']]
        if fault == 'nan':
            row['snapshot']['potential'] = (float('nan'),) * 73
        if fault == 'missing_ground':
            row['measurement']['points'][0]['currents'].pop('Si_xmin')
        if fault == 'empty_point':
            row['measurement']['points'] = []
        if fault == 'changed_parameters':
            row['params']['mu_n'] = 800
        assert evaluate(bad)['pass'] is False, fault
    print('PASS synthetic analytic wrapper + 7 faults; not actual physical evidence; engine imports 0')


if __name__ == '__main__':
    main()
