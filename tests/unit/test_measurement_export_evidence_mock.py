"""Export boundary pure tests; no engine/Tk import or physics approval."""
import ast
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_OR_TK_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
source=(ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8')
tree=ast.parse(source)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='run_dc_operating_point')
body=ast.get_source_segment(source,method)
if '--before' in sys.argv:
    assert 'current_unit_metadata' not in body and 'source_evidence' not in body
    print('REPRODUCED: DC GUI wrapper drops unit/source metadata; engine imports 0')
    raise SystemExit(0)
assert 'module.get_dimension(device=imported.device)' in body
from tcad.characterization.interface import BiasPoint,CharacterizationResult,current_unit_metadata
from tcad.characterization.io import save_measurement_bundle
r=CharacterizationResult('synthetic_dc','not_a_device','Si','Drain',
    [BiasPoint({'Source':0.,'Drain':.1,'Gate':1.},{'Source':-1e-6,'Drain':1e-6})],
    {**current_unit_metadata(2),'source_evidence':{'canonical_record':'GUI_SESSION_ONLY'},
     'verification_scope':'INPUT_SOURCE_MATCH_ONLY_NOT_GENERAL_PHYSICS_APPROVAL'})
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'result.csv'
    side=Path(save_measurement_bundle(r,str(path)))
    data=json.loads(side.read_text(encoding='utf-8'))
    assert data['metadata']['export_evidence']['csv_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert data['metadata']['current_unit']=='A/cm'
    assert data['points'][0]['converged'] is True
    assert data['points'][0]['voltages']['Gate']==1.
    rows=list(csv.reader(path.open(newline='')))
    assert rows[0]==['sweep_voltage_V','I_Drain_A_per_cm','I_Source_A_per_cm']
    assert float(rows[1][1])==1e-6 and float(rows[1][2])==-1e-6
    before=(path.read_bytes(),side.read_bytes())
    for bad in (replace(r,points=[BiasPoint({'Drain':.1},{'Drain':float('nan')})]),
                replace(r,points=[BiasPoint({'Drain':.1},{'Drain':1.},False)]),
                replace(r,metadata={'invalid':float('inf')}),replace(r,points=[])):
        try:save_measurement_bundle(bad,str(path))
        except ValueError:pass
        else:raise AssertionError('invalid export accepted')
        assert (path.read_bytes(),side.read_bytes())==before
    assert not list(Path(tmp).glob('*.tmp'))
print('PASS: values/units/source/full bias/hash; invalid evidence leaves existing files unchanged; imports 0')
