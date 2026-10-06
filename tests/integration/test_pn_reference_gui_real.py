"""실제 Tk 버튼→subprocess→DEVSIM→그림, 공정 wafer 상태 무변경."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
    raise RuntimeError('REMOTE_ONLY_TEST')
import tcad_2d_stagewise as G
from tcad.characterization.pn_reference_view import require_pass

out=Path(sys.argv[1]); out.mkdir(parents=True,exist_ok=True)
modal=[]
with patch.object(G.messagebox,'showinfo',side_effect=lambda *a,**k:modal.append('info')),patch.object(G.messagebox,'showerror',side_effect=lambda *a,**k:modal.append('error')):
    app=G.TCADApplication(); app.withdraw()
    before=(app.wafer_state,app.last_final_mesh,app.last_doped_result,app.wafer.processed,app.process_stage)
    try:
        app.pn_reference_button.invoke()
        assert app._pn_reference_process is not None
        app.pn_reference_button.invoke()  # 중복 실행 금지.
        deadline=time.monotonic()+120
        updates=0
        while app._pn_reference_process is not None and time.monotonic()<deadline:
            app.update(); updates+=1; time.sleep(.01)
        assert app._pn_reference_process is None,'GUI_REFERENCE_TIMEOUT'
        result=app._pn_reference_result
        if result is None:
            if app._pn_reference_output.exists():
                (out/'failed_result.json').write_bytes(app._pn_reference_output.read_bytes())
            raise AssertionError('NO_ACCEPTED_RESULT: '+app.log.get('1.0','end'))
        require_pass(result)
        assert before==(app.wafer_state,app.last_final_mesh,app.last_doped_result,app.wafer.processed,app.process_stage)
        assert updates>1 and not modal
        fig=app._pn_reference_window._pn_canvas.figure
        assert len(fig.axes)==4
        assert [len(ax.lines) for ax in fig.axes]==[2,3,2,3]
        fig.savefig(out/'pn_reference.png')
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        (out/'gui.json').write_text(json.dumps({'updates':updates,'modal_calls':modal,'wafer_unchanged':True,'axes':4,
                                               'solves':sum(d['solves'] for d in result['devices'].values()),
                                               'status':result['status']},ensure_ascii=False),encoding='utf-8')
        with patch.object(G.subprocess,'Popen',side_effect=OSError('SYNTHETIC_LAUNCH_FAILURE')):
            app.run_pn_reference()
            assert not app._pn_reference_window.winfo_exists()
            assert app._pn_reference_result is None
        print('PASS: real GUI benchmark, 17 solves, 4 plots, state unchanged, no modal, failure removes stale graph')
    finally:
        app.destroy()
