"""순수 보상/양극성 저항 판정. 실제 기록 없이는 승인하지 않는다."""
import math
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'docs/audits/2026-10-01-batch7h-e6i-uniform-resistor-dd/scripts'))
from resistor_judge import theory, TOL_CURRENT, TOL_CONSERVATION, TOL_N_UNIFORM, TOL_PSI_LINEAR
from tcad.characterization.node_fields import NodeFields, validate_node_fields

PROFILES = {
    'n_single': ((1e16, 0.),), 'p_single': ((0., 1e16),),
    'n_comp_da': ((2e16, 0.), (0., 1e16)),
    'n_comp_ad': ((0., 1e16), (2e16, 0.)),
    'p_comp_ad': ((0., 2e16), (1e16, 0.)),
    'p_comp_da': ((1e16, 0.), (0., 2e16)),
}
CASES = tuple((profile + '_' + sign, profile, voltage)
              for profile in PROFILES for sign, voltage in (('pos', .001), ('neg', -.001)))
EXPECTED_PARAMS = {'ElectronCharge': 1.6e-19, 'n_i': 1e10, 'T': 300., 'mu_n': 400.,
                   'mu_p': 200., 'taun': 1e-8, 'taup': 1e-8}


def require(condition, name):
    if not condition:
        raise ValueError(name)


