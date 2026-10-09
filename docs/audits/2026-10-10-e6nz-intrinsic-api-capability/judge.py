"""무도핑 Si의 사전 고정된 저전계 수치 기준. 엔진 없이 원본을 재판정."""
import math

EXPECTED = {'ElectronCharge': 1.6e-19, 'n_i': 1e10, 'T': 300., 'mu_n': 400., 'mu_p': 200., 'taun': 1e-8, 'taup': 1e-8}
BIASES = {'zero': 0., 'positive': .001, 'negative': -.001}

def judge(data):
    checks = []
    def check(name, ok):
        checks.append({'name': name, 'pass': bool(ok)})
    def bound(name, value, limit):
        check(name, math.isfinite(value) and value <= limit)
    cases = data.get('cases', {})
    check('exact cases', set(cases) == set(BIASES))
    for name, voltage in BIASES.items():
        try:
            r = cases[name]; par = r['params']; a = r['arrays']
            check(name+' metadata', r['voltage'] == voltage and r['solves'] == 3 and r['attachments'] == 0 and r['state_identity'])
            check(name+' parameters', all(par[k] == v for k,v in EXPECTED.items()))
            metadata=r['result_metadata']
            check(name+' units', metadata.get('current_unit')=='A/cm' and metadata.get('current_normalization')=='per_out_of_plane_depth' and metadata.get('device_dimension')==2)
            check(name+' full arrays', set(a) == {'x', 'y', 'Potential', 'Electrons', 'Holes', 'Donors', 'Acceptors', 'NetDoping'} and all(len(v) == 73 for v in a.values()))
            check(name+' finite arrays', all(math.isfinite(v) for values in a.values() for v in values))
            check(name+' known zero doping', all(v == 0 for key in ('Donors','Acceptors','NetDoping') for v in a[key]))
            check(name+' canonical preserved', len(r['canonical_before'])==73 and r['canonical_before']==r['canonical_after'] and all(v==0 for v in r['canonical_before']))
            ni = par['n_i']; g = par['ElectronCharge']*(par['mu_n']+par['mu_p'])*ni*.25
            ref = g*.001
            cur = r['currents']; contacts = r['contacts']
            check(name+' contacts', len(contacts)==2 and len(set(contacts))==2 and set(cur)==set(contacts))
            source, ground = cur[contacts[1]], cur[contacts[0]]
            total = source['electron']+source['hole']
            check(name+' actual result currents', set(r['result_current'])==set(contacts) and all(r['result_current'][c]==cur[c]['electron']+cur[c]['hole'] for c in contacts))
            bound(name+' current', abs(total-g*voltage)/ref, 1e-4 if voltage==0 else 1e-2)
            bound(name+' KCL', abs(total+ground['electron']+ground['hole'])/ref, 1e-6)
            for key in ('Electrons','Holes'):
                bound(name+' '+key+' uniform', max(abs(v/ni-1) for v in a[key]), 1e-4)
            xs = a['x']; potentials = a['Potential']; lo,hi=min(xs),max(xs)
            bound(name+' length', abs((hi-lo)-2e-4)/2e-4, 1e-12)
            p0 = potentials[xs.index(lo)]
            bound(name+' affine Potential', max(abs(p-(p0+voltage*(x-lo)/(hi-lo))) for x,p in zip(xs,potentials))/max(abs(voltage),.001), 1e-2)
            if voltage:
                bound(name+' electron fraction', abs(source['electron']/total-2/3), 1e-6)
                bound(name+' hole fraction', abs(source['hole']/total-1/3), 1e-6)
            check(name+' cleanup', r['devices_after']==[] and r['meshes_after']==[])
        except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError) as exc:
            check(name+' complete usable record: '+type(exc).__name__, False)
    blocked = data.get('blocked', {})
    check('exact blocked cases', set(blocked)=={'missing','unresolved'})
    for name in ('missing','unresolved'):
        r=blocked.get(name,{})
        check(name+' refusal', r.get('refused') is True and r.get('solves')==0 and r.get('writes')==0 and r.get('resolution')=='UNSUPPORTED_BY_MODEL' and r.get('devices_after')==[] and r.get('meshes_after')==[])
    return {'pass': all(r['pass'] for r in checks), 'checks': checks,
            'scope': 'KNOWN_UNDOPED_API_PILOT_NOT_GUI_OR_PN_APPROVAL'}
