"""실제 노드만 조회하는 pixel hover. 엔진/Tk import 없음."""
import ast
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as S
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
from tcad.characterization.node_fields import NodeFields,node_near_pixel
from tcad.characterization.source_context import capture_source_context
f=NodeFields('Si',((0,-1),(1,0)),(-.3,.2),(1e16,2e16),(1e4,2e4))
transform=(10,0,100,20,30)
for layer in ('potential','electron','hole'):
    assert node_near_pixel(f,layer,transform,10,50)==(0,-1,getattr(f,layer)[0])
    assert node_near_pixel(f,layer,transform,11,51)==(0,-1,getattr(f,layer)[0])
    assert node_near_pixel(f,layer,transform,13,50)==(0,-1,getattr(f,layer)[0])
    assert node_near_pixel(f,layer,transform,15,50) is None
tree=ast.parse((ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_measurement_field_hover_note']
ns={};exec(compile(ast.fix_missing_locations(ast.Module(body=methods,type_ignores=[])),'hover','exec'),ns)
with tempfile.TemporaryDirectory() as d:
    p=Path(d)/'mesh';p.write_bytes(b'synthetic nonmesh')
    st=object();settings=[.001,'x','max'];layer=['potential'];count=[2]
    app=S(viewer_layer_var=S(get=lambda:layer[0]),_viewing_step_index=None,_viewer_scale=transform,
          _measurement_fields=f,_measurement_fields_context=capture_source_context(p,st,[]),
          _measurement_fields_settings=tuple(settings),last_final_mesh=p,wafer_state=st,electrode_pins=[],
          meas_voltage_var=S(get=lambda:settings[0]),meas_axis_var=S(get=lambda:settings[1]),meas_source_pin=S(get=lambda:settings[2]),
          canvas=S(find_withtag=lambda tag:range(count[0])))
    call=lambda x=10,y=50:ns['_measurement_field_hover_note'](app,S(x=x,y=y))
    assert '-3.000000e-01 V' in call() and '보간 아님' in call()
    assert call(15)==''
    layer[0]='electron';assert '1.000000e+16 cm^-3' in call()
    for fault in ('bias','state','history','partial'):
        settings[0]=.001;app.wafer_state=st;app._viewing_step_index=None;count[0]=2
        if fault=='bias':settings[0]=.002
        if fault=='state':app.wafer_state=object()
        if fault=='history':app._viewing_step_index=0
        if fault=='partial':count[0]=1
        assert call()==''
reset=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='reset')
early=reset.body[:3]
assert all(isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and n.value.value is None for n in early)
assert {n.targets[0].attr for n in early}=={'_measurement_fields','_measurement_fields_context','_measurement_fields_settings'}
print('PASS exact nearby node/value/units; distant/stale/history/partial blocked; reset clears references; imports 0')
