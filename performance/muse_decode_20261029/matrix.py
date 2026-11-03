"""Unique configuration points; repetitions never inflate the sweep density."""
SYNTHETIC_C = (1, 2, 4, 8, 16, 32, 64, 128, 256)
CODING_C = (1, 2, 4, 8, 16, 32)


def planned_points(allocation):
    points = {}
    for job in allocation['jobs']:
        precision = job['precision']
        synthetic_cs = tuple(int(c) for c in job['decode_concurrency'].split(',')) if job.get('decode_concurrency') else SYNTHETIC_C
        assert synthetic_cs and all(c > 0 for c in synthetic_cs)
        cases = [('synthetic', str(n), 'off', synthetic_cs) for n in job['input_lengths']]
        if job['mode'] in ('paired_spec', 'long_and_paired_spec'):
            cases += [('coding', label, spec, CODING_C)
                      for label in (tuple('native-'+str(lo)+'-'+str(hi) for lo,hi in job['coding_input_ranges'])
                                    if job.get('coding_input_ranges') else ('native-0-8192', 'native-8192-32768'))
                      for spec in job.get('speculative_algorithms', ('off', 'NGRAM'))]
        for workload, label, spec, cs in cases:
            for c in cs:
                key = precision, workload, label, spec, c
                points[key] = {'precision': precision, 'workload': workload, 'input_label': label,
                    'speculative': spec, 'concurrency': c, 'gpus': 8 if precision == 'nvfp4' else 16,
                    'server_profile': 'baseline_graph256' if workload == 'synthetic' else 'paired_graph32',
                    'required_repeats': 5 if precision == 'nvfp4' and label == '8192' and c in (4, 8) else 3}
    return [points[k] for k in sorted(points)]
