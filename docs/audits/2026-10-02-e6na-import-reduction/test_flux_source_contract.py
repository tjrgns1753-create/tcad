"""공식 helper 소스 계약의 엔진 없는 정상/우회 반례."""
import ast
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import run_e6na as R
from flux_source_contract import REVIEWED_FUNCTION_SHA, _canonical, require_reviewed_source


def main():
    reference = (R.HERE/'REVIEWED_FLUX_REFERENCE.txt').read_text(encoding='utf-8')
    # 데이터 reference를 Python spy로만 실행해 검토한 모델/방정식 연결을 독립 확인.
    edges, equations = [], []
    spies = dict(InNodeModelList=lambda *args:True,
                 CreateSolution=Mock(),CreateNodeModel=Mock(),CreateNodeModelDerivative=Mock(),
                 CreateEdgeModel=lambda device,region,name,equation:edges.append((name,equation)),
                 CreateEdgeModelDerivatives=Mock(),equation=lambda **kwargs:equations.append(kwargs))
    exec(compile(reference,'reviewed-reference-only','exec'),spies)
    spies['CreateSiliconPotentialOnly']('fake-device','Si')
    assert edges == [('ElectricField','(Potential@n0-Potential@n1)*EdgeInverseLength'),
                     ('PotentialEdgeFlux','Permittivity * ElectricField')]
    assert len(equations)==1 and equations[0]['edge_model']=='PotentialEdgeFlux'
    assert equations[0]['name']=='PotentialEquation'
    print('REFERENCE_SPY model definitions and equation connection PASS')

    good_doc = reference.replace('    if not InNodeModelList', '    """changed documentation"""\n    if not InNodeModelList',1)
    for label,source in (('normal',reference),('comments','# arbitrary comment\n'+reference),
                         ('docstring',good_doc),('CRLF',reference.replace('\n','\r\n')),
                         ('indentation','\n'.join('    '+s for s in reference.splitlines()))):
        callback=Mock(return_value='OK')
        with patch.object(R.inspect,'getsource',return_value=source):
            assert R.require_flux_source(object(),callback)=='OK'
        callback.assert_called_once()
        assert require_reviewed_source(source)==REVIEWED_FUNCTION_SHA
        print('ACCEPT',label,'callback=1')

    comments='def CreateSiliconPotentialOnly(device, region):\n    # (Potential@n0-Potential@n1)*EdgeInverseLength\n    # Permittivity * ElectricField\n    actual_flux="0"\n'
    doc='def CreateSiliconPotentialOnly(device, region):\n    """(Potential@n0-Potential@n1)*EdgeInverseLength; Permittivity * ElectricField"""\n    actual_flux="0"\n'
    unused='def CreateSiliconPotentialOnly(device, region):\n    unused=("(Potential@n0-Potential@n1)*EdgeInverseLength", "Permittivity * ElectricField")\n    actual_flux="0"\n'
    bad_cases=(('comment_only',comments),('docstring_only',doc),('unused_strings',unused),
               ('electric_field',reference.replace('(Potential@n0-Potential@n1)*EdgeInverseLength','0')),
               ('flux',reference.replace('Permittivity * ElectricField','0')),
               ('equation_edge_model',reference.replace('edge_model="PotentialEdgeFlux"','edge_model="ElectricField"')),
               ('model_creation',reference.replace('CreateEdgeModel(device, region, n, e)','CreateNodeModel(device, region, n, e)')),
               ('unused_correct_function',reference+'\nwrong_flux = "0"\n'),
               ('unsupported_structure','def CreateSiliconPotentialOnly(device,region):\n    return 0\n'),
               ('syntax','def broken('),('nontext',None))
    for label,source in bad_cases:
        callback=Mock()
        with patch.object(R.inspect,'getsource',return_value=source):
            try:R.require_flux_source(object(),callback)
            except ValueError:pass
            else:raise AssertionError('false acceptance: '+label)
        callback.assert_not_called()
        print('BLOCK',label,'callback=0')
    callback=Mock()
    with patch.object(R.inspect,'getsource',side_effect=OSError('unavailable')):
        try:R.require_flux_source(object(),callback)
        except ValueError as exc:assert str(exc)=='OFFICIAL_FLUX_SOURCE_UNAVAILABLE'
        else:raise AssertionError('missing source accepted')
    callback.assert_not_called()
    print('BLOCK unavailable callback=0')
    # Python AST의 빈 type_params 유무는 같고, 비어 있지 않은 경우는 차단.
    node=ast.parse(reference).body[0];baseline=_canonical(node)
    node.type_params=[]
    assert _canonical(node)==baseline
    node.type_params=[ast.Name(id='T',ctx=ast.Load())]
    try:_canonical(node)
    except ValueError:pass
    else:raise AssertionError('unsupported type parameters accepted')
    assert not any(k in sys.modules for k in ('devsim','viennaps'))
    print('FLUX CONTRACT PASS; actual engine imports=0; actual solve=0')


if __name__=='__main__':
    main()
