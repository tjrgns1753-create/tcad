"""원시 field 배열 무변경, 모델 범위 캡션 계약. 엔진 없이 실행."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tcad.characterization.node_fields import NodeFields, field_caption
from tcad.characterization.interface import BiasPoint, CharacterizationResult, current_unit_metadata
from tcad.characterization.transport_evidence import capture_transport_evidence


def main():
    fields = NodeFields('Si', ((0., 0.), (1., -.5)), (.1, .2), (1e16, 1e16), (1e4, 1e4))
    result = CharacterizationResult('test', 'device', 'Si', 'right',
        [BiasPoint({'left': 0., 'right': .01}, {'left': -.0016, 'right': .0016})], current_unit_metadata(2))
    fake = type('ReadOnly', (), {'get_parameter': lambda self, **kw: 1.})()
    result.metadata['transport_model'] = capture_transport_evidence(fake, 'device', 'Si')
    if '--before' in sys.argv:
        assert '재료 calibration 미검증' not in field_caption(fields, result, 'potential')
        print('REPRODUCED: canvas caption omits material calibration scope')
        return
    for layer in ('potential', 'electron', 'hole'):
        text = field_caption(fields, result, layer)
        assert '고정 이동도' in text and 'Boltzmann' in text and 'SRH' in text
        assert '재료 calibration 미검증' in text
        assert 'actual node samples' in text and 'No interpolation' in text
        assert fields.potential == (.1, .2) and fields.electron == (1e16, 1e16)
    record = result.metadata.pop('transport_model')
    assert '물성 기록 미기록/불완전' in field_caption(fields, result, 'potential')
    result.metadata['transport_model'] = record
    record['parameters']['mu_n']['value'] = float('nan')
    assert '물성 기록 미기록/불완전' in field_caption(fields, result, 'potential')
    record['parameters']['mu_n']['value'] = 1.
    record['parameters']['mu_n']['unit'] = 'wrong'
    assert '물성 기록 미기록/불완전' in field_caption(fields, result, 'potential')
    print('PASS: canvas model scope, missing/NaN/wrong-unit warnings, arrays unchanged')


if __name__ == '__main__':
    main()
