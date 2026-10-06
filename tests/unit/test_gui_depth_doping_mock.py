"""실제 canonical 상태와 추출된 GUI 메서드 대조. 엔진/Tk import 없음."""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace as S
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
from tcad.physics.wafer_state_v2 import initialize_wafer_state,attach_dopant,uniform_inventory_integral
source=(ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8')
tree=ast.parse(source)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
names={'_doping_color_segments','_canvas_doping_query','_doping_color_at','_doping_unsupported_hover_note','_on_canvas_motion'}
ns={'_DOPING_UNSUPPORTED_MARKER':'UNKNOWN','_DOPING_ZERO_MARKER':'ZERO'}
exec(compile(ast.fix_missing_locations(ast.Module(body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[])),'gui_depth','exec'),ns)

def state(chemical='ACTIVE'):
    s=initialize_wafer_state(cells=[('Si',(-1,1,-2,0),'si')])
    for polarity,C,bounds,label in [('donor',1e17,(-1,1,-2,0),'ACTIVE'),('acceptor',2e17,(-1,1,-2,-1),chemical)]:
        s=attach_dopant(s,species=None,polarity=polarity,chemical_state=label,
            concentration_at=lambda x,y,C=C:C,inventory_integral=uniform_inventory_integral(C),
            support_instance_id='si',support_region_um=bounds,model='explicit_uniform')
    return s

def main():
    app=S(wafer_state=state(),_viewing_step_index=None,viewer_layer_var=S(get=lambda:'doping'))
    for name,fn in ns.items():
        if callable(fn) and name in names:
            setattr(app,name,lambda *args,fn=fn,**kw:fn(app,*args,**kw))
    if '--before' in sys.argv:
        segments=app._doping_color_segments('Si',-1,1)
        assert all(v[2]=='#2f6fed' for v in segments)
        assert app.wafer_state.net_doping_at(0,-1.5).net_doping==-1e17
        print('REPRODUCED: lower p region painted n by y=0 lookup; engine imports 0')
        return
    assert app._doping_color_at(0,-.5,'Si')=='#2f6fed'
    assert app._doping_color_at(0,-1.5,'Si')=='#e0393e'
    assert app._doping_color_at(0,-1.5,'SiO2')=='UNKNOWN'
    assert app._doping_color_at(0,-3,'Si')=='UNKNOWN'
    from dataclasses import replace
    s=app.wafer_state
    app.wafer_state=replace(s,cells=s.cells+(replace(s.cells[0],cell_id='overlap',material_instance_id='other'),))
    assert app._doping_color_at(0,-.5,'Si')=='UNKNOWN'
    app.wafer_state=replace(s,attachments=(replace(s.attachments[0],concentration_at=lambda x,y:float('nan')),))
    assert app._doping_color_at(0,-.5,'Si')=='UNKNOWN'
    for chemical in ('CHEMICAL','UNKNOWN'):
        app.wafer_state=state(chemical)
        assert app._doping_color_at(0,-.5,'Si')=='#2f6fed'
        assert app._doping_color_at(0,-1.5,'Si')=='UNKNOWN'
        assert app._doping_unsupported_hover_note(0,-.5)==''
        assert 'UNSUPPORTED' in app._doping_unsupported_hover_note(0,-1.5)
    app.wafer_state=initialize_wafer_state(cells=[('Si',(-1,1,-2,0),'si')])
    assert app._doping_color_at(0,-1,'Si')=='ZERO'
    app._viewing_step_index=0
    assert app._doping_color_at(0,-1,'Si')=='UNKNOWN'
    assert '이력' in app._doping_unsupported_hover_note(0,-1)
    motion=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_on_canvas_motion')
    assert 'self._doping_unsupported_hover_note(x_um, y_um)' in ast.get_source_segment(source,motion)
    print('PASS: depth-dependent p/n, activation, ownership, true zero, history, mouse y; engine imports 0')

if __name__=='__main__': main()
