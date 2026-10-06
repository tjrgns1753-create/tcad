"""검토된 공식 helper AST 하나만 허용하는 엔진 없는 소스 계약.

공백/주석/함수 docstring만 무시한다. transitive helper나 native 엔진의
동일성 증명이 아니다. 예상값은 검사 대상에서 런타임에 만들지 않는다.
"""
import ast
import hashlib
import json
import textwrap

# 로컬 설치 simple_physics.CreateSiliconPotentialOnly를 파일로 읽고 검토해 고정.
# 대응 식/호출 경로는 REVIEWED_FLUX_REFERENCE.txt에 보존한다.
REVIEWED_FUNCTION_SHA = 'fd33b1c5c4a5f199916c550c138df3da8fce46a8ad8a8c8a87548b73a205611e'


def _canonical(node):
    if isinstance(node, ast.AST):
        # Python 3.11에서는 동적으로 붙인 type_params가 iter_fields에 안 나온다.
        # 구버전에서도 비어 있지 않은 속성은 계약상 반드시 차단한다.
        if getattr(node, 'type_params', None):
            raise ValueError('OFFICIAL_FLUX_SOURCE_UNSUPPORTED: type parameters')
        fields = []
        for key, value in ast.iter_fields(node):
            if key == 'type_params':
                if value:
                    raise ValueError('OFFICIAL_FLUX_SOURCE_UNSUPPORTED: type parameters')
                continue  # Python 3.11/3.12+의 빈 필드 차이만 제거.
            fields.append([key, _canonical(value)])
        return [type(node).__name__, fields]
    if isinstance(node, list):
        return [_canonical(value) for value in node]
    return node


def require_reviewed_source(source):
    try:
        if not isinstance(source, str):
            raise ValueError('source is not text')
        tree = ast.parse(textwrap.dedent(source))
    except (SyntaxError, ValueError, TypeError) as exc:
        raise ValueError('OFFICIAL_FLUX_SOURCE_UNPARSABLE') from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError('OFFICIAL_FLUX_SOURCE_UNSUPPORTED: single function required')
    function = tree.body[0]
    if function.name != 'CreateSiliconPotentialOnly':
        raise ValueError('OFFICIAL_FLUX_SOURCE_UNSUPPORTED: function name')
    first = function.body[0] if function.body else None
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        function.body = function.body[1:]
    serialized = json.dumps(_canonical(function), separators=(',', ':'), ensure_ascii=True)
    digest = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
    if digest != REVIEWED_FUNCTION_SHA:
        raise ValueError('OFFICIAL_FLUX_SOURCE_MISMATCH: reviewed AST differs')
    return digest
