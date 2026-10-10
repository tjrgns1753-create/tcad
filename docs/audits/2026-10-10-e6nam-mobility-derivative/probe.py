"""공개 API의 node carrier derivative 대조; 실제 DD solve 없음."""
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PLAN_SHA = '461e774f1022a9b29b542ed579af34aad60603b1a4df1a33fad3669942b322e9'
from judge import classify, judge


def main():
    assert os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'REMOTE_ONLY'
    assert hashlib.sha256((HERE/'PLAN.md').read_bytes().replace(b'\r\n', b'\n')).hexdigest() == PLAN_SHA
    import devsim as dv
    from devsim.python_packages import Klaassen as helper
    original_dir = ROOT/'docs/audits/2026-10-10-e6nal-mobility-zero-limit/raw/remote-run-89/outputs/e6nal_out'
    source = Path(helper.__file__).read_bytes()
    source_sha = hashlib.sha256(source.replace(b'\r\n', b'\n')).hexdigest()
    attempts = []
    saved_solve = dv.solve
    def no_solve(*args, **kwargs):
        attempts.append('solve')
        raise AssertionError('SOLVE_FORBIDDEN')
    dv.solve = no_solve
    result = {'plan_sha': PLAN_SHA, 'scope': 'AUDIT_ONLY_DERIVATIVE_EVALUATION',
              'helper_source_lf_sha256': source_sha, 'rows': [], 'inputs_restored': True}
    device, region = 'mobility_derivative', 'Si'
    try:
        for label in ('PURE_N', 'PURE_P', 'INTRINSIC', 'BOTH_POSITIVE_CONTROL'):
            baseline = json.loads((original_dir/(label+'.json')).read_text(encoding='utf-8'))
            assert source_sha == baseline['helper_source_lf_sha256']
            mesh = 'mobility_'+label
            dv.create_gmsh_mesh(mesh=mesh, coordinates=[0.,0.,0.,1e-4,0.,0.,1e-4,1e-4,0.,0.,1e-4,0.],
                                elements=[2,0,0,1,2,2,0,0,2,3], physical_names=['Si'])
            dv.add_gmsh_region(mesh=mesh, gmsh_name='Si', region=region, material='Silicon')
            dv.finalize_mesh(mesh=mesh)
            dv.create_device(mesh=mesh, device=device)
            dv.set_parameter(device=device, region=region, name='T', value=300.)
            for name, values in baseline['inputs'].items():
                if name in {'Electrons', 'Holes'}:
                    dv.node_solution(device=device, region=region, name=name)
                    dv.set_node_values(device=device, region=region, name=name, values=values)
                else:
                    dv.node_model(device=device, region=region, name=name, equation=repr(values[0]))
            helper.Set_Mobility_Parameters(device, region)
            helper.Klaassen_Mobility(device, region)
            dv.node_model(device=device, region=region, name='Z_D', equation='1+(Donors/Nref_D)^2/(1+c_D*(Donors/Nref_D)^2)')
            dv.node_model(device=device, region=region, name='Z_A', equation='1+(Acceptors/Nref_A)^2/(1+c_A*(Acceptors/Nref_A)^2)')
            for model in ('mu_bulk_e_Node', 'mu_bulk_h_Node'):
                original = list(dv.get_node_model_values(device=device, region=region, name=model))
                assert original == baseline['models'][model]['values']
                for carrier in ('Electrons', 'Holes'):
                    analytic = list(dv.get_node_model_values(device=device, region=region, name=model+':'+carrier))
                    assert len(analytic) == 4
                    values = baseline['inputs'][carrier]
                    for node in range(4):
                        row = {'case': label, 'model': model, 'carrier': carrier, 'node': node,
                               'carrier_value': values[node], 'base_mobility': original[node],
                               'analytic': analytic[node], 'samples': []}
                        for factor in (1e-3, 5e-4, 2.5e-4):
                            step = values[node]*factor
                            samples = []
                            for sign in (1., -1.):
                                changed = list(values)
                                changed[node] += sign*step
                                dv.set_node_values(device=device, region=region, name=carrier, values=changed)
                                actual = list(dv.get_node_model_values(device=device, region=region, name=model))
                                assert all(v == original[i] for i,v in enumerate(actual) if i != node)
                                samples.append(actual[node])
                            row['samples'].append({'step': step, 'plus': samples[0], 'minus': samples[1]})
                        dv.set_node_values(device=device, region=region, name=carrier, values=values)
                        assert list(dv.get_node_model_values(device=device, region=region, name=model)) == original
                        row['comparison'] = classify(row)
                        result['rows'].append(row)
            for name, values in baseline['inputs'].items():
                assert list(dv.get_node_model_values(device=device, region=region, name=name)) == values
            dv.delete_device(device=device)
    finally:
        dv.solve = saved_solve
        if device in dv.get_device_list(): dv.delete_device(device=device)
        result['cleanup_devices'] = list(dv.get_device_list())
        result['solve_attempts'] = len(attempts)
        result['engine_source_unchanged'] = Path(helper.__file__).read_bytes() == source
        out = ROOT/'e6nam_out'
        out.mkdir(exist_ok=True)
        (out/'metrics.json').write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
    counts = judge(result, PLAN_SHA)
    verdict = {'evidence_complete': True, 'counts': counts, 'scope': 'AUDIT_ONLY_NO_DD_OR_CALIBRATION',
               'mismatch_found': counts.get('NUMERICAL_DERIVATIVE_MISMATCH', 0) > 0}
    (out/'verdict.json').write_text(json.dumps(verdict, indent=2), encoding='utf-8')
    print(json.dumps(verdict))


if __name__ == '__main__': main()
