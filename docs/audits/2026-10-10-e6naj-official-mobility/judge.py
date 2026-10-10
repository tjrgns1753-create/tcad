"""증거 누락은 capability failure와 구분하여 차단한다. 엔진 없음."""
import math

EXPECTED = {'PURE_N': (1e16, 0., 1e16, 1e4), 'PURE_P': (0., 5e15, 2e4, 5e15),
            'INTRINSIC': (0., 0., 1e10, 1e10)}
n = (9e15+math.sqrt((9e15)**2+4e20))/2
EXPECTED['BOTH_POSITIVE_CONTROL'] = (1e16, 1e15, n, 1e20/n)
MODELS = {'Z_D', 'Z_A', 'mu_bulk_e_Node', 'mu_bulk_h_Node', 'mu_bulk_e', 'mu_bulk_h'}


def judge(rows, plan_sha):
    assert set(rows) == set(EXPECTED)
    hashes = set()
    for label, values in EXPECTED.items():
        row = rows[label]
        assert row['case'] == label and row['scope'] == 'SYNTHETIC_MODEL_INPUT_ONLY'
        assert row['plan_sha'] == plan_sha and row['devsim_version'] == '2.11.0'
        assert row['helper'] == 'devsim.python_packages.Klaassen'
        assert len(row['helper_source_sha256']) == len(row['helper_source_lf_sha256']) == 64
        hashes.add(row['helper_source_lf_sha256'])
        assert row['cleanup_devices'] == [] and row['solve_attempts'] == 0
        assert row['temperature_K'] == 300.
        assert set(row['inputs']) == {'Donors', 'Acceptors', 'Electrons', 'Holes'}
        for name, value in zip(('Donors', 'Acceptors', 'Electrons', 'Holes'), values):
            assert row['inputs'][name] == [value]*4
        assert row['coefficient_species_comments'] == ['As donor', 'B acceptor']
        assert row['parameters'] == {'mu_min_e': 52.2, 'mu_max_e': 1417.,
            'mu_min_h': 44.9, 'mu_max_h': 470.5, 'Nref_D': 4e20, 'Nref_A': 7.2e20}
        assert set(row['models']) == MODELS
        assert row['creation'] in {'COMPLETE', 'FAILED'}
        valid = row['creation'] == 'COMPLETE'
        if row['creation'] == 'FAILED': assert row['creation_error']
        for name, model in row['models'].items():
            if model['status'] == 'FINITE_POSITIVE':
                assert len(model['values']) == (4 if name.endswith('_Node') or name in {'Z_D', 'Z_A'} else 5)
                assert all(not isinstance(v, bool) and math.isfinite(v) and v > 0 for v in model['values'])
            else:
                assert model['status'] == 'EVALUATION_FAILED' and model['error']
                valid = False
        assert row['status'] == ('NUMERIC_EVALUABLE' if valid else 'CAPABILITY_UNAVAILABLE')
        if valid:
            for carrier in ('e', 'h'):
                node = row['models']['mu_bulk_'+carrier+'_Node']['values']
                edge = row['models']['mu_bulk_'+carrier]['values']
                assert max(node)-min(node) <= 16*math.ulp(node[0])
                assert all(abs(v-node[0]) <= 16*math.ulp(node[0]) for v in edge)
    assert len(hashes) == 1
    assert rows['BOTH_POSITIVE_CONTROL']['status'] == 'NUMERIC_EVALUABLE'
    return {label: row['status'] for label, row in rows.items()}
