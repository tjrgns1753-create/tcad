"""공식 Z 식과 연속 확장의 순수 Decimal 산술 비교; 엔진 없음."""
from decimal import Decimal as D, localcontext


def main():
    with localcontext() as context:
        context.prec = 80
        for c, nr in ((D('.21'), D('4e20')), (D('.50'), D('7.2e20'))):
            for dopant in map(D, ('1e10', '1e16', '1e20', '1e22')):
                original = 1+1/(c+(nr/dopant)**2)
                candidate = 1+(dopant/nr)**2/(1+c*(dopant/nr)**2)
                error = abs(candidate-original)/abs(original)
                assert error <= D('1e-70')
                print(f'dopant={dopant} c={c} relative_difference={error}')
            assert 1+(D(0)/nr)**2/(1+c*(D(0)/nr)**2) == D(1)
    print('PASS 8 positive equivalences + 2 exact zero limits; no engine')


if __name__ == '__main__': main()
