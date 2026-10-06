"""원격 실제 Tk canvas 반례 및 ViennaPS 출력 대응 검사."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
    raise RuntimeError('REMOTE_ONLY')
if '--before' in sys.argv:
    import subprocess
    import types
    revision='4316c3f'
    old=subprocess.check_output(['git','show',revision+':tcad_2d_stagewise.py'],cwd=ROOT).decode('utf-8')
    G=types.ModuleType('canvas_before_gui')
    G.__file__=str(ROOT/'tcad_2d_stagewise.py')
    sys.modules[G.__name__]=G
    exec(compile(old,G.__file__,'exec'),G.__dict__)
else:
    import tcad_2d_stagewise as G

def texts(app):
    return [app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']

def solids(app):
    return [(app.canvas.type(i),app.canvas.itemcget(i,'fill'),app.canvas.coords(i))
            for i in app.canvas.find_all() if app.canvas.type(i) in ('rectangle','polygon')]

def main():
    before='--before' in sys.argv
    out=ROOT/('e6nh_before_out' if before else 'e6nh_out'); out.mkdir(exist_ok=True)
    app=G.TCADApplication(); app.withdraw(); app.update_idletasks()
    observations={}
    try:
        app.wafer.processed=True
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'invalid.vtu'
            app.last_final_mesh=str(path)
            app.redraw()
            observations['missing']={'texts':texts(app),'solid_count':len(solids(app))}
            if before:
                assert 'Si substrate' in texts(app) and solids(app)
            else:
                assert '형상 표시 차단' in '\n'.join(texts(app)) and not solids(app)
                assert app._viewer_scale is None
            import meshio
            meshio.write(path,meshio.Mesh([[0.,0.,0.]],cells=[('vertex',[[0]])]))
            app.redraw()
            observations['corrupt']={'texts':texts(app),'solid_count':len(solids(app))}
            if before:
                assert 'Si substrate' in texts(app) and solids(app)
            else:
                assert '형상 표시 차단' in '\n'.join(texts(app)) and not solids(app)
            path.write_text('not a volume mesh',encoding='utf-8')
            terminated=False
            try:
                app.redraw()
            except SystemExit:
                terminated=True
            observations['malformed']={'system_exit':terminated,'texts':texts(app)}
            assert terminated is before
            if not before:
                assert '형상 표시 차단' in '\n'.join(texts(app)) and not solids(app)
        if not before:
            app.reset(); app.redraw()
            assert '입력 도식' in '\n'.join(texts(app))
            app.grid_var.set(.2)
            assert app._materialize_current_wafer()
            path=app.last_final_mesh
            # A real mesh remains authoritative even if a zero-duration UI flag is false.
            app.wafer.processed=False; app.redraw()
            assert '실제 mesh' in '\n'.join(texts(app))
            import meshio
            mesh=meshio.read(path)
            color=G.TCADApplication._MATERIAL_COLORS['Si']
            si=[coords for kind,fill,coords in solids(app) if fill==color]
            assert si
            x0,xmin,sx,surface,sy=app._viewer_scale
            points=[((coords[i]-x0)/sx+xmin,(surface-coords[i+1])/sy)
                    for coords in si for i in range(0,len(coords),2)]
            import numpy as np
            drawn=np.asarray(points)
            assert np.allclose(drawn.min(axis=0),mesh.points[:,:2].min(axis=0),rtol=0,atol=1e-7)
            assert np.allclose(drawn.max(axis=0),mesh.points[:,:2].max(axis=0),rtol=0,atol=1e-7)
            before_si=si
            app.ox_time_var.set(.5)
            app.run_oxidation(); app.redraw()
            assert '미지원' in '\n'.join(texts(app))
            after_si=[coords for kind,fill,coords in solids(app) if fill==color]
            assert before_si==after_si
            observations['real_geometry']={'canvas_mesh_bbox_match':True,'unsupported_geometry_preserved':True,
                                            'texts':texts(app)}
            app.completed_steps=[{}]; app.flow_step_meshes=[path]; app._viewing_step_index=0
            app.redraw()
            assert '이력 mesh' in '\n'.join(texts(app))
            app.reset(); app.redraw()
            assert '입력 도식' in '\n'.join(texts(app)) and '미지원' not in '\n'.join(texts(app))
        (out/'canvas.json').write_text(json.dumps(observations,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS: '+('before-fix false geometry reproduced' if before else 'actual canvas source contract and mesh bounds'))
    finally:
        app.destroy()

if __name__=='__main__':
    main()
