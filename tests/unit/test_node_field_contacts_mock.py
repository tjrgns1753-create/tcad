"""2단자 저장 증거의 완전성. 합성 결과이며 엔진과 Tk import를 금지한다."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def deny(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals', 'tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
from tcad.characterization.node_fields import NodeFields, save_node_field_evidence
from tcad.characterization.interface import BiasPoint, CharacterizationResult, current_unit_metadata
from tcad.characterization.source_context import capture_source_context


def main():
    before_fix = '--before' in sys.argv
    cases = {
        'only_source': ({'source': .001}, {'source': 1e-6}),
        'missing_ground_current': ({'source': .001, 'ground': 0}, {'source': 1e-6}),
        'missing_ground_voltage': ({'source': .001}, {'source': 1e-6, 'ground': -1e-6}),
        'different_contacts': ({'source': .001, 'ground': 0}, {'source': 1e-6, 'other': -1e-6}),
        'extra_current': ({'source': .001, 'ground': 0}, {'source': 1e-6, 'ground': -1e-6, 'other': 0}),
        'three_contacts': ({'source': .001, 'ground': 0, 'other': 0}, {'source': 1e-6, 'ground': -1e-6, 'other': 0}),
        'blank_contact': ({'source': .001, '': 0}, {'source': 1e-6, '': -1e-6}),
        'non_string_contact': ({'source': .001, 7: 0}, {'source': 1e-6, 7: -1e-6}),
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        mesh = root / 'mesh'
        mesh.write_bytes(b'SYNTHETIC_NOT_PHYSICAL_MESH')
        context = capture_source_context(mesh, object(), [])
        fields = NodeFields('Si', ((0., 0.), (1., -.5)), (.3, .301), (1e16, 1e16), (1e4, 1e4))
        result = CharacterizationResult('synthetic', 'deleted', 'Si', 'source',
            [BiasPoint({'source': .001, 'ground': 0}, {'source': 1e-6, 'ground': -1e-6})], current_unit_metadata(2))
        target = root / '기록.json'
        outcomes = {}
        for name, (voltages, currents) in cases.items():
            target.write_bytes(b'EXISTING_EVIDENCE')
            candidate = replace(result, points=[BiasPoint(voltages, currents)])
            try:
                save_node_field_evidence(fields, candidate, context, target)
            except ValueError:
                outcomes[name] = 'BLOCKED'
            else:
                outcomes[name] = 'ACCEPTED'
            if not before_fix:
                assert outcomes[name] == 'BLOCKED', (name, outcomes[name])
                assert target.read_bytes() == b'EXISTING_EVIDENCE'
                assert not list(root.glob('.node_fields_*.tmp'))
        if before_fix:
            assert all(value == 'ACCEPTED' for value in outcomes.values()), outcomes
        else:
            controls = [result, replace(result, sweep_contact='custom left', points=[BiasPoint(
                {'custom left': .4, 'custom right': .399}, {'custom left': -1e-6, 'custom right': 1e-6})]),
                replace(result, points=[BiasPoint({'source': 0, 'ground': 0}, {'source': 0, 'ground': 0})])]
            for control in controls:
                save_node_field_evidence(fields, control, context, target)
                payload = json.loads(target.read_text(encoding='utf-8'))
                assert payload['measurement']['voltages'] == control.points[0].voltages
                assert payload['measurement']['currents'] == control.points[0].currents
                assert payload['snapshot']['potential'] == [.3, .301]
            missing_sweep = replace(result, sweep_contact='not present')
            original = target.read_bytes()
            try:
                save_node_field_evidence(fields, missing_sweep, context, target)
            except ValueError:
                pass
            else:
                raise AssertionError('Missing sweep contact accepted')
            assert target.read_bytes() == original
        print(json.dumps({'mode': 'before' if before_fix else 'after', 'cases': outcomes,
            'normal_controls': None if before_fix else 3, 'engine_imports': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
