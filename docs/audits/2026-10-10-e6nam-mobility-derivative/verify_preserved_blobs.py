"""커밋한 원본이 runner SHA와 같은 바이트인지 전체 대조; 엔진 없음."""
import hashlib
import json
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[3]
BATCHES = [('2026-10-10-e6nai-field-model-scope', 'raw_initial/remote-run-86'),
           ('2026-10-10-e6naj-official-mobility', 'raw/remote-run-87'),
           ('2026-10-10-e6nak-field-color-range', 'raw/remote-run-88'),
           ('2026-10-10-e6nal-mobility-zero-limit', 'raw/remote-run-89'),
           ('2026-10-10-e6nam-mobility-derivative', 'raw/remote-run-90')]


def main():
    rows = []
    for batch, suffix in BATCHES:
        raw = ROOT/'docs/audits'/batch/suffix
        summary = json.loads((raw/'summary.json').read_text(encoding='utf-8'))
        for row in summary['outputs']:
            p = raw/'outputs'/row['path']
            name = p.relative_to(ROOT).as_posix()
            blob = subprocess.check_output(['git', 'show', 'HEAD:'+name], cwd=ROOT)
            assert blob == p.read_bytes(), name
            assert hashlib.sha256(blob).hexdigest() == row['sha256'], name
        for name in ('run.log', 'summary.json'):
            p = raw/name
            blob = subprocess.check_output(['git', 'show', 'HEAD:'+p.relative_to(ROOT).as_posix()], cwd=ROOT)
            assert blob == p.read_bytes()
            if name == 'run.log': assert hashlib.sha256(blob).hexdigest() == summary['log']['sha256']
        rows.append({'batch': batch, 'outputs': len(summary['outputs']), 'git_blob_equals_artifact': True})
    print(json.dumps(rows, indent=2))


if __name__ == '__main__': main()
