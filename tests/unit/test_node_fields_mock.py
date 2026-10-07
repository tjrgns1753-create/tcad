"""엔진 없는 공식 조회 API 모형과 실제 GUI 표시 메서드 검증."""
import ast
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as S
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_OR_TK_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
from tcad.characterization.node_fields import capture_node_fields,field_samples,MAX_CAPTURE_NODES
from tcad.characterization.source_context import capture_source_context
class API:
    def __init__(self):
        self.a={'x':[0,1e-4], 'y':[0,-1e-4], 'Potential':[-.2,.3], 'Electrons':[1e16,2e16], 'Holes':[1e4,0]}
    def get_node_model_list(self,**kw): return list(self.a)
    def get_node_model_values(self,**kw): return self.a[kw['name']]
api=API(); fields=capture_node_fields(api,'device','Si',1e-4)
assert fields.xy_um==((0,0),(1,-1)) and fields.potential==(-.2,.3)
api.a.clear(); assert fields.electron==(1e16,2e16)
for change in ('missing','nan','length','negative','cap'):
    api=API()
    if change=='missing': del api.a['Holes']
    if change=='nan': api.a['Potential'][0]=float('nan')
    if change=='length': api.a['y']=[]
    if change=='negative': api.a['Holes'][0]=-1
    if change=='cap': api.a['x']=[0]*(MAX_CAPTURE_NODES+1)
    try: capture_node_fields(api,'device','Si',1e-4)
    except ValueError: pass
    else: raise AssertionError(change)
for layer in ('potential','electron','hole'):
    samples,lo,hi=field_samples(fields,layer)
    assert len(samples)==2 and [s[2] for s in samples]==list(getattr(fields,layer))
tree=ast.parse((ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
draw=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_draw_measurement_field')
ns={'Tokens':S(FG_MUTED='gray',FONT_UI='Arial')}
exec(compile(ast.fix_missing_locations(ast.Module(body=[draw],type_ignores=[])),'draw','exec'),ns)
with tempfile.TemporaryDirectory() as d:
    p=Path(d)/'mesh'; p.write_bytes(b'fixture only, not real geometry')
    state=object(); settings=[.001,'x','max']; nodes=[]; notes=[]
    app=S(last_final_mesh=p,wafer_state=state,electrode_pins=[],_viewing_step_index=None,
          _measurement_fields=fields,_measurement_fields_context=capture_source_context(p,state,[]),
          _measurement_fields_settings=tuple(settings),_viewer_scale=(0,0,1,0,1),
          meas_voltage_var=S(get=lambda:settings[0]),meas_axis_var=S(get=lambda:settings[1]),meas_source_pin=S(get=lambda:settings[2]),
          canvas=S(create_oval=lambda *a,**k:nodes.append((a,k)),create_text=lambda *a,**k:notes.append(k['text'])))
    ns['_draw_measurement_field'](app,'potential',0,100,20)
    assert len(nodes)==2 and 'actual node samples' in notes[-1]
    for fault in ('state','mesh','bias','history'):
        nodes.clear()
        app.wafer_state=state; p.write_bytes(b'fixture only, not real geometry'); settings[0]=.001;app._viewing_step_index=None
        if fault=='state': app.wafer_state=object()
        if fault=='mesh': p.write_bytes(b'changed')
        if fault=='bias': settings[0]=.002
        if fault=='history':app._viewing_step_index=0
        ns['_draw_measurement_field'](app,'potential',0,100,20)
        assert not nodes and notes[-1].startswith('Field unavailable:')
print('PASS capture/copy/invalid arrays/all nodes/stale evidence/history; engine/Tk imports 0')
