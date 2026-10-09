"""실제 GUI preflight를 AST로 읽어 engine 없이 실행한다."""
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace as S
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
from tcad.physics.wafer_state_v2 import initialize_wafer_state
def main():
    cls=next(n for n in ast.parse((ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8')).body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='run_measurement')
    prefix=[]
    for n in method.body:
        if isinstance(n,ast.ImportFrom) and n.module=='tcad.device.devsim': break
        prefix.append(n)
    fn=ast.FunctionDef(name='actual_prefix',args=method.args,body=prefix,decorator_list=[])
    ns={}; exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'actual_prefix','exec'),ns)
    state=initialize_wafer_state(cells=[('Si',(-1.,1.,-.5,0.),'substrate')]); messages=[]; statuses=[]
    app=S(last_doped_result=None,wafer_state=state,last_final_mesh='not_opened',last_physics_status='OLD_MODELLED',
        _measurement_fields='STALE',_measurement_fields_context='STALE',_measurement_fields_result='STALE',
        meas_voltage_var=S(get=lambda:.002),meas_axis_var=S(get=lambda:'x'),history=[],redraw=lambda:None,
        _notify_error=lambda *a:messages.append(a),_log_physics_status=lambda result:statuses.append(result))
    ns['actual_prefix'](app)
    assert app.wafer_state is state and not app.history and app._measurement_fields is None
    assert messages and 'INTRINSIC_LOW_FIELD_CAPABILITY_UNVERIFIED' in messages[0][1]
    if '--before' in sys.argv:
        assert app.last_physics_status=='OLD_MODELLED' and not statuses
    else:
        assert app.last_physics_status['resolution']=='UNSUPPORTED_BY_MODEL'
        assert app.last_physics_status['reason_code']=='INTRINSIC_LOW_FIELD_CAPABILITY_UNVERIFIED'
        assert statuses==[{'physics_status':app.last_physics_status}]
    print(json.dumps({'before':'--before' in sys.argv,'stale_state_reproduced':'--before' in sys.argv,'engine_imports':0}))
if __name__=='__main__': main()
