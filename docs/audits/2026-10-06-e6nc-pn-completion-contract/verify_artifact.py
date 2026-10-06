"""원격 결과 해시, 원본 증거, 명시적 미승인 상태의 독립 대조."""
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
EXPECTED_SOURCE = 'a556d65615d8dad62c36323daccadedb0263a3d2'


def semantic_check(summary, report):
    if (summary.get('status') != 'PASS' or type(summary.get('exit_code')) is not int
            or summary['exit_code'] != 0 or summary.get('log_truncated') is not False
            or summary.get('omitted_outputs') != []
            or summary.get('source', {}).get('github_sha') != EXPECTED_SOURCE
            or report.get('source_sha') != EXPECTED_SOURCE):
        raise ValueError('REMOTE_EXECUTION_IDENTITY_OR_COMPLETENESS_FAIL')
    if (report.get('status') != 'PASS' or report.get('pn_approved') is not False
            or report.get('gate_released') is not False or report.get('raw_hashes_unchanged') is not True
            or type(report.get('revalidated_audit_exit_code')) is not int
            or report['revalidated_audit_exit_code'] != 1
            or type(report.get('new_solves')) is not int or report['new_solves'] != 0
            or type(report.get('engine_imports')) is not int or report['engine_imports'] != 0
            or report.get('current_verdicts', {}).get('G2_PRODUCTION_GATE_HELD_AND_AUDIT_DOPING') != 'NOT_EVALUATED'):
        raise ValueError('INCOMPLETE_PN_EVIDENCE_CANNOT_BE_APPROVED')
    expected = {f'L{i}_{d}': 'NOT_RECORDED' if d == 'rev' else 'RECORDED_VALID' for i in range(3) for d in ('fwd', 'rev')}
    if report.get('canonical_evidence') != expected:
        raise ValueError('CANONICAL_EVIDENCE_CHANGED')


def main(path):
    path = Path(path)
    summary = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
    result = path / 'outputs/e6nc_out/result.json'
    report = json.loads(result.read_text(encoding='utf-8'))
    semantic_check(summary, report)
    expected = summary['outputs']
    if len(expected) != 1 or expected[0]['path'] != 'e6nc_out/result.json':
        raise ValueError('UNEXPECTED_OUTPUT_SET')
    for file, record in ((result, expected[0]), (path / 'run.log', summary['log'])):
        if hashlib.sha256(file.read_bytes()).hexdigest() != record['sha256'] or file.stat().st_size != record['bytes']:
            raise ValueError('ARTIFACT_HASH_FAIL')
    portability = {}
    for relative, digest in report['raw_hashes'].items():
        file = ROOT / relative
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() == digest:
            portability[relative] = 'BYTE_IDENTICAL'
        elif (file.suffix in ('.json', '.md') and b'\r' not in data
              and hashlib.sha256(data.replace(b'\n', b'\r\n')).hexdigest() == digest):
            # Exact alternate-checkout bytes are established by the remote hash.
            # This is NOT byte portability; keep the discrepancy visible.
            portability[relative] = 'EXACT_CHECKOUT_CRLF_VARIANT_ONLY'
        else:
            raise ValueError('ORIGINAL_EVIDENCE_HASH_FAIL:' + relative)
    tests = []
    for key, bad in (('pn_approved', True), ('gate_released', True), ('engine_imports', 1),
                     ('new_solves', 1), ('revalidated_audit_exit_code', 0), ('raw_hashes_unchanged', False)):
        mutated = copy.deepcopy(report)
        mutated[key] = bad
        try:
            semantic_check(summary, mutated)
        except ValueError:
            tests.append(key)
        else:
            raise AssertionError('FALSE_GREEN:' + key)
    print(json.dumps(dict(status='PASS', artifact_outputs_verified=1, original_hashes_verified=len(report['raw_hashes']),
                         checkout_portability=portability, negative_controls=tests,
                         source_sha=EXPECTED_SOURCE, engine_imports=0, new_solves=0), indent=2))


if __name__ == '__main__':
    main(sys.argv[1])
