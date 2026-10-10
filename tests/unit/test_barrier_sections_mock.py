"""Exact synthetic exported geometry; no process/device engine or Tk."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
def forbid(event,args):
    if event=="import" and args[0].split(".")[0] in {"devsim","viennaps","viennals"}:
        raise RuntimeError("ENGINE_IMPORT_FORBIDDEN")
sys.addaudithook(forbid)
import numpy as np
from tcad.mesh.barrier_sections import covered_sections


def stack(xs, bottom=0.0, roof=lambda x:0.3):
    points=[]; triangles=[]; tags=[]
    for i,x in enumerate(xs):
        points.extend([[x,-1],[x,0],[x,bottom],[x,roof(x)]])
    for i in range(len(xs)-1):
        for a,b,tag in ((0,1,10),(2,3,30)):
            k=4*i
            triangles.extend([[k+a,k+4+a,k+b],[k+4+a,k+4+b,k+b]])
            tags.extend([tag,tag])
    return np.array(points),np.array(triangles),np.array(tags)


def main():
    p,t,g=stack(np.linspace(-5,5,101,dtype=np.float32))
    assert covered_sections(p,t,g,10,30,min_thickness=.01)==[{"min_um":-5.,"max_um":5.}]
    # Same serialized geometry, shuffled IDs and triangle order.
    rng=np.random.default_rng(27); order=rng.permutation(len(p)); inv=np.argsort(order)
    assert covered_sections(p[order],inv[t[::-1]],g[::-1],10,30,min_thickness=.01)==[{"min_um":-5.,"max_um":5.}]
    assert covered_sections(p[:,::-1],t,g,10,30,axis="y",min_thickness=.01)==[{"min_um":-5.,"max_um":5.}]
    # Keep actual gap in oxide, not an invented filled mask.
    keep=np.array([tag==10 or max(p[tri,0])<=-1 or min(p[tri,0])>=1 for tri,tag in zip(t,g)])
    assert covered_sections(p,t[keep],g[keep],10,30,min_thickness=.01)==[
        {"min_um":-5.,"max_um":-1.},{"min_um":1.,"max_um":5.}]
    p,t,g=stack([0.,1.],bottom=.05)
    assert covered_sections(p,t,g,10,30,min_thickness=.01)==[]
    p,t,g=stack([0.,1.],roof=lambda x:.1+.2*x)
    windows=covered_sections(p,t,g,10,30,min_thickness=.2)
    assert len(windows)==1 and abs(windows[0]["min_um"]-.5)<1e-15 and windows[0]["max_um"]==1
    for kw in ({"axis":"z"},{"min_thickness":float("nan")},{"min_thickness":-.1}):
        try: covered_sections(p,t,g,10,30,**kw)
        except ValueError: pass
        else: raise AssertionError("invalid request accepted")
    for q,u in ((np.full_like(p,np.nan),t),(p,np.concatenate([t,t[:1],t[:1]]))):
        try: covered_sections(q,u,np.concatenate([g,g[:1],g[:1]]) if len(u)>len(t) else g,10,30)
        except ValueError: pass
        else: raise AssertionError("invalid geometry accepted")
    assert not any(name in sys.modules for name in ("viennaps","devsim","viennals"))
    print("PASS continuous/gap/float32/permutation/axis/wedge/invalid; engine imports 0")


if __name__=="__main__": main()
