"""redraw 초입의 실제 코드로 stale 숫자를 재현/차단. 엔진/Tk 없음."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace as S
ROOT=Path(__file__).resolve().parents[2]
tree=ast.parse((ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='redraw')
# Execute only the real prefix preceding widget size queries. No geometry/import.
prefix=[]
for n in method.body:
    if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='width' for t in n.targets):break
    prefix.append(n)
fn=ast.FunctionDef(name='prefix',args=method.args,body=prefix,decorator_list=[])
ns={};exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'prefix','exec'),ns)
text=['stale node Potential=0.3576 V'];deleted=[]
app=S(canvas=S(delete=lambda tag:deleted.append(tag)),coord_var=S(set=lambda v:text.__setitem__(0,v)))
ns['prefix'](app)
if '--before' in sys.argv:
    assert text[0].startswith('stale');print('REPRODUCED: redraw deletes map but keeps old node numeric readout')
else:
    assert text[0]=='' and deleted==['all'];print('PASS actual redraw prefix clears stale numeric readout; engine/Tk imports 0')
