"""실제 측정 메서드 초입의 물리 상태 분류. 엔진/Tk를 import하지 않는다."""
import ast
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

def main():
    cls = next(n for n in ast.parse((ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8')).body
               if isinstance(n, ast.ClassDef) and n.name == 'TCADApplication')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run_measurement')
    prefix = []
    for node in method.body:
        if isinstance(node, ast.ImportFrom) and node.module == 'tcad.device.devsim':
            break
        prefix.append(node)
    fn = ast.FunctionDef(name='actual_prefix', args=method.args, body=prefix, decorator_list=[])
    ns = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), 'actual_prefix', 'exec'), ns)
    cases = {'none': None, 'empty': S(attachments=()), 'chemical': S(attachments=(S(chemical_state='CHEMICAL'),)),
             'unknown': S(attachments=(S(chemical_state='UNKNOWN'),)),
             'mixed': S(attachments=(S(chemical_state='ACTIVE'), S(chemical_state='CHEMICAL'))),
             'active_without_result': S(attachments=(S(chemical_state='ACTIVE'),))}
    for name, state in cases.items():
        messages = []; physics = []
        app = S(last_doped_result=None, wafer_state=state, last_physics_status='SENTINEL',
                _measurement_fields='STALE', _measurement_fields_context='STALE', _measurement_fields_result='STALE',
                meas_voltage_var=S(get=lambda: .001), history=[], redraw=lambda: None,
                _notify_info=lambda title, text: messages.append(text),
                _notify_error=lambda *args: (_ for _ in ()).throw(AssertionError(args)),
                _log_physics_status=lambda result: physics.append(result))
        ns['actual_prefix'](app)
        assert app.wafer_state is state and app.history == []
        assert app._measurement_fields is app._measurement_fields_context is app._measurement_fields_result is None
        if '--before' in sys.argv:
            assert app.last_physics_status == 'SENTINEL' and not physics
            assert 'has no carrier' in messages[0]
        else:
            expected = 'DOPANT_ACTIVATION_MODEL_MISSING' if name in {'chemical', 'unknown', 'mixed'} else 'DEVICE_PROFILE_NOT_AVAILABLE'
            status = app.last_physics_status
            assert status['resolution'] == 'UNSUPPORTED_BY_MODEL' and status['reason_code'] == expected
            assert physics == [{'physics_status': status}]
            assert expected in messages[0] and 'No doping write or solve' in messages[0]
            assert 'has no carrier' not in messages[0] and 'carries no doping profile' not in messages[0]
    print(json.dumps({'mode': 'before' if '--before' in sys.argv else 'after', 'cases': 6, 'engine_imports': 0}))

if __name__ == '__main__':
    main()