def evaluate(records, cases=CASES):
    checks, metrics = [], {}
    try:
        require(set(records) == {row[0] for row in cases}, 'CASE_SET')
        for name, profile, voltage in cases:
            r = records[name]
            donor = sum(p[0] for p in PROFILES[profile])
            acceptor = sum(p[1] for p in PROFILES[profile])
            require(r['profile'] == profile and r['voltage'] == voltage, 'REQUEST_IDENTITY')
            require(r['steps'] == [list(s) for s in PROFILES[profile]], 'ACTUAL_DECLARATION_SEQUENCE')
            require(r['solves'] == 3 and r['device_cleanup'] is True and r['live_api_equal'] is True, 'EXECUTION')
            require(r['canonical_query'] == {'donor': donor, 'acceptor': acceptor, 'net': donor-acceptor,
                                            'physics_status': None}, 'CANONICAL_CONCENTRATIONS')
            require(r['attachment_count'] == len(PROFILES[profile]), 'ATTACHMENT_COUNT')
            fields = NodeFields(**r['snapshot'])
            validate_node_fields(fields)
            require(len(fields.xy_um) == 73 and fields.region == 'Si', 'SNAPSHOT_SCOPE')
            require(all(math.isfinite(v) and v > 0 for a in (fields.electron, fields.hole) for v in a), 'POSITIVE_CARRIERS')
            for model, expected in (('Donors', donor), ('Acceptors', acceptor), ('NetDoping', donor-acceptor)):
                require(len(r['doping_arrays'][model]) == 73 and all(v == expected for v in r['doping_arrays'][model]), 'DOPING_' + model)
            params = r['params']
            require(all(params[k] == v for k, v in EXPECTED_PARAMS.items()), 'PARAMETERS')
            result = r['measurement']
            require(result['region'] == 'Si' and result['sweep_contact'] == 'Si_xmax' and len(result['points']) == 1, 'RESULT_IDENTITY')
            point = result['points'][0]
            require(point['converged'] is True and point['voltages'] == {'Si_xmin': 0., 'Si_xmax': voltage}, 'BIAS_POINT')
            require(set(point['currents']) == {'Si_xmin', 'Si_xmax'} and all(math.isfinite(v) for v in point['currents'].values()), 'CURRENT_CONTACTS')
            require(result['metadata']['current_unit'] == 'A/cm' and result['metadata']['device_dimension'] == 2 and
                    result['metadata']['current_normalization'] == 'per_out_of_plane_depth', 'UNITS')
            require(r['export_equal'] is True and r['success_log_present'] is True, 'GUI_EVIDENCE')
            require(set(r['rendered']) == {'potential', 'electron', 'hole'} and all(item['nodes'] == 73 and
                    '영역 Si' in item['text'] and 'No interpolation' in item['text'] for item in r['rendered'].values()), 'NODE_DISPLAY')
            x = [pair[0] for pair in fields.xy_um]
            y = [pair[1] for pair in fields.xy_um]
            require(min(x) == -1. and max(x) == 1. and min(y) == -.5 and max(y) == 0., 'GEOMETRY')
            th = theory(donor, acceptor, params['n_i'], params['ElectronCharge'], params['mu_n'], params['mu_p'], .5e-4, 2e-4)
            g = th['G_A_per_V_per_cm_depth']
            isrc, ignd = point['currents']['Si_xmax'], point['currents']['Si_xmin']
            current_error = max(abs(isrc-g*voltage), abs(ignd+g*voltage)) / abs(g*voltage)
            kcl = abs(isrc+ignd) / (g*.001)
            majority = fields.electron if donor >= acceptor else fields.hole
            majority_ref = th['n0'] if donor >= acceptor else th['p0']
            majority_error = max(abs(v/majority_ref-1.) for v in majority)
            offsets = [p for c, p in zip(x, fields.potential) if c == -1.]
            offset = sum(offsets) / len(offsets)
            phi_error = max(abs(p-(offset+voltage*(c+1.)/2.)) for c,p in zip(x,fields.potential)) / .001
            metrics[name] = {'source_current_A_per_cm': isrc, 'ground_current_A_per_cm': ignd,
                'G_A_per_V_per_cm': g, 'current_error': current_error, 'kcl': kcl,
                'majority_uniformity': majority_error, 'potential_linearity': phi_error,
                'ground_raw_Potential_V': offset, 'n0': th['n0'], 'p0': th['p0']}
            for label, value, limit in (('current',current_error,TOL_CURRENT),('kcl',kcl,TOL_CONSERVATION),
                    ('majority',majority_error,TOL_N_UNIFORM),('potential',phi_error,TOL_PSI_LINEAR)):
                checks.append({'name':name+'_'+label,'value':value,'limit':limit,'pass':math.isfinite(value) and value<=limit})
        for sign in ('pos','neg'):
            ni = metrics['n_single_'+sign]['source_current_A_per_cm']
            pi = metrics['p_single_'+sign]['source_current_A_per_cm']
            ratio = pi/ni
            checks.append({'name':'p_over_n_'+sign,'value':abs(ratio/.5-1),'limit':TOL_CURRENT,
                           'pass':math.isfinite(ratio) and abs(ratio/.5-1)<=TOL_CURRENT})
            for label,a,b in (('n_order','n_comp_da','n_comp_ad'),('p_order','p_comp_ad','p_comp_da')):
                if a+'_'+sign not in records or b+'_'+sign not in records:
                    continue
                ra,rb=records[a+'_'+sign],records[b+'_'+sign]
                ma,mb=metrics[a+'_'+sign],metrics[b+'_'+sign]
                errs=[abs(ma['source_current_A_per_cm']-mb['source_current_A_per_cm'])/abs(ma['G_A_per_V_per_cm']*.001)]
                majority_key='electron' if label.startswith('n') else 'hole'
                ref=ma['n0'] if majority_key=='electron' else ma['p0']
                errs.append(max(abs(u-v)/ref for u,v in zip(ra['snapshot'][majority_key],rb['snapshot'][majority_key])))
                errs.append(max(abs(u-v)/.001 for u,v in zip(ra['snapshot']['potential'],rb['snapshot']['potential'])))
                for key,err,limit in zip(('current','majority','potential'),errs,(TOL_CURRENT,TOL_N_UNIFORM,TOL_PSI_LINEAR)):
                    checks.append({'name':label+'_'+sign+'_'+key,'value':err,'limit':limit,
                                   'pass':math.isfinite(err) and err<=limit})
        return {'pass':all(c['pass'] for c in checks),'checks':checks,'metrics':metrics}
    except (KeyError,IndexError,ValueError,TypeError,ZeroDivisionError,OverflowError) as error:
        return {'pass':False,'error':str(error),'checks':checks,'metrics':metrics}
