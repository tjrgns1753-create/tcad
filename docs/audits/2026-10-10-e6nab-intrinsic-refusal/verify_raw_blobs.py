"""원본 artifact와 현재 git blob의 바이트를 엔진 없이 대조한다."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3]
def main():
    count=0
    for name in ('2026-10-10-e6naa-intrinsic-gui','2026-10-10-e6nab-intrinsic-refusal',
                 '2026-10-10-e6nac-unit-cross-regression'):
        raw=ROOT/'docs/audits'/name/'raw'
        summary=json.loads((raw/'summary.json').read_text(encoding='utf-8'))
        paths=[('outputs/'+r['path'],r['sha256']) for r in summary['outputs']]
        paths.append((summary['log']['file'],summary['log']['sha256']))
        paths.append(('summary.json',hashlib.sha256((raw/'summary.json').read_bytes()).hexdigest()))
        for local,sha in paths:
            rel=str((raw/local).relative_to(ROOT)).replace('\\','/')
            b=subprocess.check_output(['git','-c','safe.directory='+str(ROOT),'show','HEAD:'+rel],cwd=ROOT,
                env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM='1'))
            assert hashlib.sha256(b).hexdigest()==sha,rel
            assert (raw/local).read_bytes()==b,rel
            count+=1
    print(json.dumps({'committed_raw_files':count,'artifact_and_git_blob_identical':True}))
if __name__=='__main__':main()
