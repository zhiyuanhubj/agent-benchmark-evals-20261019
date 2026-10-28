#!/usr/bin/env python3
"""Separate policy/length curves; error bars are sample SD across repetitions."""
import argparse
import csv
import fcntl
import json
import statistics
from collections import defaultdict
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', type=Path, required=True)
    a = p.parse_args()
    lock = (a.state / 'plot.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX)
    acceptance = a.state / 'report/acceptance.json'
    accepted = None
    accepted_rounds = None
    in_progress = True
    if acceptance.exists():
        in_progress = not json.loads(acceptance.read_text())['complete']
        accepted = {(r['precision'], r['workload'], r['input_label'], r['cache'], r['speculative'], r['concurrency'])
                    for r in json.loads(acceptance.read_text())['targets'] if r['status'] == 'complete'}
        with (a.state / 'report/detailed_rounds.csv').open() as f:
            accepted_rounds = {r['artifact'] for r in csv.DictReader(f)
                               if r['valid_full_protocol_round'] == 'True'}
    groups, rows = defaultdict(list), []
    for path in sorted(a.state.glob('*/cache-*/*/c*/summary.json')):
        row = json.loads(path.read_text())
        row['artifact'] = str(path.relative_to(a.state))
        rows.append(row)
        s = row['scenario']
        if row['valid_curve_point'] and (accepted_rounds is None or row['artifact'] in accepted_rounds):
            label = s.get('input_label', str(s['input_tokens']))
            key = (row['precision'], s['workload'], label, s['cache'], s['speculative'], row['concurrency'])
            groups[key].append(row)
    output = a.state / 'report'
    output.mkdir(exist_ok=True)
    with (output / 'all_rounds.csv').open('w') as stream:
        fields = ['precision', 'workload', 'input_tokens', 'cache', 'speculative', 'concurrency', 'repeat',
                  'valid', 'measurement_s', 'window_output_tokens', 'tokens_s_gpu', 'decode_p50',
                  'ttft_p50_s', 'ttft_p95_s', 'tpot_p50_s', 'tpot_p95_s', 'e2e_p50_s', 'e2e_p95_s',
                  'arrival_successes', 'arrival_failures', 'completions_in_window', 'failures_in_window',
                  'arrival_prompt_tokens', 'arrival_output_tokens_including_drain', 'cache_hit_rate_tokens',
                  'spec_accept_length', 'artifact']
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for r in rows:
            s = r['scenario']
            writer.writerow(dict(precision=r['precision'], workload=s['workload'], input_tokens=s['input_tokens'],
                cache=s['cache'], speculative=s['speculative'], concurrency=r['concurrency'], repeat=r['repeat'],
                valid=r['valid_curve_point'], measurement_s=r['measurement_seconds'],
                window_output_tokens=r['output_tokens_received_in_window'], tokens_s_gpu=r['output_tokens_per_second_per_gpu'],
                decode_p50=r['decode_tokens_per_second']['p50'], ttft_p50_s=r['ttft_s']['p50'], ttft_p95_s=r['ttft_s']['p95'],
                tpot_p50_s=r['tpot_s']['p50'], tpot_p95_s=r['tpot_s']['p95'], e2e_p50_s=r['e2e_s']['p50'],
                e2e_p95_s=r['e2e_s']['p95'], arrival_successes=r['successful_arrivals_after_drain'],
                arrival_failures=r['failed_arrivals_after_drain'], completions_in_window=r['completed_in_window'],
                failures_in_window=r['failed_in_window'], arrival_prompt_tokens=r['prompt_tokens_arrival_cohort'],
                arrival_output_tokens_including_drain=r['output_tokens_arrival_cohort_including_drain'],
                cache_hit_rate_tokens=r['cache_hit_rate_tokens'], spec_accept_length=r['spec_accept_length_weighted'], artifact=r['artifact']))
    with (output / 'status.json').open('w') as f:
        json.dump({'rounds': len(rows), 'valid_rounds': sum(r['valid_curve_point'] for r in rows),
                   'complete_points_with_3_repeats': sum(len(v) >= 3 for v in groups.values()),
                   'complete_protocol_points':len(accepted) if accepted is not None else None,
                   'states': {d: json.loads((a.state / d / 'status.json').read_text())
                              for d in ('nvfp4', 'bf16') if (a.state / d / 'status.json').exists()}}, f, indent=2)
    if not rows:
        return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for workload in ('synthetic', 'coding'):
        fig, ax = plt.subplots(figsize=(11, 7))
        lines = defaultdict(list)
        for key, repeats in groups.items():
            precision, kind, label, cache, spec, concurrency = key
            required = 5 if precision == 'nvfp4' and label == '8192' and concurrency in (4, 8) else 3
            if kind != workload or len(repeats) < required or (accepted is not None and key not in accepted):
                continue
            xs = [r['decode_tokens_per_second']['p50'] for r in repeats]
            ys = [r['output_tokens_per_second_per_gpu'] for r in repeats]
            pooled_x = statistics.median(v for r in repeats for v in r['decode_speed_samples'])
            actual_y = sum(r['output_tokens_received_in_window'] for r in repeats) / sum(r['measurement_seconds'] for r in repeats) / repeats[0]['gpus']
            lines[(precision, label, cache, spec)].append((concurrency, pooled_x, actual_y,
                                                         statistics.stdev(xs), statistics.stdev(ys), len(repeats)))
        for key, points in sorted(lines.items()):
            precision, input_label, cache, spec = key
            points.sort(key=lambda row: row[0])
            label = f'{precision} / {int(input_label) // 1024}K' if workload == 'synthetic' else f'{precision} / coding+review / {input_label}'
            label += f' / cache {"on" if cache else "off"} / spec {spec}'
            ax.errorbar([r[1] for r in points], [r[2] for r in points], xerr=[r[3] for r in points],
                        yerr=[r[4] for r in points], marker='o', capsize=3, label=label)
            for c, x, y, *_ in points:
                ax.annotate(f'c={c}', (x, y), xytext=(4, 4), textcoords='offset points', fontsize=7)
        ax.set_xlabel('Per-request decode speed p50 (output tokens/s); pooled request median')
        ax.set_ylabel('Actual output tokens received / measurement seconds / GPU')
        ax.set_title(('IN PROGRESS — ' if in_progress else '') + 'Controlled Muse serving: ' + workload + '\nError bars: sample SD across repetitions')
        ax.grid(alpha=.25)
        if lines:
            ax.legend(fontsize=7)
        else:
            ax.text(.5, .5, 'No points with >=3 valid repetitions yet', ha='center', transform=ax.transAxes)
        fig.tight_layout()
        fig.savefig(output / (workload + '.png'), dpi=180)
        fig.savefig(output / (workload + '.pdf'))
        plt.close(fig)


if __name__ == '__main__':
    main()
