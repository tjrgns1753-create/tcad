"""짧은 실제 Python 프로세스만 사용. 엔진 import/물리 계산 없음."""
from pathlib import Path
import sys
import tempfile
import time
from resource_supervisor import Job, supervise, require_elements, payload_check


def main():
    with tempfile.TemporaryDirectory(prefix='e6na_supervisor_test_') as tmp:
        root = Path(tmp)
        def run(name, code, **kw):
            r = supervise([sys.executable, '-B', '-c', code], tmp, root/(name+'.log'),
                          candidate_s=kw.pop('candidate_s', 10), interval=0.05, **kw)
            print(name, r, flush=True)
            return r
        r=run('normal', 'print("OK")')
        assert r['status']=='COMPLETED' and r['exit_code']==0 and r['cleanup_ok']
        r=run('error', 'raise SystemExit(7)')
        assert r['status']=='FAIL' and r['exit_code']==7 and r['cleanup_ok']
        r=run('timeout', 'import time; time.sleep(20)', candidate_s=0.8)
        assert r['status']=='TIMEOUT' and r['cleanup_ok']
        r=run('tree_timeout', 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time;time.sleep(20)"]); print("spawned",flush=True);time.sleep(20)', candidate_s=1.5)
        assert r['status']=='TIMEOUT' and r['cleanup_ok']
        assert 'spawned' in (root/'tree_timeout.log').read_text()
        r=run('total_deadline', 'raise AssertionError("must not run")', total_deadline=time.monotonic()-1)
        assert r['status']=='TIMEOUT' and 'pid' not in r
        class RefuseAssignment(Job):
            def assign(self, process):
                raise RuntimeError('synthetic assignment failure')
        marker=root/'should_not_exist'
        r=run('assignment', 'from pathlib import Path;Path("should_not_exist").touch()', job_factory=RefuseAssignment)
        assert r['status']=='FAIL' and r['cleanup_ok'] and not marker.exists()
        r=run('memory', 'import time;time.sleep(20)', memory_cap=1)
        assert r['status']=='FAIL' and r['cleanup_ok'] and 'WORKING_SET' in r['reason']
        class BrokenCleanup(Job):
            def stop(self):
                super().stop()
                raise RuntimeError('synthetic cleanup failure')
        r=run('cleanup', 'print("OK")', job_factory=BrokenCleanup)
        assert r['status']=='FAIL' and not r['cleanup_ok']
        calls=[]
        try:
            require_elements(400001, lambda:calls.append(1))
        except ValueError:
            pass
        else:
            raise AssertionError('element cap bypass')
        assert not calls
        payload_check(100,100,0)
        try:
            payload_check(100,121*1024**2,0)
        except ValueError:
            pass
        else:
            raise AssertionError('output cap bypass')
    assert 'devsim' not in sys.modules and 'viennaps' not in sys.modules
    print('RESOURCE_SUPERVISOR_PASS; ENGINE_IMPORTS=0')


if __name__=='__main__':
    main()
