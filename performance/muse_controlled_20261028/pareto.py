#!/usr/bin/env python3
"""Readable serving Pareto figures from accepted, measured request-level statistics."""
import argparse
import csv
from pathlib import Path


COLORS = {'nvfp4': '#2868d8', 'bf16': '#d26823'}
LABELS = {'nvfp4': 'Muse NVFP4 | 8 x H200 | TP8/EP8',
          'bf16': 'Muse BF16 | 16 x H200 | TP16/EP16'}


def curves(ax, rows):
    for precision in ('nvfp4', 'bf16'):
        points = sorted((r for r in rows if r['precision'] == precision), key=lambda r: int(r['concurrency']))
        if not points:
            continue
        x = [float(r['decode_tokens_per_second_p50']) for r in points]
        y = [float(r['tokens_s_gpu']) for r in points]
        ax.errorbar(x, y,
                    xerr=[float(r['decode_p50_repeat_sd']) for r in points],
                    yerr=[float(r['throughput_repeat_sd']) for r in points],
                    color=COLORS[precision], marker='o', linewidth=2.1, markersize=6,
                    capsize=3, label=LABELS[precision])
        for r, a, b in zip(points, x, y):
            limit = float(r['ttft_s_p95']) > 60 or float(r['e2e_s_p95']) > 300
            if limit:
                ax.scatter([a], [b], s=63, facecolors='white', edgecolors=COLORS[precision], zorder=5)
            ax.annotate(r['concurrency'] + ('*' if limit else ''), (a, b),
                        xytext=(5, 7 if precision == 'nvfp4' or b < 8 else -13),
                        textcoords='offset points', fontsize=9, color=COLORS[precision])
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(alpha=.25)
    ax.spines[['top', 'right']].set_visible(False)
    if not rows:
        ax.text(.5, .5, 'No fully accepted points', transform=ax.transAxes, ha='center')


def export(fig, output, name):
    for suffix in ('png', 'pdf', 'svg'):
        fig.savefig(output / (name + '.' + suffix), dpi=190, facecolor='white')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', type=Path, required=True)
    a = p.parse_args()
    output = a.state / 'report'
    with (output / 'detailed_points.csv').open() as f:
        rows = [r for r in csv.DictReader(f) if r['complete'] == 'True' and r['speculative'] == 'off']
    if not rows:
        return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'svg.fonttype': 'none'})
    selected = [r for r in rows if r['workload'] == 'synthetic' and r['input_label'] == '8192' and r['cache'] == 'False']
    with (output / 'decode_pareto_8k.csv').open('w') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(selected)
    fig, ax = plt.subplots(figsize=(11, 7.5))
    curves(ax, selected)
    ax.set_title('Muse Spark: Output Throughput vs. Interactivity', fontsize=19, weight='bold', pad=36)
    ax.text(0, 1.03, '8,192 input / 1,024 output tokens | cache OFF | speculation OFF | FP8 KV',
            transform=ax.transAxes, fontsize=11, color='#555555')
    ax.set_xlabel('Per-request decode speed p50 (output tokens/s/user)')
    ax.set_ylabel('Measured output throughput (output tokens/s/GPU)')
    ax.legend(loc='upper right', fontsize=10)
    fig.text(.5, .065, 'Labels: offered closed-loop concurrency | error bars: repetition SD | 3 repeats; NVFP4 c4/c8: 5', ha='center', fontsize=9)
    fig.text(.5, .039, '* Hollow point: TTFT p95 > 60 s or E2E p95 > 300 s. BF16 c256 omitted: only 1/3 valid repeats.', ha='center', fontsize=9)
    fig.text(.5, .013, 'Serving windows include prefill + decode; BF16 prefill CUDA graphs disabled. Not a matched DeepInfer decode benchmark.', ha='center', fontsize=8.5, color='#555555')
    fig.subplots_adjust(left=.105, right=.98, top=.82, bottom=.17)
    export(fig, output, 'decode_pareto_8k'); plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=True, sharey=True)
    for ax, (tokens, cache) in zip(axes.flat, ((32768, False), (32768, True), (65536, False), (65536, True))):
        selected = [r for r in rows if r['workload'] == 'synthetic' and r['input_label'] == str(tokens) and r['cache'] == str(cache)]
        curves(ax, selected)
        ax.set_title(f'{tokens // 1024}K input | prefix cache {"ON" if cache else "OFF"}')
    long_rows = [r for r in rows if r['workload'] == 'synthetic' and r['input_label'] in ('32768', '65536')]
    if long_rows:
        axes.flat[0].set_ylim(0, max(float(r['tokens_s_gpu']) for r in long_rows) * 1.16)
        axes.flat[0].set_xlim(0, max(float(r['decode_tokens_per_second_p50']) for r in long_rows) * 1.08)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(.5, .925), ncol=2, fontsize=10)
    fig.suptitle('Muse Spark: Long-context Throughput vs. Interactivity', fontsize=18, weight='bold', y=.98)
    fig.supxlabel('Per-request decode speed p50 (output tokens/s/user)', y=.055)
    fig.supylabel('Measured output throughput (output tokens/s/GPU)', x=.025)
    fig.text(.5, .016, '1,024 output tokens | speculation OFF | FP8 KV | labels: concurrency | 3 repeats | error bars: repetition SD\nCache ON: nominal 90% common prefix; measured hit rates in detailed_rounds.csv. * Hollow points exceed latency limits.', ha='center', fontsize=9)
    fig.subplots_adjust(left=.085, right=.98, top=.86, bottom=.12, hspace=.23, wspace=.10)
    export(fig, output, 'decode_pareto_long_context'); plt.close(fig)

    labels = sorted({r['input_label'] for r in rows if r['workload'] == 'coding'})
    fig, axes = plt.subplots(1, max(1, len(labels)), figsize=(6.5 * max(1, len(labels)), 6), squeeze=False, sharey=True)
    for ax, label in zip(axes.flat, labels):
        curves(ax, [r for r in rows if r['workload'] == 'coding' and r['input_label'] == label])
        _, lo, hi = label.split('-')
        ax.set_title(f'Actual input length [{int(lo) // 1024}K, {int(hi) // 1024}K)')
    handles, names = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, names, loc='upper center', bbox_to_anchor=(.5, .90), ncol=2, fontsize=10)
    fig.suptitle('Muse Spark: Coding + Review Serving Curves', fontsize=17, weight='bold', y=.98)
    fig.supxlabel('Per-request decode speed p50 (output tokens/s/user)', y=.075)
    fig.supylabel('Measured output throughput (output tokens/s/GPU)', x=.025)
    fig.text(.5, .016, 'Authentic prompts without padding | 1,024 output tokens | cache OFF | speculation OFF\n3 repeats | error bars: repetition SD | speculative counterparts failed and are not plotted', ha='center', fontsize=9)
    fig.subplots_adjust(left=.08, right=.98, top=.78, bottom=.18, wspace=.12)
    export(fig, output, 'decode_pareto_coding'); plt.close(fig)


if __name__ == '__main__':
    main()
