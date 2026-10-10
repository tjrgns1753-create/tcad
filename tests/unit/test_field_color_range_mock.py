"""색 자동 확대의 수치 범위를 숨기지 않는다. 엔진 없이 실제 캡션 검사."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def forbid(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals', 'tkinter'}:
        raise RuntimeError('ENGINE_FORBIDDEN')


sys.addaudithook(forbid)
from tcad.characterization.node_fields import NodeFields, field_caption, field_samples
from tcad.characterization.interface import BiasPoint, CharacterizationResult, current_unit_metadata


def main():
    result = CharacterizationResult('synthetic', 'deleted', 'Si', 'right',
        [BiasPoint({'left': 0., 'right': .01}, {'left': -1., 'right': 1.})], current_unit_metadata(2))
    fields = NodeFields('Si', ((0., 0.), (1., 0.)), (-.2, .3), (1e16, 1e16+2), (0., 0.))
    samples, lo, hi = field_samples(fields, 'electron')
    assert samples[0][3] != samples[1][3] and lo == 1e16 and hi == 1e16+2
    note = field_caption(fields, result, 'electron')
    if '--before' in sys.argv:
        assert note.count('1.0000e+16') == 2 and '자동 색 확대' not in note
        print('REPRODUCED: full color contrast but rounded caption limits identical')
        return
    assert '10000000000000000' in note and '10000000000000002' in note
    assert 'Δ=2 cm^-3' in note and '상대 범위=' in note
    assert '자동 색 확대; 물리적 유의성 보장 아님' in note
    assert field_samples(fields, 'electron')[0] == samples and fields.electron == (1e16, 1e16+2)
    zero = field_caption(fields, result, 'hole')
    assert 'Δ=0 cm^-3' in zero and '상대 범위=0' in zero
    assert len({r[3] for r in field_samples(fields, 'hole')[0]}) == 1
    potential = field_caption(fields, result, 'potential')
    assert 'Δ=0.5 V' in potential and '상대 범위는 전위 기준 의존' in potential
    uniform = NodeFields('Si', fields.xy_um, (0., 0.), (1e16, 1e16), (1e4, 1e4))
    assert 'Δ=0 cm^-3' in field_caption(uniform, result, 'electron')
    print('PASS exact endpoints/span/relative/zero/reference; arrays and colors unchanged; engine imports zero')


if __name__ == '__main__': main()
