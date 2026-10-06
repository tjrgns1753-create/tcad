"""접점 출처 순수 반례. 실제 엔진/물리 검증이 아니다."""
import ast
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as S, ModuleType
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_OR_TK_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
tree=ast.parse((ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
methods={'_on_export_result_clicked','run_dc_operating_point'}
ns={}
exec(compile(ast.fix_missing_locations(ast.Module(body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in methods],type_ignores=[])), 'gui_source','exec'),ns)
dialog=[]
tk=ModuleType('tkinter'); tk.filedialog=S(asksaveasfilename=lambda **kw:dialog.append('opened'))
io=ModuleType('tcad.characterization.io'); io.save_csv=lambda *a:None
app=S(last_electrode_result=object(),last_final_mesh=None,wafer_state=object(),electrode_pins=[],
      _notify_info=lambda *a:None,_notify_error=lambda *a:None,_log=lambda *a:None)
with patch.dict(sys.modules,{'tkinter':tk,'tcad.characterization.io':io}):
    ns['_on_export_result_clicked'](app)
if '--before' in sys.argv:
    assert dialog==['opened']
    print('REPRODUCED: exporter opens dialog with no source evidence; imports 0')
    raise SystemExit(0)
assert not dialog and app.last_electrode_result is None
from tcad.characterization.source_context import capture_source_context, source_context_matches
from tcad.mesh.pin import Pin
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'mesh.vtu'; path.write_bytes(b'original mesh')
    state=object(); pins=[Pin('s','Source',0.,0.)]
    context=capture_source_context(path,state,pins)
    assert source_context_matches(context,path,state,pins)
    assert not source_context_matches(None,path,state,pins)
    assert not source_context_matches(context,path,object(),pins)
    pins[0].role='Drain'
    assert not source_context_matches(context,path,state,pins)
    pins[0].role='Source'; pins[0].x_um=1.
    assert not source_context_matches(context,path,state,pins)
    pins[0].x_um=0.
    path.write_bytes(b'changed mesh')
    assert not source_context_matches(context,path,state,pins)
    path.write_bytes(b'original mesh')
    assert source_context_matches(context,path,state,pins)
    path.unlink()
    assert not source_context_matches(context,path,state,pins)
app.last_electrode_import=object()
cleared=[]
app._cleanup_electrode_device=lambda:cleared.append(True)
assert ns['run_dc_operating_point'](app,.1,1.) is None
assert cleared==[True]
print('PASS: changed state/pin/mesh, missing source, same source, export/DC blocked; imports 0')
