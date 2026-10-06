"""원격 실제 Tk/ViennaPS mesh와 canonical 깊이별 p/n 표시 대조."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace as S
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
    raise RuntimeError('REMOTE_ONLY')
import numpy as np
import meshio
import tcad_2d_stagewise as G
from tcad.physics.wafer_state_v2 import initialize_wafer_state,attach_dopant,uniform_inventory_integral

def state(bounds,chemical='ACTIVE',zero=False):
    s=initialize_wafer_state(cells=[('Si',bounds,'si')])
    if zero: return s
    lower=(bounds[0],bounds[1],bounds[2],.5*(bounds[2]+bounds[3]))
    for polarity,C,support,label in [('donor',1e17,bounds,'ACTIVE'),('acceptor',2e17,lower,chemical)]:
        s=attach_dopant(s,species=None,polarity=polarity,chemical_state=label,
            concentration_at=lambda x,y,C=C:C,inventory_integral=uniform_inventory_integral(C),
            support_instance_id='si',support_region_um=support,model='explicit_uniform')
    return s

def main():
    out=ROOT/'e6ni_out'; out.mkdir(exist_ok=True)
    app=G.TCADApplication(); app.withdraw(); app.update_idletasks()
    records={}
    try:
        app.grid_var.set(.5)
        assert app._materialize_current_wafer()
        path=app.last_final_mesh
        original=Path(path).read_bytes()
        mesh=meshio.read(path)
        block=next(i for i,c in enumerate(mesh.cells) if c.type=='triangle')
        tri=mesh.cells[block].data
        assert len(tri)<=G._MAX_RENDERED_TRIANGLES
        bounds=(-5.,5.,-5.,0.)  # explicit GUI virgin construction input, not inverse-derived
        app.viewer_layer_var.set('doping')
        app.last_doped_result=S(doping=S(regions=[S(region='Si')]))
        # Reproduce the old y=0 result from exact prior source, without checkout edits.
        import ast
        import subprocess
        old=subprocess.check_output(['git','show','af3fafa:tcad_2d_stagewise.py'],cwd=ROOT).decode('utf-8')
        cls=next(n for n in ast.parse(old).body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_doping_color_segments')
        ns={'_DOPING_UNSUPPORTED_MARKER':G._DOPING_UNSUPPORTED_MARKER,'_DOPING_ZERO_MARKER':G._DOPING_ZERO_MARKER}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'before_depth','exec'),ns)
        app.wafer_state=state(bounds)
        old_colors=ns['_doping_color_segments'](app,'Si',-5,5)
        assert all(v[2]=='#2f6fed' for v in old_colors)
        assert app.wafer_state.net_doping_at(0,-4).net_doping==-1e17
        records['before']={'all_surface_buckets_n':True,'actual_lower_net':-1e17}
        max_error=0.
        for label in ('ACTIVE','CHEMICAL','UNKNOWN','ZERO'):
            app.wafer_state=state(bounds,label,zero=label=='ZERO')
            app.redraw()
            items=app.canvas.find_withtag('canonical_doping_sample')
            assert len(items)==len(tri)
            counts={'n':0,'p':0,'unknown':0,'zero':0}
            x0,xmin,sx,surface,sy=app._viewer_scale
            for item,nodes in zip(items,tri):
                coords=app.canvas.coords(item)
                actual=np.asarray([((coords[i]-x0)/sx+xmin,(surface-coords[i+1])/sy) for i in range(0,6,2)])
                vertices=np.asarray(mesh.points[nodes,:2],dtype=float)
                max_error=max(max_error,float(np.max(np.abs(actual-vertices))))
                x,y=vertices.mean(axis=0)
                # Independent explicit-fixture analytic sign/status at this sample.
                if not (bounds[0]<=x<=bounds[1] and bounds[2]<=y<=bounds[3]): expected='unknown'
                elif label=='ZERO': expected='zero'
                elif y<=-2.5: expected='p' if label=='ACTIVE' else 'unknown'
                else: expected='n'
                colors={'n':'#2f6fed','p':'#e0393e','unknown':G.Tokens.FG_DIM,'zero':G.Tokens.FG_MUTED}
                assert app.canvas.itemcget(item,'fill')==colors[expected]
                counts[expected]+=1
            if label=='ACTIVE': assert counts['n'] and counts['p']
            if label in ('CHEMICAL','UNKNOWN'): assert counts['unknown'] and counts['n'] and counts['p']==0
            if label=='ZERO': assert counts['zero']
            texts=[app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']
            assert '삼각형 중심' in '\n'.join(texts) and '농도 크기' in '\n'.join(texts)
            records[label]={'counts':counts,'items':len(items)}
        assert max_error<=1e-7
        records['vertex_inverse_error_um']=max_error
        app.wafer_state=state(bounds,'UNKNOWN')
        x0,xmin,sx,surface,sy=app._viewer_scale
        app._on_canvas_motion(S(x=x0+(0-xmin)*sx,y=surface-(-4)*sy))
        assert 'UNSUPPORTED' in app.coord_var.get()
        app._on_canvas_motion(S(x=x0+(0-xmin)*sx,y=surface-(-1)*sy))
        assert 'UNSUPPORTED' not in app.coord_var.get()
        records['hover_depth']=True
        app.completed_steps=[{}]; app.flow_step_meshes=[path]; app._viewing_step_index=0
        app.redraw()
        assert not app.canvas.find_withtag('canonical_doping_sample')
        assert '이력 도핑 미보존' in '\n'.join(app.canvas.itemcget(i,'text') for i in app.canvas.find_all())
        records['history_no_current_doping']=True
        app._viewing_step_index=None
        # Valid refined mesh above resource cap; not duplicated/invalid triangles.
        from tcad.device.devsim.mesh_refine import refine_mesh_near
        pts,tris,tags=mesh.points,tri,mesh.cell_data['Material'][block]
        while len(tris)<=G._MAX_RENDERED_TRIANGLES:
            pts,tris,tags=refine_mesh_near(pts,tris,tags,lambda centroid:True,levels=1)
        refined=out/'over_cap.vtu'
        meshio.write(refined,meshio.Mesh(pts,[('triangle',tris)],cell_data={'Material':[tags]}))
        app.last_final_mesh=str(refined); app.redraw()
        assert not app.canvas.find_withtag('canonical_doping_sample')
        assert '도핑 채색 생략' in '\n'.join(app.canvas.itemcget(i,'text') for i in app.canvas.find_all())
        records['resource_cap']={'triangles':len(tris),'no_partial_fill':True}
        assert Path(path).read_bytes()==original
        records['mesh_unchanged']=True
        records['pass']=True
        (out/'depth.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(records,ensure_ascii=False))
    finally:
        app.destroy()

if __name__=='__main__': main()
