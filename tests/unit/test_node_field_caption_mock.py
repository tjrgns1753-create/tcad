"""caption은 실제 결과의 영역·바이어스만 설명한다. 엔진·Tk import 없음."""
import ast
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as S
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def deny(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals', 'tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
from tcad.characterization.node_fields import NodeFields
from tcad.characterization.interface import BiasPoint, CharacterizationResult, current_unit_metadata
from tcad.characterization.source_context import capture_source_context


def main():
    tree = ast.parse((ROOT / 'tcad_2d_stagewise.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TCADApplication')
    draw = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_draw_measurement_field')
    ns = {'Tokens': S(FG_MUTED='gray', FONT_UI='Arial')}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[draw], type_ignores=[])), 'draw', 'exec'), ns)
    fields = NodeFields('Si', ((0, 0), (1, -.5)), (.3576, .3586), (1e16, 1e16), (1e4, 1e4))
    result = CharacterizationResult('synthetic', 'deleted', 'Si', 'right',
        [BiasPoint({'left': 0, 'right': .001}, {'left': -1e-6, 'right': 1e-6})], current_unit_metadata(2))
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'mesh'
        path.write_bytes(b'SYNTHETIC_NOT_GEOMETRY')
        state = object()
        nodes, notes = [], []
        app = S(last_final_mesh=path, wafer_state=state, electrode_pins=[], _viewing_step_index=None,
            _measurement_fields=fields, _measurement_fields_result=result,
            _measurement_fields_context=capture_source_context(path, state, []),
            _measurement_fields_settings=(.001, 'x', 'max'), _viewer_scale=(0, 0, 1, 0, 1),
            meas_voltage_var=S(get=lambda: .001), meas_axis_var=S(get=lambda: 'x'), meas_source_pin=S(get=lambda: 'max'),
            canvas=S(create_oval=lambda *a, **kw: nodes.append((a, kw)),
                     create_text=lambda *a, **kw: notes.append(kw['text'])))
        draw_field = lambda layer: ns['_draw_measurement_field'](app, layer, 0, 600, 100)
        draw_field('potential')
        if '--before' in sys.argv:
            assert len(nodes) == 2 and '영역 Si' not in notes[-1] and 'left=+0 V' not in notes[-1]
            assert '원시 Potential' not in notes[-1]
            print('REPRODUCED missing region/contact bias/potential-reference explanation')
            return
        for layer, unit in [('potential', 'V'), ('electron', 'cm^-3'), ('hole', 'cm^-3')]:
            nodes.clear()
            draw_field(layer)
            note = notes[-1]
            assert len(nodes) == 2 and '영역 Si' in note
            assert 'left=+0 V' in note and 'right=+0.001 V' in note
            assert 'actual node samples' in note and 'No interpolation' in note and unit in note
            assert ('원시 Potential' in note) == (layer == 'potential')
            assert app._measurement_fields is fields and fields.potential == (.3576, .3586)
        for bad in [None, replace(result, region='other'), replace(result, points=[]),
                    replace(result, points=[BiasPoint({'left': 0, 'right': float('nan')}, {'left': -1e-6, 'right': 1e-6})]),
                    replace(result, points=[BiasPoint({'right': .001}, {'right': 1e-6})])]:
            app._measurement_fields_result = bad
            nodes.clear()
            draw_field('potential')
            assert not nodes and notes[-1].startswith('Field unavailable:')
        print('PASS caption region/all contacts/units/reference; bad result has no numeric map; arrays unchanged; imports 0')


if __name__ == '__main__':
    main()
