#!/usr/bin/env python3
"""Detailed request/GPU/KV statistics and an explicit full-protocol acceptance matrix."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import statistics
import time
import zlib
from collections import defaultdict
from pathlib import Path

from bench import distribution, save
from node import IMAGE

READ_ERRORS = {}


def records(path):
    if not path.exists():
        return
    try:
        with gzip.open(path, 'rt') as f:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    break
    except (EOFError, OSError, zlib.error) as exc:
        # GPU gzip is still open; only already-flushed complete records are used.
        if not isinstance(exc, EOFError):
            READ_ERRORS[str(path)] = type(exc).__name__
        return


def dist(values):
    values = [v for v in values if v is not None and math.isfinite(v)]
    return {**distribution(values), 'mean': statistics.mean(values) if values else None,
            'min': min(values) if values else None, 'max': max(values) if values else None}


GAUGES = {'sglang:token_usage', 'sglang:full_token_usage', 'sglang:swa_token_usage',
          'sglang:kv_cache_memory_usage_gb', 'sglang:num_running_reqs', 'sglang:num_queue_reqs',
          'sglang:cache_hit_rate', 'sglang:spec_accept_length', 'sglang:spec_accept_rate'}


def analyze(root, path, gpu_frames):
    summary = json.loads(path.read_text())
    raw = path.parent / 'requests.jsonl.gz'
    stamp = (raw.stat().st_size, raw.stat().st_mtime_ns)
    key = hashlib.sha256(('analysis_v5' + str(path.relative_to(root)) + path.read_text() + str(stamp)).encode()).hexdigest()
    cache = root / 'report/analysis-cache' / (key + '.json')
    if cache.exists():
        return json.loads(cache.read_text())
    start, end = summary['measurement_start_monotonic'], summary['measurement_end_monotonic']
    cohort, failed = [], []
    for r in records(raw):
        if r['valid'] and start <= r['started'] < end:
            cohort.append({k: r.get(k) for k in ('ttft_s', 'tpot_s', 'e2e_s', 'decode_tokens_per_second')} |
                          {'prompt_tokens': r['meta']['prompt_tokens'], 'output_tokens': r['meta']['completion_tokens']})
        elif start <= r['started'] < end:
            failed.append({'e2e_s':r.get('e2e_s'),'ttft_s':r.get('ttft_s'),
                           'client_input_tokens':r.get('input_tokens_expected',0),
                           'native_prompt_tokens':r.get('meta',{}).get('prompt_tokens'),
                           'native_output_tokens':r.get('meta',{}).get('completion_tokens')})
    begin, finish = summary['measurement_start_unix'], summary['measurement_end_unix']
    gpu_values = defaultdict(list)
    uuids, frames = set(), 0
    valid_by_gpu = defaultdict(int)
    for f in gpu_frames:
        if not begin <= f['unix'] < finish:
            continue
        frames += 1
        for values in f.get('rows', []):
            row = dict(zip(f['fields'], values))
            if row.get('uuid'):
                uuids.add(row['uuid'])
                try:
                    if all(math.isfinite(float(row[k])) for k in ('utilization.gpu','memory.used')):
                        valid_by_gpu[row['uuid']] += 1
                except (ValueError,KeyError):
                    pass
            for field in ('utilization.gpu', 'memory.used', 'memory.total', 'power.draw', 'clocks.sm'):
                try:
                    gpu_values[field].append(float(row[field]))
                except (ValueError, KeyError):
                    pass
    gauges = defaultdict(list)
    for f in records(path.parent / 'backend.jsonl.gz'):
        if not begin <= f['utc_unix'] < finish:
            continue
        response = f.get('/metrics', {})
        if response.get('http') != 200:
            continue
        for line in response['body'].splitlines():
            if not line or line.startswith('#'):
                continue
            metric = line.split('{', 1)[0].split(' ', 1)[0]
            if metric in GAUGES:
                try:
                    gauges[metric].append(float(line.rsplit(' ', 1)[1]))
                except ValueError:
                    pass
    result = {'summary': summary, 'artifact': str(path.relative_to(root)), 'latency_samples': cohort,
              'failed_samples':failed,
              'raw_request_records_complete':len(cohort)==summary['successful_arrivals_after_drain'] and len(failed)==summary['failed_arrivals_after_drain'],
              'gpu': {'unique_gpus': len(uuids), 'frames': frames, 'expected_gpus': summary['gpus'],
                      'valid_samples_by_gpu':dict(valid_by_gpu),
                      'values': {k: dist(v) for k, v in gpu_values.items()}},
              'kv_scheduler_gauges': {k: dist(v) for k, v in gauges.items()}}
    # Do not freeze an incomplete GPU trace if a delayed sampler still needs to flush.
    if len(uuids) == summary['gpus'] and frames:
        save(cache, result)
    return result


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def gpu_complete(d):
    r = d['summary']
    counts = d['gpu'].get('valid_samples_by_gpu', {})
    return (d['gpu']['unique_gpus'] == r['gpus'] and len(counts) == r['gpus'] and
            min(counts.values(), default=0) >= r['measurement_seconds'] * .8)


def protocol_valid(d):
    r = d['summary']
    spec_ok = (r['scenario']['speculative'] == 'off' or
               (r.get('spec_verify_steps', 0) > 0 and r.get('spec_accept_length_weighted') is not None))
    return r['valid_curve_point'] and gpu_complete(d) and spec_ok and d['raw_request_records_complete']


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', type=Path, required=True)
    a = p.parse_args()
    out = a.state / 'report'; out.mkdir(exist_ok=True)
    gpu = {prec: [r for path in (a.state / prec / 'gpu').glob('*.jsonl.gz') for r in records(path)]
           for prec in ('nvfp4', 'bf16')}
    groups = defaultdict(list)
    round_rows = []
    for path in sorted(a.state.glob('*/cache-*/*/c*/summary.json')):
        prec = path.relative_to(a.state).parts[0]
        d = analyze(a.state, path, gpu[prec])
        r, s = d['summary'], d['summary']['scenario']
        label = s.get('input_label', str(s['input_tokens']))
        key = (prec, s['workload'], label, s['cache'], s['speculative'], r['concurrency'])
        groups[key].append(d)
        row = {'precision': prec, 'workload': s['workload'], 'input_label': label,
               'cache': s['cache'], 'speculative': s['speculative'], 'concurrency': r['concurrency'],
               'repeat': r['repeat'], 'valid_measurement': r['valid_curve_point'],
               'gpu_telemetry_complete': gpu_complete(d), 'measurement_s': r['measurement_seconds'],
               'raw_request_records_complete':d['raw_request_records_complete'],
               'valid_full_protocol_round':protocol_valid(d),
               'window_output_tokens': r['output_tokens_received_in_window'], 'tokens_s_gpu': r['output_tokens_per_second_per_gpu'],
               'successes_in_window': r['completed_in_window'], 'failures_in_window': r['failed_in_window'],
               'arrival_successes': r['successful_arrivals_after_drain'], 'arrival_failures': r['failed_arrivals_after_drain'],
               'arrival_prompt_tokens': r['prompt_tokens_arrival_cohort'],
               'arrival_output_tokens_including_drain': r['output_tokens_arrival_cohort_including_drain'],
               'cached_prompt_tokens': r['cached_prompt_tokens_arrival_cohort'], 'cache_hit_rate_tokens': r['cache_hit_rate_tokens'],
               'spec_accept_length': r['spec_accept_length_weighted'], 'spec_accept_rate': r['spec_accept_rate_weighted'],
               'spec_verify_steps': r['spec_verify_steps'], 'spec_proposed_drafts': r['spec_num_proposed_drafts'],
               'spec_correct_drafts': r['spec_num_correct_drafts'], 'artifact': d['artifact']}
        failed = d.get('failed_samples', [])
        row.update(failed_client_input_tokens=sum(f['client_input_tokens'] for f in failed),
                   failed_native_output_tokens_known=sum(f['native_output_tokens'] or 0 for f in failed),
                   failed_requests_without_first_token=sum(f['ttft_s'] is None for f in failed))
        for metric in ('ttft_s', 'tpot_s', 'e2e_s', 'decode_tokens_per_second'):
            for stat in ('p50', 'p95'):
                row[metric + '_' + stat] = r[metric][stat]
        for metric, values in d['gpu']['values'].items():
            for stat in ('mean', 'p50', 'p95', 'max'):
                row['gpu_' + metric + '_' + stat] = values[stat]
        for metric, values in d['kv_scheduler_gauges'].items():
            for stat in ('p50', 'p95', 'max'):
                row[metric + '_' + stat] = values[stat]
        round_rows.append(row)
    write_csv(out / 'detailed_rounds.csv', round_rows)
    point_rows = []
    for key, ds in sorted(groups.items()):
        prec, workload, label, cache, spec, c = key
        good = [d for d in ds if protocol_valid(d)]
        expected = 5 if prec == 'nvfp4' and workload == 'synthetic' and label == '8192' and c in (4, 8) else 3
        row = dict(zip(('precision', 'workload', 'input_label', 'cache', 'speculative', 'concurrency'), key))
        row.update(repeats=len(ds), valid_repeats=len(good), required_repeats=expected, complete=len(good) >= expected)
        row['arrival_failures_all_repeats'] = sum(d['summary']['failed_arrivals_after_drain'] for d in ds)
        if good:
            samples = [s for d in good for s in d['latency_samples']]
            summaries = [d['summary'] for d in good]
            tokens = sum(r['output_tokens_received_in_window'] for r in summaries)
            seconds = sum(r['measurement_seconds'] for r in summaries)
            row.update(measurement_s=seconds, window_output_tokens=tokens, tokens_s_gpu=tokens / seconds / summaries[0]['gpus'],
                       requests=len(samples), successes_in_window=sum(r['completed_in_window'] for r in summaries),
                       failures_in_window=sum(r['failed_in_window'] for r in summaries),
                       arrival_prompt_tokens=sum(r['prompt_tokens_arrival_cohort'] for r in summaries),
                       arrival_output_tokens_including_drain=sum(r['output_tokens_arrival_cohort_including_drain'] for r in summaries),
                       throughput_repeat_sd=statistics.stdev(r['output_tokens_per_second_per_gpu'] for r in summaries) if len(good) > 1 else None,
                       decode_p50_repeat_sd=statistics.stdev(r['decode_tokens_per_second']['p50'] for r in summaries) if len(good) > 1 else None)
            for metric in ('ttft_s', 'tpot_s', 'e2e_s', 'decode_tokens_per_second', 'prompt_tokens', 'output_tokens'):
                for stat, value in dist([s[metric] for s in samples]).items():
                    row[metric + '_' + stat] = value
            util = [d['gpu']['values'].get('utilization.gpu') for d in good]
            util = [u for u in util if u and u['n']]
            row['gpu_utilization_percent_sample_weighted_mean'] = sum(u['mean']*u['n'] for u in util)/sum(u['n'] for u in util) if util else None
            mem = [d['gpu']['values'].get('memory.used',{}).get('max') for d in good]
            row['gpu_memory_used_mib_max'] = max((m for m in mem if m is not None),default=None)
            kv = [d['kv_scheduler_gauges'].get('sglang:token_usage',{}).get('p95') for d in good]
            row['kv_token_usage_p95_max_across_repeats'] = max((v for v in kv if v is not None),default=None)
        point_rows.append(row)
    write_csv(out / 'detailed_points.csv', point_rows)
    coverage = []
    for prec in ('nvfp4', 'bf16'):
        statefile = a.state / prec / 'status.json'
        state = json.loads(statefile.read_text()) if statefile.exists() else {}
        cases = [('synthetic', '8192', False, 'off', c) for c in (1, 2, 4, 8, 16, 32, 64, 128)]
        cases += [('synthetic', str(n), cache, 'off', c) for n in (32768, 65536) for cache in (False, True) for c in (1, 8, 32)]
        for spec in ('off', 'NGRAM'):
            phase = 'cache-off-' + spec
            bucketfile = a.state / prec / phase / 'coding-0/INPUT_BUCKETS.json'
            if not bucketfile.exists() and spec != 'off':
                bucketfile = a.state / prec / 'cache-off-off/coding-0/INPUT_BUCKETS.json'
            labels = [k for k, n in json.loads(bucketfile.read_text())['ranges'].items() if n] if bucketfile.exists() else ['native-input-bins-pending']
            cases += [('coding', label, False, spec, c) for label in labels for c in (1, 8, 32)]
        for workload, label, cache, spec, c in cases:
            key = (prec, workload, label, cache, spec, c)
            ds = groups.get(key, [])
            valid = sum(protocol_valid(d) for d in ds)
            need = 5 if prec == 'nvfp4' and label == '8192' and c in (4, 8) else 3
            status = 'complete' if valid >= need else ('partial' if ds else 'pending')
            phase = ('cache-on' if cache else 'cache-off') + '-' + spec
            if valid < need and any(f.get('configuration') == phase for f in state.get('failures', [])):
                status = 'failed_configuration'
            if workload == 'synthetic' and label == '8192' and not ds:
                limit = a.state / prec / 'cache-off-off/synthetic-8192/LATENCY_LIMIT.json'
                if limit.exists() and c > json.loads(limit.read_text())['concurrency']:
                    status = 'not_tested_above_measured_latency_limit'
            coverage.append({'precision': prec, 'workload': workload, 'input_label': label,
                             'cache': cache, 'speculative': spec, 'concurrency': c,
                             'valid_repeats': valid, 'required_repeats': need, 'status': status})
        for key, ds in sorted(groups.items()):
            model, workload, label, cache, spec, c = key
            if model != prec or workload != 'synthetic' or label != '8192' or c <= 128:
                continue
            valid = sum(protocol_valid(d) for d in ds)
            coverage.append({'precision':prec,'workload':workload,'input_label':label,'cache':cache,'speculative':spec,
                             'concurrency':c,'valid_repeats':valid,'required_repeats':3,'status':'complete' if valid>=3 else 'partial'})
    write_csv(out / 'acceptance_matrix.csv', coverage)
    unresolved = [str(p.relative_to(a.state)) for p in a.state.glob('*/cache-*/*/FOLLOWUP_REQUIRED.json')]
    complete = not unresolved and all(r['status'] in ('complete', 'not_tested_above_measured_latency_limit') for r in coverage)
    plan = json.loads((a.state / 'PLAN.json').read_text()) if (a.state / 'PLAN.json').exists() else {}
    metadata = {'image': IMAGE, 'measurement_plan': {k:v for k,v in plan.items() if k != 'models'},
                'models': plan.get('models', {}), 'deployments': {}}
    for prec in ('nvfp4', 'bf16'):
        root = a.state / prec
        metadata['deployments'][prec] = {
            'current_state': json.loads((root / 'status.json').read_text()) if (root / 'status.json').exists() else {},
            'hardware': [json.loads(p.read_text()) for p in sorted(root.glob('rank*/hardware.json'))],
            'launch_commands': {str(p.relative_to(root)):json.loads(p.read_text()) for p in sorted(root.glob('rank*/cache-*-command.json'))},
            'native_server_info': {p.name:json.loads(p.read_text()) for p in sorted(root.glob('cache-*-server-info.json'))}}
    save(out / 'reproducibility.json', metadata)
    def fmt(value, scale=1):
        return '—' if value is None else f'{value * scale:.3f}'
    text = ['# Muse 受控压测完整协议进度', '',
            ('全部已列测点完成；吞吐饱和与延迟边界见对应记录。' if complete else '以下结果为进行中的测量；完整曲线、长上下文与投机对照尚未全部完成。'), '',
            f'更新时间：{time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}。', '',
            '配置、模型完整 revision、镜像 digest、实际启动命令、物理 GPU 与 native server_info：[reproducibility.json](reproducibility.json)。', '',
            '已完成规定重复的测点如下。TTFT/E2E 单位为秒，TPOT 为毫秒/token；输出速度包含 reasoning 与回答。吞吐按实际测量窗计算。', '',
            '| 模型/输入 | 缓存/投机 | 并发 | 重复 | 测量秒数合计 | 成功/失败入场请求 | 输出 t/s/GPU ±重复SD | 单请求 t/s p50 ±重复SD | TTFT p50/p95 | TPOT p50/p95 | E2E p50/p95 |',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in point_rows:
        if not r['complete']:
            continue
        text.append(f'| {r["precision"]}/{r["input_label"]} | {r["cache"]}/{r["speculative"]} | {r["concurrency"]} | {r["valid_repeats"]} | {fmt(r["measurement_s"])} | {r["requests"]}/{r["arrival_failures_all_repeats"]} | {fmt(r["tokens_s_gpu"])} ± {fmt(r["throughput_repeat_sd"])} | {fmt(r["decode_tokens_per_second_p50"])} ± {fmt(r["decode_p50_repeat_sd"])} | {fmt(r["ttft_s_p50"])}/{fmt(r["ttft_s_p95"])} | {fmt(r["tpot_s_p50"],1000)}/{fmt(r["tpot_s_p95"],1000)} | {fmt(r["e2e_s_p50"])}/{fmt(r["e2e_s_p95"])} |')
    text += ['', '8K 基础吞吐—单用户速度曲线（仅含已验收测点）：', '',
             '![8K serving Pareto curve](decode_pareto_8k.png)', '',
             '可导出：[PDF](decode_pareto_8k.pdf)、[SVG](decode_pareto_8k.svg)、[数据 CSV](decode_pareto_8k.csv)。', '',
             '32K/64K × 缓存开关分面图：', '',
             '![Long-context Pareto curves](decode_pareto_long_context.png)', '',
             '![Coding and review Pareto curves](decode_pareto_coding.png)', '',
             '全部 synthetic 配置总览：[synthetic.png](synthetic.png)。', '',
             'coding+review 各 native 输入长度桶及投机开关分别成线：[coding.png](coding.png)。', '',
            f'已完成 {sum(r["status"] == "complete" for r in coverage)} / {len(coverage)} 个当前列出的目标测点。真实 coding 输入分桶在准备后展开；自适应扩展另见 SATURATION/EXTENSION 记录。', '',
            '| 模型 | 输入/工作负载 | 缓存 | 投机 | 并发 | 有效重复/目标 | 状态 |',
            '|---|---|---|---|---:|---:|---|']
    for r in coverage:
        text.append(f'| {r["precision"]} | {r["workload"]}/{r["input_label"]} | {r["cache"]} | {r["speculative"]} | {r["concurrency"]} | {r["valid_repeats"]}/{r["required_repeats"]} | {r["status"]} |')
    text += ['', '详细逐轮指标：[detailed_rounds.csv](detailed_rounds.csv)；逐请求合并后的测点统计：[detailed_points.csv](detailed_points.csv)。', '',
             '吞吐严格来自测量窗内收到的 native token 增量；延迟统计保留测量窗内入场请求的完整排空尾部。输出包括模型生成的 reasoning 和回答。', '',
             'GPU 指标来自所有物理 GPU 的 1 秒采样；KV/运行/排队指标来自 2 秒 Prometheus 原始记录。没有完整重复或 GPU 遥测的点不作为最终曲线点。', '',
             '误差棒为重复实验间的样本标准差。DeepSeek 未进行条件对齐的独立实测，本报告不补造对照数字。']
    states = {prec: metadata['deployments'][prec]['current_state'] for prec in ('nvfp4', 'bf16')}
    if any(s.get('phase', '').startswith('finished') for s in states.values()):
        text[2] = '已结束的本轮任务存在未完成配置；基础曲线和已验收测点可以使用，全协议尚未完成。' if not complete else text[2]
        text[6:6] = ['任务结束状态与缺口：', '', *[f'- {prec}: `{s.get("phase", "unknown")}`；{json.dumps(s.get("failures", []), ensure_ascii=False)}' for prec, s in states.items()], '',
                    'BF16 并发 256 是扩展边界测试：三轮均结束，仅一轮有效；两轮测量入场请求共 9 个 ReadError，TTFT p95 已超过 60 秒。保留三轮记录，但不画为有效三重复曲线点。', '',
                    'NVFP4 NGRAM: `NgramVerifyInput` 缺少 `draft_probs`；BF16 NGRAM: verify CUDA graph 分配 8 GiB page table 时 OOM。均无有效投机加速数字。', '',
                    '与 [DeepInfer 原图](https://github.com/deepseek-ai/DeepInfer/blob/main/doc/images/decode_pareto.png) 采用同类坐标。其 [官方说明](https://github.com/deepseek-ai/DeepInfer#performance-benchmarks) 为 64×SM100 decode 测试；图中为 128K 上下文及固定 nextn=3。这里是 H200、包含 prefill 的闭环服务测量，不能据此直接比较绝对吞吐或断言精度差异的因果效果。', '']
    (out / 'REPORT.zh-CN.md').write_text('\n'.join(text) + '\n')
    save(out / 'acceptance.json', {'generated_unix': time.time(), 'targets': coverage,
         'unresolved_saturation_followups': unresolved,
         'trace_read_errors':READ_ERRORS,
         'complete': complete,
         'incomplete_targets': [r for r in coverage if r['status'] not in ('complete', 'not_tested_above_measured_latency_limit')]})


if __name__ == '__main__':
    main()
