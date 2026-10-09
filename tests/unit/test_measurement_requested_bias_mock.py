"""실제 GUI의 반환 기록 gate를 AST로 실행. 합성 반례, 엔진·Tk import 없음."""
import ast
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace as S
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def deny(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals', 'tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
from tcad.characterization.interface import BiasPoint, CharacterizationResult, current_unit_metadata, validate_bias_point


def main():
    cls = next(n for n in ast.parse((ROOT / 'tcad_2d_stagewise.py').read_text(encoding='utf-8')).body
               if isinstance(n, ast.ClassDef) and n.name == 'TCADApplication')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run_measurement')
    body = next(n.body for n in ast.walk(method) if isinstance(n, ast.Try)
                and any(isinstance(s, ast.If) and ast.unparse(s.test) == 'len(result.points) != 1' for s in n.body))
    start = next(i for i, n in enumerate(body) if isinstance(n, ast.If) and ast.unparse(n.test) == 'len(result.points) != 1')
    stop = next(i for i, n in enumerate(body) if isinstance(n, ast.ImportFrom) and n.module == 'tcad.characterization.node_fields')
    code = compile(ast.fix_missing_locations(ast.Module(body=body[start:stop], type_ignores=[])), 'actual_result_gate', 'exec')
    source, ground = 'Si_xmax', 'Si_xmin'
    base = CharacterizationResult('synthetic', 'deleted', 'Si', source,
        [BiasPoint({source: .001, ground: 0}, {source: 1e-6, ground: -1e-6})], current_unit_metadata(2))
    point = base.points[0]
    cases = {
        'wrong_source_voltage': replace(base, points=[replace(point, voltages={source: .002, ground: 0})]),
        'wrong_ground_voltage': replace(base, points=[replace(point, voltages={source: .001, ground: .1})]),
        'wrong_region': replace(base, region='other'),
        'wrong_sweep_contact': replace(base, sweep_contact=ground),
        'extra_voltage': replace(base, points=[replace(point, voltages={source: .001, ground: 0, 'other': 0})]),
        'extra_current': replace(base, points=[replace(point, currents={source: 1e-6, ground: -1e-6, 'other': 0})]),
    }
    ns = {'source_contact': source, 'gnd_contact': ground, 'region': 'Si', 'voltage': .001,
          'imported': S(contacts=[ground, source]), 'validate_bias_point': validate_bias_point}
    outcomes = {}
    for name, result in cases.items():
        ns['result'] = result
        try:
            exec(code, ns)
        except ValueError:
            outcomes[name] = 'BLOCKED'
        else:
            outcomes[name] = 'ACCEPTED'
    before = '--before' in sys.argv
    if before:
        assert set(outcomes.values()) == {'ACCEPTED'}, outcomes
    else:
        assert set(outcomes.values()) == {'BLOCKED'}, outcomes
        for voltage in (.001, -.001, 0):
            ns['voltage'] = voltage
            ns['result'] = replace(base, points=[BiasPoint({source: voltage, ground: 0}, {source: -1e-6, ground: 1e-6})])
            exec(code, ns)
        # Optional check does not turn a separate ideal gate into an invented DD current.
        multi = BiasPoint({'a': .1, 'b': 0, 'gate': 1}, {'a': 0, 'b': 0})
        validate_bias_point(multi, ('a', 'b'), expected_voltages={'a': .1, 'b': 0, 'gate': 1})
        validate_bias_point(multi, ('a', 'b'))
        for expected in ({'missing': 0}, {'a': float('nan')}, {'gate': 2}):
            try:
                validate_bias_point(multi, ('a', 'b'), expected_voltages=expected)
            except ValueError:
                pass
            else:
                raise AssertionError('Invalid expected voltage accepted')
    print(json.dumps({'mode': 'before' if before else 'after', 'cases': outcomes,
        'normal_bias_controls': None if before else 3, 'engine_imports': 0}))


if __name__ == '__main__':
    main()
