"""AST로 표시 안내만 실행한다. Tk/engine import 없이 계약을 검사한다."""
import ast
from pathlib import Path
from types import SimpleNamespace as S
import sys

def no_engine(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(no_engine)
source=(Path(__file__).resolve().parents[2]/'tcad_2d_stagewise.py').read_text(encoding='utf-8')
tree=ast.parse(source)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
note=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_canvas_state_note')
ns={}
exec(compile(ast.fix_missing_locations(ast.Module(body=[note],type_ignores=[])),'canvas_note','exec'),ns)
def check(state,physics=None,view=None):
    return ns['_canvas_state_note'](S(wafer_state=state,last_physics_status=physics,_viewing_step_index=view))
known=S(cells=[S(lifecycle='ACTIVE')],attachments=[S(chemical_state='ACTIVE')],unresolved_inventory=[])
assert '실제 mesh' in check(known)
assert '별도' in check(known)
for state in (S(cells=[S(lifecycle='UNRESOLVED')]),S(cells=[S(lifecycle='LEGACY_UNRESOLVED')]),
              S(unresolved_inventory=[object()]),S(attachments=[S(chemical_state='CHEMICAL')]),
              S(attachments=[S(chemical_state='UNKNOWN')])):
    assert 'UNSUPPORTED_BY_MODEL' in check(state)
assert 'UNSUPPORTED_BY_MODEL' in check(known,{'resolution':'UNSUPPORTED_BY_MODEL'})
assert '이력 mesh' in check(known,view=0)
redraw=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='redraw')
text=ast.get_source_segment(source,redraw)
assert 'visual_depth' not in text and 'VIENNAPS\\n' not in text
assert 'self.wafer.processed\n            and display_mesh' not in text
assert 'mesh_expected and not real_mesh_available' in text
import numpy as np
draw=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_draw_real_mesh_result')
transform=next(n for n in ast.walk(draw) if isinstance(n,ast.FunctionDef) and n.name=='to_canvas')
points=np.array([[-5.,-5.],[5.,0.]],dtype=np.float32)
scope={'points':points,'x0':70.,'x_min':-5.,'x_scale':56.,'surface_y':297.6,'y_scale':37.4}
exec(compile(ast.fix_missing_locations(ast.Module(body=[transform],type_ignores=[])),'canvas_transform','exec'),scope)
for i in range(2):
    cx,cy=scope['to_canvas'](i)
    assert abs((cx-70.)/56.-5.-float(points[i,0]))<1e-12
    assert abs((297.6-cy)/37.4-float(points[i,1]))<1e-12
print('PASS: 9 disclosure states, invented etch removed, source gating; engine imports 0')
