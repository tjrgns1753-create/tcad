"""단일 파일 export 원자성·수치·출처. 합성 자료이며 엔진 import 없음."""
import ast
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as S
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
from tcad.characterization.node_fields import NodeFields,save_node_field_evidence
from tcad.characterization.interface import BiasPoint,CharacterizationResult,current_unit_metadata
from tcad.characterization.source_context import capture_source_context
tree=ast.parse((ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_on_export_node_fields_clicked')
calls=[];ns={'filedialog':S(asksaveasfilename=lambda **kw:calls.append(kw))}
exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'export','exec'),ns)
with tempfile.TemporaryDirectory() as d:
    p=Path(d)/'mesh';p.write_bytes(b'synthetic, not mesh');out=Path(d)/'한국어.json';st=object()
    context=capture_source_context(p,st,[])
    f=NodeFields('Si',((0,0),(1,-1)),(-.3,.2),(1e16,2e16),(1e4,2e4))
    result=CharacterizationResult(name='synthetic',device='deleted',region='Si',sweep_contact='a',
        points=[BiasPoint({'a':.001,'b':0},{'a':1e-6,'b':-1e-6})],metadata=current_unit_metadata(2))
    save_node_field_evidence(f,result,context,out)
    before=out.read_bytes();payload=json.loads(before)
    assert payload['snapshot']['potential']==[-.3,.2] and payload['measurement']['currents']['b']==-1e-6
    assert payload['measurement']['metadata']['current_unit']=='A/cm' and payload['source_evidence']['canonical_record']=='GUI_SESSION_ONLY'
    for bad in (replace(f,potential=(float('nan'),.2)),replace(f,electron=(-1.,2e16)),replace(f,hole=()),
                replace(f,xy_um=((float('inf'),0),(1,-1)))):
        try:save_node_field_evidence(bad,result,context,out)
        except ValueError:pass
        else:raise AssertionError('invalid fields accepted')
        assert out.read_bytes()==before and not list(Path(d).glob('*.tmp'))
    for bad in (replace(result,points=[]),replace(result,points=[replace(result.points[0],converged=False)]),
                replace(result,metadata={}),replace(result,region='other')):
        try:save_node_field_evidence(f,bad,context,out)
        except ValueError:pass
        else:raise AssertionError('invalid result accepted')
        assert out.read_bytes()==before
    settings=[.001,'x','max'];errors=[]
    app=S(_viewing_step_index=None,_measurement_fields=f,_measurement_fields_result=result,
        _measurement_fields_context=context,_measurement_fields_settings=tuple(settings),
        last_final_mesh=p,wafer_state=st,electrode_pins=[],meas_voltage_var=S(get=lambda:settings[0]),
        meas_axis_var=S(get=lambda:settings[1]),meas_source_pin=S(get=lambda:settings[2]),_notify_error=lambda *a:errors.append(a),_log=lambda msg:None)
    for fault in ('state','bias','history','missing'):
        app.wafer_state=st;settings[0]=.001;app._viewing_step_index=None;app._measurement_fields=f
        if fault=='state':app.wafer_state=object()
        if fault=='bias':settings[0]=.002
        if fault=='history':app._viewing_step_index=0
        if fault=='missing':app._measurement_fields=None
        ns['_on_export_node_fields_clicked'](app)
        assert not calls
    app.wafer_state=st;app._measurement_fields=f;app._viewing_step_index=None;settings[0]=.001
    def changed_dialog(**kw):settings[0]=.002;calls.append(kw);return str(out)
    ns['filedialog']=S(asksaveasfilename=changed_dialog)
    ns['_on_export_node_fields_clicked'](app)
    assert len(calls)==1 and out.read_bytes()==before
print('PASS all-array/single-bias/unit/source JSON; invalid preserves file; stale before/after dialog blocked; imports 0')
