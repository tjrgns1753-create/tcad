"""실제 Tk export 배선 + canonical DC mock control. MOSFET 실측 아님."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tests/unit')]
if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted': raise RuntimeError('REMOTE_ONLY')
import tcad_2d_stagewise as G
import test_measurement_entry_point_gate_mock as M

def main():
    app=G.TCADApplication();app.withdraw()
    try:
        point,recorder,fake,log=M._dc_operating_point(app,M._virgin_doped(),[(-1.,-1.),(1.,-.5)])
        assert point is not None and len(recorder.calls)==1
        result=app.last_electrode_result
        assert result.metadata['current_unit']=='A/cm'
        assert result.metadata['device_dimension']==2
        assert result.metadata['source_evidence']['canonical_record']=='GUI_SESSION_ONLY'
        assert result.metadata['source_evidence']['mesh_sha256']==hashlib.sha256(Path(M.__file__).read_bytes()).hexdigest()
        assert 'NOT_GENERAL_PHYSICS_APPROVAL' in result.metadata['verification_scope']
        assert 'A/cm' in log
        with tempfile.TemporaryDirectory() as tmp:
            csv=Path(tmp)/'한국어.csv'
            with patch('tkinter.filedialog.asksaveasfilename',return_value=str(csv)):
                app._on_export_result_clicked()
            companion=Path(str(csv)+'.metadata.json')
            payload=json.loads(companion.read_text(encoding='utf-8'))
            assert payload['metadata']['export_evidence']['csv_sha256']==hashlib.sha256(csv.read_bytes()).hexdigest()
            assert payload['points'][0]['currents']==point.currents
            assert payload['points'][0]['voltages']['Gate']==1.
            assert payload['points'][0]['converged'] is True
            assert all('A_per_cm' in s for s in csv.read_text(encoding='utf-8').splitlines()[0].split(',')[1:])
        out=ROOT/'e6nl_out';out.mkdir(exist_ok=True)
        (out/'export.json').write_text(json.dumps({'pass':True,'current_unit':'A/cm','source_sha_verified':True,
            'csv_sha_verified':True,'full_bias_preserved':True,'gui_mock_dc':'SYNTHETIC_NOT_PHYSICS_EVIDENCE'},indent=2),encoding='utf-8')
        print('PASS: GUI DC unit/source/log + companion hash/full bias; DC result is mock')
    finally:app.destroy()
if __name__=='__main__':main()
