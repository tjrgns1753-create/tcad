"""측정 경계 계약. 합성 데이터이며 엔진/물리 검증을 주장하지 않는다."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace as S
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
def deny(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
source = (ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8')
cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'TCADApplication')
names = {'run_dc_operating_point', '_on_dc_operating_point_clicked', 'run_measurement'}
ns = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=[n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])), 'extracted_gui', 'exec'), ns)
logs = []
app = S(last_electrode_import=None, last_electrode_result=object(), _log=logs.append, _notify_error=lambda *a: logs.append(str(a)))
ns['run_dc_operating_point'](app, .1, 1.)
if '--before' in sys.argv:
    assert app.last_electrode_result is not None
    print('REPRODUCED: failed DC retry keeps previous export result; engine imports 0')
else:
    assert app.last_electrode_result is None
    from tcad.characterization.interface import BiasPoint, validate_bias_point
    good = BiasPoint({'a': .1, 'b': 0.}, {'a': -1e-10, 'b': 1e-10})
    assert validate_bias_point(good, ('a', 'b')) is None
    for point in (BiasPoint({}, {}), BiasPoint(good.voltages, good.currents, False),
                  BiasPoint(good.voltages, {'a': 1.}),
                  *[BiasPoint({'a': bad, 'b': 0.}, good.currents) for bad in (float('nan'), float('inf'))],
                  *[BiasPoint(good.voltages, {'a': bad, 'b': 0.}) for bad in (float('nan'), -float('inf'))]):
        try: validate_bias_point(point, ('a', 'b'))
        except ValueError: pass
        else: raise AssertionError('invalid result accepted')
    for bad in (float('nan'), float('inf'), -float('inf')):
        app.last_electrode_import = object()
        app.last_electrode_result = object()
        ns['run_dc_operating_point'](app, bad, 1.)
        assert app.last_electrode_result is None
        # A sentinel import would fail attribute access if validation ran too late.
        app.last_doped_result = object()
        app.meas_voltage_var = S(get=lambda bad=bad: str(bad))
        ns['run_measurement'](app)
    app.dc_drain_v_var=S(get=lambda:'bad')
    app.dc_gate_v_var=app.dc_body_v_var=S(get=lambda:'0')
    app.last_electrode_result=object()
    ns['_on_dc_operating_point_clicked'](app)
    assert app.last_electrode_result is None
    assert source.count('validate_bias_point(') == 2
    print('PASS: finite input/result, missing contact, failed retry; engine imports 0')
