"""엔진 없는 실제 API 반환값 기록/거부 계약. 물성 calibration 시험 아님."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tcad.characterization.transport_evidence import (
    PARAMETER_UNITS, capture_transport_evidence, transport_model_note, TransportEvidenceError)


class Fake:
    def __init__(self):
        self.values = {key: float(i + 1) for i, key in enumerate(PARAMETER_UNITS)}
        self.calls = []

    def get_parameter(self, **kw):
        self.calls.append(kw)
        return self.values[kw['name']]


def main():
    fake = Fake()
    record = capture_transport_evidence(fake, 'actual_device', 'Si')
    assert record['parameters'] == {k: {'value': v, 'unit': PARAMETER_UNITS[k]} for k, v in fake.values.items()}
    assert len(fake.calls) == 11
    assert all(c['device'] == 'actual_device' and c['region'] == 'Si' for c in fake.calls)
    assert record['material_calibration'] == 'NOT_VALIDATED'
    assert '미검증' in transport_model_note({'transport_model': record})
    assert '미기록' in transport_model_note({})
    assert json.loads(json.dumps(record, allow_nan=False)) == record
    for key in PARAMETER_UNITS:
        for bad in (None, float('nan'), float('inf'), 0, -1, True, '400'):
            fake = Fake()
            fake.values[key] = bad
            try:
                capture_transport_evidence(fake, 'd', 'Si')
            except TransportEvidenceError as exc:
                assert key in str(exc)
            else:
                raise AssertionError((key, bad))
        fake = Fake()
        del fake.values[key]
        try:
            capture_transport_evidence(fake, 'd', 'Si')
        except TransportEvidenceError:
            pass
        else:
            raise AssertionError(key)
    assert '미기록' in transport_model_note({'transport_model': {'schema': 1}})
    print('PASS: 11 actual-value records, 88 invalid/missing cases; no engine import')


if __name__ == '__main__':
    main()
