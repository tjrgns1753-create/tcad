"""승인 전 자원 정책 합성 검증. 실제 프로세스/메모리/엔진 실행 없음."""
import sys
from unittest.mock import Mock
from resource_policy_prototype import decision, payload_budget, supervise_snapshot


def main():
    base=dict(elapsed_candidate=1,elapsed_total=1,working_set=100,metric_ok=True)
    for update,expected in (({},'CONTINUE'),({'elapsed_candidate':600},'TIMEOUT'),
                            ({'elapsed_total':1800},'TIMEOUT'),({'working_set':6*1024**3+1},'MEMORY_LIMIT'),
                            ({'metric_ok':False},'MONITOR_UNAVAILABLE'),
                            ({'working_set':float('nan')},'MONITOR_UNAVAILABLE')):
        snap=dict(base,**update);stop=Mock();finalize=Mock()
        assert supervise_snapshot(snap,stop,finalize)==expected
        if expected=='CONTINUE':
            stop.assert_not_called();finalize.assert_not_called()
        else:
            stop.assert_called_once();finalize.assert_called_once_with(expected)
        print('POLICY',expected)
    stop=Mock(side_effect=RuntimeError('stop failed'));finalize=Mock()
    assert supervise_snapshot(dict(base,elapsed_candidate=600),stop,finalize)=='PROCESS_TREE_STOP_FAILED'
    finalize.assert_called_once_with('PROCESS_TREE_STOP_FAILED')
    assert payload_budget({'arrays.npz':119*1024**2,'witness.json':82*1024**2})=='OUTPUT_LIMIT'
    assert payload_budget({'witness.json':121*1024**2})=='OUTPUT_LIMIT'
    assert payload_budget({'arrays.npz':1,'witness.json':1})=='WITHIN_BUDGET'
    assert not any(k in sys.modules for k in ('devsim','viennaps'))
    print('RESOURCE PROPOSAL TEST PASS; operational watchdog NOT_IMPLEMENTED')


if __name__=='__main__':
    main()
