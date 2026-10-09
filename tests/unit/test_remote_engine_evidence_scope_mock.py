"""실제 실행기의 정보 조회 분기만 AST 추출한다. 엔진/child 실행 없음."""
import ast
from pathlib import Path
import sys


def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
ROOT=Path(__file__).resolve().parents[2]


def main():
    tree=ast.parse((ROOT/'remote/run_profile.py').read_text(encoding='utf-8'))
    branches=[node for node in ast.walk(tree) if isinstance(node,ast.If) and
              isinstance(node.test,ast.Call) and isinstance(node.test.func,ast.Attribute) and
              node.test.func.attr=='get' and isinstance(node.test.func.value,ast.Name) and
              node.test.func.value.id=='prof' and node.test.args and
              isinstance(node.test.args[0],ast.Constant) and node.test.args[0].value=='engine_info']
    assert len(branches)==1
    code=compile(ast.fix_missing_locations(ast.Module(body=[branches[0]],type_ignores=[])),'actual_runner_branch','exec')
    calls=[]
    def probe():
        calls.append(True)
        return {'version':'synthetic','extended_precision':True,'direct_solver':'synthetic'}
    summary={}
    exec(code,{'prof':{'engine_info':False},'summary':summary,'devsim_info':probe})
    if '--before' in sys.argv:
        assert summary['devsim']=={'status':'NOT_IMPORTED','reason':'engine-free profile'}
        assert not calls
        print('REPRODUCED: child usage unknown but summary calls entire profile engine-free')
        return
    assert summary['devsim']['status']=='NOT_PROBED'
    assert summary['devsim']['scope']=='ISOLATED_VERSION_PROBE'
    assert summary['devsim']['profile_execution_observed'] is False and not calls
    assert 'child' in summary['devsim']['reason'] and 'engine-free profile' not in summary['devsim']['reason']
    for prof in ({'engine_info':True},{}):
        summary={}
        before=len(calls)
        exec(code,{'prof':prof,'summary':summary,'devsim_info':probe})
        assert len(calls)==before+1
        assert summary['devsim']['version']=='synthetic' and summary['devsim']['extended_precision'] is True
        assert summary['devsim']['scope']=='ISOLATED_VERSION_PROBE' and summary['devsim']['profile_execution_observed'] is False
    def failed_probe():
        return {'error':'devsim info unavailable','exit_code':1}
    summary={}
    exec(code,{'prof':{'engine_info':True},'summary':summary,'devsim_info':failed_probe})
    assert summary['devsim']['error']=='devsim info unavailable' and summary['devsim']['exit_code']==1
    assert 'version' not in summary['devsim']  # 실패를 성공한 버전 정보로 대체하지 않는다.
    print('PASS actual branch: disabled/enabled/default/failed probe scopes; engines/solve 0')


if __name__=='__main__':
    main()
