"""공식 simple_physics DD 경로의 실제 parameter 사본. 엔진 import/계수 변경 없음."""
import math
from numbers import Real

PARAMETER_UNITS = {
    'T': 'K', 'mu_n': 'cm^2/(V*s)', 'mu_p': 'cm^2/(V*s)', 'n_i': 'cm^-3',
    'taun': 's', 'taup': 's', 'ElectronCharge': 'C', 'Permittivity': 'F/cm',
    'V_t': 'V', 'n1': 'cm^-3', 'p1': 'cm^-3',
}


class TransportEvidenceError(ValueError):
    """물성 기록 결손. 이미 수행한 Poisson solve가 없었다는 뜻은 아니다."""


def _values(record):
    parameters = record['parameters']
    if set(parameters) != set(PARAMETER_UNITS):
        raise ValueError('TRANSPORT_PARAMETER_SET_MISMATCH')
    for name, unit in PARAMETER_UNITS.items():
        item = parameters[name]
        value = item['value']
        if (item['unit'] != unit or isinstance(value, bool) or not isinstance(value, Real)
                or not math.isfinite(value) or value <= 0):
            raise ValueError('TRANSPORT_PARAMETER_INVALID: ' + name)
    return parameters


def capture_transport_evidence(module, device, region):
    """DD 설정 직후, solve/cleanup 전에 실제 public get_parameter만 읽는다.

    이 함수는 프로젝트의 simple_physics 생성자 전용이다. 임의 사용자가 만든
    이동도 모델이나 MOS 측정을 이 함수의 provenance로 승인하지 않는다.
    """
    parameters = {}
    for name, unit in PARAMETER_UNITS.items():
        try:
            value = module.get_parameter(device=device, region=region, name=name)
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError('not a real scalar')
            value = float(value)
            if not math.isfinite(value) or value <= 0:
                raise ValueError('not finite and positive')
        except Exception as exc:
            raise TransportEvidenceError('TRANSPORT_PARAMETER_EVIDENCE_MISSING_OR_INVALID: ' + name) from exc
        parameters[name] = {'value': value, 'unit': unit}
    return {
        'schema': 1, 'device': device, 'region': region,
        'capture_api': 'devsim.get_parameter', 'capture_stage': 'POST_DD_SETUP_PRE_DD_SOLVE',
        'model': 'DEVSIM_SIMPLE_PHYSICS_CONSTANT_MOBILITY_BOLTZMANN_SRH',
        'source': 'devsim.python_packages.simple_physics',
        'lifetime_source': 'tcad.device.devsim.semiconductor_equation.setup_drift_diffusion_equation',
        'material_calibration': 'NOT_VALIDATED', 'parameters': parameters,
        'limitations': ['NO_DOPING_DEPENDENT_MOBILITY', 'NO_HIGH_FIELD_MOBILITY',
                        'NO_FERMI_DIRAC_STATISTICS', 'NO_PROCESS_CALIBRATED_LIFETIME',
                        'NO_T_DEPENDENT_MOBILITY_OR_INTRINSIC_DENSITY'],
    }


def _record_values(metadata):
    record = metadata['transport_model']
    if (record['schema'] != 1 or record['capture_api'] != 'devsim.get_parameter'
            or record['model'] != 'DEVSIM_SIMPLE_PHYSICS_CONSTANT_MOBILITY_BOLTZMANN_SRH'
            or record['material_calibration'] != 'NOT_VALIDATED'):
        raise ValueError('unknown contract')
    return _values(record)


def transport_model_scope(metadata):
    """좁은 화면 공간의 한계 안내. 값은 긴 note/JSON에 그대로 기록된다."""
    try:
        _record_values(metadata)
    except (KeyError, TypeError, ValueError):
        return '물성 기록 미기록/불완전 — 실제 재료 정확성 미검증.'
    return '고정 이동도 · Boltzmann · SRH 모델 — 재료 calibration 미검증.'


def transport_model_note(metadata):
    """화면/로그는 저장된 값만 사용한다. 기록 결손을 기본 예제값으로 채우지 않는다."""
    try:
        p = _record_values(metadata)
    except (KeyError, TypeError, ValueError):
        return '수송 모델의 실제 물성값 미기록/불완전 — 실제 재료의 정량 검증으로 해석할 수 없습니다.'
    values = '; '.join(f"{k}={p[k]['value']:.6g} {p[k]['unit']}" for k in PARAMETER_UNITS)
    return ('수송 모델: 고정 이동도·Boltzmann 통계·SRH 재결합. 실제 사용값: ' + values + '\n'
            '재료 물성 calibration 미검증: 이동도·수명은 제작 이력에서 계산한 값이 아닙니다. '
            '수렴 성공은 고농도·고전계·임의 온도에서 실제 Si 특성의 정확성을 보장하지 않습니다.')
