"""PN 기준 문제 표시. 실패한 수치를 정상 그래프로 표시하지 않는다."""
from . import pn_reference as P


def require_pass(result):
    if (result.get('schema')!=1 or result.get('status')!='REFERENCE_MODEL_CHECKS_PASS'
            or result.get('scope')!=P.SCOPE or result.get('current_unit')!='A/cm^2'
            or result.get('production_2d_gate_released') is not False or result.get('problems')!=[]):
        raise ValueError('PN_REFERENCE_DISPLAY_BLOCKED')
    baseline,arrays=P.reference()
    checks=P.validate(result['devices'],baseline,arrays)
    if not checks or not all(c['pass'] is True for c in checks) or checks!=result.get('checks'):
        raise ValueError('PN_REFERENCE_DISPLAY_CHECKS_FAILED')
    return checks


def figure_for_result(result):
    require_pass(result)
    from matplotlib.figure import Figure
    import numpy as np
    fig=Figure(figsize=(10,7),dpi=100,constrained_layout=True)
    iv,psi,carriers,field=fig.subplots(2,2).flat
    for d,label in [('fwd','순방향'),('rev','역방향')]:
        rows=result['devices'][d]['currents']
        iv.semilogy([r['V'] for r in rows],[abs(r['left']) for r in rows],'o-',label=label)
    iv.set(xlabel='인가 전압 (V)',ylabel='|전류 밀도| (A/cm²)',title='고정 1D PN — 제작 웨이퍼 결과 아님')
    iv.legend()
    for d,v in [('rev',-1.),('fwd',0.),('fwd',.6)]:
        r=result['devices'][d]; s=r['profiles'][str(v)]
        x=np.array(r['x_cm'])*1e4; order=np.argsort(x)
        psi.plot(x[order],np.array(s['Potential'])[order],label=f'{v:+g} V')
        e=(np.array(r['x@n0'])+np.array(r['x@n1']))*.5e4
        eo=np.argsort(e)
        field.plot(e[eo],np.array(s['ElectricField'])[eo],label=f'{v:+g} V')
    r=result['devices']['fwd']; s=r['profiles']['0.0']
    x=np.array(r['x_cm'])*1e4; order=np.argsort(x)
    for nm,label in [('Electrons','전자'),('Holes','정공')]:
        carriers.semilogy(x[order],np.array(s[nm])[order],label=label)
    psi.set(xlabel='x (µm)',ylabel='정전위 (V)',xlim=(-.5,.5))
    field.set(xlabel='x (µm)',ylabel='전계 (V/cm)',xlim=(-.5,.5))
    carriers.set(xlabel='x (µm)',ylabel='캐리어 농도 (cm⁻³)',xlim=(-.5,.5),title='평형 캐리어 분포')
    for ax in (psi,carriers,field):
        ax.legend()
    from matplotlib import font_manager
    from matplotlib.text import Text
    available={f.name for f in font_manager.fontManager.ttflist}
    font=next((f for f in ('Malgun Gothic','NanumGothic','Noto Sans CJK KR') if f in available),None)
    if font:
        for text in fig.findobj(Text):
            # Korean labels and mathematical minus signs need different glyph sets.
            text.set_fontfamily([font, 'DejaVu Sans'])
            text.set_math_fontfamily('dejavusans')
    return fig


def show_result(app,result):
    import tkinter as tk
    from tkinter import ttk
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    checks=require_pass(result)
    window=tk.Toplevel(app)
    window.title('PN 기준 다이오드 — 문헌 모델 및 수치 기준 검사')
    ttk.Label(window,text='고정 1D Si PN | NA=ND=1e17 cm⁻³ | 300 K | ACTIVE 분석 입력\n'
              '문헌 모델/수치 기준 검사 통과 — 현재 웨이퍼·제작 공정·실험 검증 결과가 아닙니다.',
              foreground='#176b35').pack(anchor='w',padx=10,pady=8)
    tabs=ttk.Notebook(window); tabs.pack(fill='both',expand=True)
    plots=ttk.Frame(tabs); details=ttk.Frame(tabs)
    tabs.add(plots,text='실제 DEVSIM 결과'); tabs.add(details,text='물리 검사 / 범위 / 문헌')
    canvas=FigureCanvasTkAgg(figure_for_result(result),master=plots)
    canvas.draw(); canvas.get_tk_widget().pack(fill='both',expand=True)
    toolbar=NavigationToolbar2Tk(canvas,plots); toolbar.update()
    window._pn_canvas=canvas
    text=tk.Text(details,width=100,height=28,wrap='word')
    text.pack(fill='both',expand=True)
    text.insert('end',P.SCOPE+'\n\n'+
                'Poisson + drift-diffusion + SG 전류 + SRH 모델의 고정 기준 문제입니다.\n'
                '활성화, 산화 재분포, 실제 제작 도핑 및 avalanche breakdown은 검증 범위가 아닙니다.\n'
                '이상 Shockley 전류식을 SRH 포함 전류의 정확한 등식으로 주장하지 않습니다.\n'
                '일반 2D PN gate는 그대로 유지됩니다.\n\n'+
                '\n'.join('통과: '+c['name']+((' | '+str(c['value'])) if c['value'] is not None else '') for c in checks)+
                '\n\n문헌 / 공식 구현:\n'+'\n'.join(P.SOURCES))
    text.configure(state='disabled')
    return window
