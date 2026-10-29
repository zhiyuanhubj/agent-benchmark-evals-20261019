#!/usr/bin/env python3
"""Closed-loop native SGLang load; token-window throughput, arrival-cohort latency."""
import argparse
import asyncio
import copy
import gzip
import hashlib
import json
import math
import random
import statistics
import time
import uuid
from pathlib import Path

import httpx


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def percentile(values, q):
    values = sorted(v for v in values if v is not None and math.isfinite(v))
    if not values:
        return None
    rank = (len(values) - 1) * q
    a, b = math.floor(rank), math.ceil(rank)
    return values[a] + (values[b] - values[a]) * (rank - a)


def distribution(values):
    values = [x for x in values if x is not None]
    return {'n': len(values), 'p50': percentile(values, .5), 'p95': percentile(values, .95)}


def window_tokens(events, start, end):
    """Events are (client receive timestamp, newly received native token count)."""
    return sum(n for t, n in events if start <= t < end)


def summarize(rows, events, start, end, gpus):
    # Drain all arrivals before computing latency; avoid dropping slow right tails.
    cohort = [r for r in rows if start <= r['started'] < end]
    ok = [r for r in cohort if r['valid']]
    in_window = [r for r in rows if start <= r['finished'] < end]
    duration = end - start
    tokens = window_tokens(events, start, end)
    spec = [r['meta'] for r in ok if r['meta'].get('spec_verify_ct')]
    verify = sum(m['spec_verify_ct'] for m in spec)
    proposed = sum(m.get('spec_num_proposed_drafts', 0) for m in spec)
    correct = sum(m.get('spec_num_correct_drafts', 0) for m in spec)
    return {
        'measurement_start_monotonic': start, 'measurement_end_monotonic': end,
        'measurement_seconds': duration, 'output_tokens_received_in_window': tokens,
        'output_tokens_per_second': tokens / duration,
        'output_tokens_per_second_per_gpu': tokens / duration / gpus,
        'arrivals_in_window': len(cohort), 'successful_arrivals_after_drain': len(ok),
        'failed_arrivals_after_drain': len(cohort) - len(ok),
        'completed_in_window': sum(r['valid'] for r in in_window),
        'failed_in_window': sum(not r['valid'] for r in in_window),
        'prompt_tokens_arrival_cohort': sum(r['meta'].get('prompt_tokens', 0) for r in ok),
        'output_tokens_arrival_cohort_including_drain': sum(r['meta'].get('completion_tokens', 0) for r in ok),
        'cached_prompt_tokens_arrival_cohort': sum(r['meta'].get('cached_tokens', 0) for r in ok),
        'ttft_s': distribution([r['ttft_s'] for r in ok]),
        'tpot_s': distribution([r['tpot_s'] for r in ok]),
        'e2e_s': distribution([r['e2e_s'] for r in ok]),
        'decode_tokens_per_second': distribution([r['decode_tokens_per_second'] for r in ok]),
        'decode_speed_samples': [r['decode_tokens_per_second'] for r in ok],
        'spec_verify_steps': verify, 'spec_num_proposed_drafts': proposed,
        'spec_num_correct_drafts': correct,
        'spec_accept_length_weighted': sum(m['completion_tokens'] for m in spec) / verify if verify else None,
        'spec_accept_rate_weighted': correct / proposed if proposed else None,
        'successful_completion_times': [r['finished'] for r in ok],
    }


async def tokenize(client, base, text):
    r = await client.post(base + '/tokenize', json={
        'messages': [{'role': 'user', 'content': text}],
        'chat_template_kwargs': {'reasoning_effort': 'xhigh'}})
    r.raise_for_status()
    j = r.json()
    assert j['count'] == len(j['tokens'])
    return j['tokens']


class Prompts:
    def __init__(self, templates, scenario, seed):
        self.templates, self.scenario, self.seed = templates, scenario, seed
        self.sequence = 0

    @classmethod
    async def build(cls, client, base, corpus, scenario, seed):
        templates = []
        if scenario['workload'] == 'coding':
            for item in corpus:
                tokens = await tokenize(client, base, item['prompt'])
                # Native prompts are left unchanged; distributions are reported.
                low, high = scenario.get('input_range', [0, 130048])
                if low <= len(tokens) < high and len(tokens) + 1024 < 131072:
                    templates.append({'id': item['id'], 'ids': tokens, 'source': item['source']})
        else:
            n = scenario['input_tokens']
            text = ('A synthetic context length and throughput measurement.\n' +
                    'record: index, value, checksum, invariant.\n' * (n // 4) +
                    '\nExplain a binary search implementation and its invariants.')
            ids = await tokenize(client, base, text)
            assert len(ids) >= n
            ids = ids[:n - 32] + ids[-32:]
            templates.append({'id': 'fixed-length-synthetic', 'ids': ids})
        assert templates
        return cls(templates, scenario, seed)

    def next(self):
        seq = self.sequence
        self.sequence += 1
        template = self.templates[seq % len(self.templates)]
        tokens = template['ids'].copy()
        if self.scenario['workload'] != 'coding':
            # Non-special, ordinary token IDs from the original tokenized text.
            rng = random.Random(self.seed + seq)
            candidates = sorted(set(tokens[128:-32]))
            pos = int(len(tokens) * .90) if self.scenario['cache'] else 128
            tokens[pos:pos + 16] = [rng.choice(candidates) for _ in range(16)]
        return tokens, {'sequence': seq, 'corpus_id': template['id'],
                        'input_ids_sha256': hashlib.sha256(json.dumps(tokens).encode()).hexdigest()}


class Round:
    def __init__(self, args, scenario, c, repeat, directory):
        self.args, self.scenario, self.c, self.repeat = args, scenario, c, repeat
        self.directory = directory
        self.rows, self.events = [], []
        self.start = self.end = None
        self.stop = False
        self.epoch_offset = time.time() - time.perf_counter()
        self.metrics_samples = []

    async def request(self, client, prompts, worker):
        tokens, provenance = prompts.next()
        rid = uuid.uuid4().hex
        payload = {'rid': rid, 'input_ids': tokens, 'stream': True,
                   'sampling_params': {'max_new_tokens': 1024, 'min_new_tokens': 1024,
                                       'ignore_eos': True, 'temperature': 1.0, 'top_p': 1.0, 'top_k': -1}}
        started = time.perf_counter()
        count, first, last = 0, None, None
        meta, error, done, status, text = {}, None, False, None, ''
        timings = []
        try:
            async with client.stream('POST', self.args.base + '/generate', json=payload) as r:
                status = r.status_code
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith('data: '):
                        continue
                    raw = line[6:]
                    if raw == '[DONE]':
                        done = True
                        continue
                    j = json.loads(raw)
                    now = time.perf_counter()
                    meta = j.get('meta_info') or meta
                    new_count = meta.get('completion_tokens', count)
                    assert new_count >= count, 'Non-monotonic native token count'
                    delta = new_count - count
                    if delta:
                        first = now if first is None else first
                        last = now
                        self.events.append((now, delta))
                        timings.append((now - started, new_count))
                    count = new_count
                    text = j.get('text', text)
        except Exception as exc:
            error = type(exc).__name__ + ': ' + str(exc)[:300]
        finished = time.perf_counter()
        span = last - first if last is not None else None
        valid = (status == 200 and done and count == 1024 and
                 meta.get('prompt_tokens') == len(tokens) and 'cached_tokens' in meta and error is None)
        row = dict(id=rid, worker=worker, started=started, finished=finished, http_status=status,
                   meta=meta, error=error, done=done, valid=valid, input_tokens_expected=len(tokens),
                   ttft_s=first - started if first is not None else None,
                   tpot_s=span / (count - 1) if span is not None and count > 1 else None,
                   decode_tokens_per_second=(count - 1) / span if span else None,
                   e2e_s=finished - started, token_timing=timings, text=text, provenance=provenance)
        self.rows.append(row)
        self.raw.write(json.dumps(row, ensure_ascii=False) + '\n')
        self.raw.flush()
        return row

    async def worker(self, client, prompts, worker):
        while not self.stop:
            result = await self.request(client, prompts, worker)
            if not result['valid']:
                await asyncio.sleep(.25)  # Bound pressure if the server is unhealthy.

    async def telemetry(self, client):
        with gzip.open(self.directory / 'backend.jsonl.gz', 'wt') as f:
            while not self.stop:
                record = {'utc_unix': time.time(), 'monotonic': time.perf_counter()}
                for path in ('/server_info', '/metrics'):
                    try:
                        r = await client.get(self.args.base + path, timeout=10)
                        record[path] = {'http': r.status_code, 'body': r.json() if path == '/server_info' and r.status_code == 200 else r.text}
                        if path == '/metrics' and r.status_code == 200:
                            self.metrics_samples.append(time.perf_counter())
                    except Exception as exc:
                        record[path] = {'error': type(exc).__name__}
                f.write(json.dumps(record) + '\n'); f.flush()
                await asyncio.sleep(2)

    async def run(self, client, prompts):
        self.directory.mkdir(parents=True, exist_ok=False)
        before = (await client.get(self.args.base + '/server_info')).json()
        save(self.directory / 'server-before.json', before)
        r = await client.post(self.args.base + '/flush_cache', params={'timeout': 30})
        r.raise_for_status()
        if self.scenario['cache'] and self.scenario['workload'] == 'synthetic':
            ids = prompts.templates[0]['ids'][:int(self.scenario['input_tokens'] * .90)]
            r = await client.post(self.args.base + '/generate', json={'input_ids': ids,
                'sampling_params': {'max_new_tokens': 1, 'temperature': 1.0}})
            r.raise_for_status()
            save(self.directory / 'prefix-prime.json', r.json())
        self.raw = gzip.open(self.directory / 'requests.jsonl.gz', 'wt')
        tasks = [asyncio.create_task(self.worker(client, prompts, i)) for i in range(self.c)]
        monitor = asyncio.create_task(self.telemetry(client))
        warm = time.perf_counter()
        reason = None
        try:
            # At least 60 seconds and >=4 completed warmups; bounded by the request timeout.
            while time.perf_counter() - warm < self.args.warmup or sum(r['valid'] for r in self.rows) < 4:
                await asyncio.sleep(1)
                if time.perf_counter() - warm > self.args.request_timeout:
                    raise RuntimeError('Warmup failed to complete four valid requests before timeout')
            self.start = time.perf_counter()
            while True:
                await asyncio.sleep(.25)
                now = time.perf_counter()
                finished = [r for r in self.rows if r['started'] >= self.start]
                ok = [r for r in finished if r['valid']]
                elapsed = now - self.start
                if elapsed >= self.args.seconds and len(ok) >= self.args.min_samples:
                    reason = 'minimum_time_and_sample_count_met'; break
                if elapsed >= self.args.max_seconds:
                    reason = 'measurement_max_seconds'; break
                # Do not silently hammer an unhealthy deployment.
                if len(finished) >= 10 and sum(not r['valid'] for r in finished) / len(finished) > .10:
                    reason = 'error_rate_over_10_percent'; break
            self.end = time.perf_counter()
        finally:
            self.stop = True
            # Already admitted requests finish naturally; no new admission after end.
            results = await asyncio.gather(*tasks, return_exceptions=True)
            await monitor
            self.raw.close()
            if any(isinstance(r, BaseException) for r in results):
                raise RuntimeError('Load worker crashed: ' + str(results))
        if self.start is None or self.end is None:
            raise RuntimeError('No valid measurement window')
        summary = summarize(self.rows, self.events, self.start, self.end, self.args.gpus)
        summary.update(scenario=self.scenario, concurrency=self.c, repeat=self.repeat,
                       measurement_start_unix=self.start + self.epoch_offset,
                       measurement_end_unix=self.end + self.epoch_offset,
                       precision=self.args.precision, gpus=self.args.gpus,
                       stop_reason=reason, warmup_seconds=self.start - warm,
                       sample_target_met=summary['successful_arrivals_after_drain'] >= self.args.min_samples,
                       duration_target_met=summary['measurement_seconds'] >= self.args.seconds,
                       drain_seconds=time.perf_counter() - self.end,
                       input_tokens=distribution([r['meta'].get('prompt_tokens') for r in self.rows if r['valid'] and self.start <= r['started'] < self.end]))
        summary['prometheus_samples_in_window'] = sum(self.start <= t < self.end for t in self.metrics_samples)
        prompt = summary['prompt_tokens_arrival_cohort']
        summary['cache_hit_rate_tokens'] = summary['cached_prompt_tokens_arrival_cohort'] / prompt if prompt else None
        if not self.scenario['cache'] and summary['cached_prompt_tokens_arrival_cohort']:
            summary['invalid_reason'] = 'Cache-disabled configuration returned cached prompt tokens'
        if not summary['prometheus_samples_in_window']:
            summary['invalid_reason'] = 'No Prometheus telemetry during the measurement window'
        summary['valid_curve_point'] = (summary['sample_target_met'] and summary['duration_target_met'] and
                                         not summary['failed_arrivals_after_drain'] and 'invalid_reason' not in summary)
        save(self.directory / 'summary.json', summary)
        print(json.dumps({'directory': str(self.directory), 'concurrency': self.c, 'repeat': self.repeat,
                          'throughput_per_gpu': summary['output_tokens_per_second_per_gpu'],
                          'decode_p50': summary['decode_tokens_per_second']['p50'],
                          'valid': summary['valid_curve_point']}), flush=True)
        return summary


async def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    scenario = {'input_tokens': args.input_tokens, 'cache': args.cache, 'speculative': args.speculative,
                'workload': args.workload}
    if getattr(args, 'input_range', None):
        scenario.update(input_range=args.input_range, input_label=args.input_label)
    corpus = [json.loads(line) for line in args.corpus.read_text().splitlines()]
    limits = httpx.Limits(max_connections=1024, max_keepalive_connections=512)
    async with httpx.AsyncClient(trust_env=False, limits=limits,
                                 timeout=httpx.Timeout(args.request_timeout, connect=15)) as client:
        info = (await client.get(args.base + '/server_info')).json()
        assert bool(info['disable_radix_cache']) is not args.cache
        assert info['kv_cache_dtype'] == 'fp8_e4m3'
        assert (info.get('speculative_algorithm') or None) == (args.speculative if args.speculative != 'off' else None)
        assert info['max_running_requests'] == args.server_cap
        save(args.output / 'CONFIG.json', {'args': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}, 'server_info': info})
        prompts = await Prompts.build(client, args.base, corpus, scenario, args.seed)
        save(args.output / 'PROMPTS.json', {'templates': prompts.templates, 'seed': args.seed, 'scenario': scenario})
        curves = []
        concurrencies = [int(c) for c in args.concurrency.split(',')]
        for concurrency in concurrencies:
            repeats = 5 if concurrency in (4, 8) and args.precision == 'nvfp4' and args.input_tokens == 8192 and args.workload == 'synthetic' else 3
            for repeat in range(repeats):
                directory = args.output / f'c{concurrency:03d}-r{repeat}'
                if (directory / 'summary.json').exists():
                    row = json.loads((directory / 'summary.json').read_text())
                elif directory.exists():
                    raise RuntimeError(f'Interrupted run retained at {directory}; reconcile rather than overwrite')
                else:
                    prompts.sequence = 0
                    row = await Round(args, scenario, concurrency, repeat, directory).run(client, prompts)
                curves.append(row)
            save(args.output / 'progress.json', {'scenario': scenario, 'rounds': curves, 'complete': False})
            group = curves[-repeats:]
            p95ttft = max((r['ttft_s']['p95'] or 0) for r in group)
            p95e2e = max((r['e2e_s']['p95'] or 0) for r in group)
            if p95ttft > args.ttft_limit or p95e2e > args.e2e_limit:
                save(args.output / 'LATENCY_LIMIT.json', {'concurrency': concurrency, 'ttft_p95_max': p95ttft, 'e2e_p95_max': p95e2e})
                if args.adaptive:
                    break
            if args.adaptive and any(r['failed_arrivals_after_drain'] for r in group):
                save(args.output / 'ERROR_STOP.json', {'concurrency': concurrency, 'reason': 'Measured request failures; higher offered concurrency is not tested automatically'})
                break
        # Extend the baseline only beyond the requested 1..128 grid and only if safe.
        if args.adaptive and not (args.output / 'LATENCY_LIMIT.json').exists() and not (args.output / 'ERROR_STOP.json').exists() and concurrencies[-1] == 128:
            by_c = {c: statistics.median(r['output_tokens_per_second_per_gpu'] for r in curves if r['concurrency'] == c) for c in concurrencies}
            gain = by_c[128] / by_c[64] - 1
            if gain >= .05:
                for repeat in range(3):
                    d = args.output / f'c256-r{repeat}'
                    prompts.sequence = 0
                    row = json.loads((d / 'summary.json').read_text()) if (d / 'summary.json').exists() else await Round(args, scenario, 256, repeat, d).run(client, prompts)
                    curves.append(row)
            extra = [r for r in curves if r['concurrency'] == 256]
            gain256 = statistics.median(r['output_tokens_per_second_per_gpu'] for r in extra) / by_c[128] - 1 if extra else None
            limited = any((r['ttft_s']['p95'] or 0) > args.ttft_limit or (r['e2e_s']['p95'] or 0) > args.e2e_limit for r in extra)
            reached = gain < .05 or (gain256 is not None and gain256 < .05) or limited
            result = {'gain_64_to_128': gain, 'gain_128_to_256': gain256, 'tested_256': bool(extra),
                      'admission_cap': args.server_cap, 'saturation_or_latency_limit_observed': reached,
                      'rule': 'At most 256 incoming in this pinned configuration; >=5% gain triggers extension. An unresolved admission ceiling is not a measured peak.'}
            save(args.output / 'SATURATION.json', result)
            if not reached:
                save(args.output / 'FOLLOWUP_REQUIRED.json', {'reason': 'Throughput still grew >=5% at admission cap; peak not established. Requires a separately frozen larger-cap server configuration.'})
        save(args.output / 'progress.json', {'scenario': scenario, 'rounds': curves, 'complete': True})


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--corpus', type=Path, required=True)
    p.add_argument('--precision', choices=['nvfp4', 'bf16'], required=True)
    p.add_argument('--gpus', type=int, required=True)
    p.add_argument('--input-tokens', type=int, default=8192)
    p.add_argument('--cache', action='store_true')
    p.add_argument('--speculative', choices=['off', 'NGRAM'], default='off')
    p.add_argument('--workload', choices=['synthetic', 'coding'], default='synthetic')
    p.add_argument('--concurrency', default='1,2,4,8,16,32,64,128')
    p.add_argument('--server-cap', type=int, default=256)
    p.add_argument('--seconds', type=float, default=120)
    p.add_argument('--warmup', type=float, default=60)
    p.add_argument('--min-samples', type=int, default=30)
    p.add_argument('--max-seconds', type=float, default=1800)
    p.add_argument('--request-timeout', type=float, default=600)
    p.add_argument('--ttft-limit', type=float, default=60)
    p.add_argument('--e2e-limit', type=float, default=300)
    p.add_argument('--seed', type=int, default=20261028)
    p.add_argument('--adaptive', action='store_true')
    return p


async def extend_saturation(args, baseline):
    """Continue offered concurrency with the SAME pinned serving admission cap."""
    a = copy.copy(args)
    a.output, a.input_tokens, a.workload = baseline, 8192, 'synthetic'
    a.cache, a.speculative = False, 'off'
    scenario = {'input_tokens': 8192, 'cache': False, 'speculative': 'off', 'workload': 'synthetic'}
    reference = [json.loads(p.read_text()) for p in sorted(baseline.glob('c256-r*/summary.json'))]
    assert len(reference) == 3 and all(r['valid_curve_point'] for r in reference)
    previous = statistics.median(r['output_tokens_per_second_per_gpu'] for r in reference)
    corpus = [json.loads(line) for line in a.corpus.read_text().splitlines()]
    rounds, steps, stop = [], [], None
    async with httpx.AsyncClient(trust_env=False, limits=httpx.Limits(max_connections=4096, max_keepalive_connections=2048),
                                 timeout=httpx.Timeout(a.request_timeout, connect=15)) as client:
        info = (await client.get(a.base + '/server_info')).json()
        assert info['disable_radix_cache'] and info['max_running_requests'] == a.server_cap
        assert not info.get('speculative_algorithm') and info['kv_cache_dtype'] == 'fp8_e4m3'
        save(baseline / 'EXTENSION_CONFIG.json', {'server_info': info, 'admission_cap_unchanged': a.server_cap,
             'definition': 'Offered closed-loop concurrency may exceed the serving admission cap; active versus queued counts are retained. This measures saturation of this fixed configuration, not an absolute hardware optimum.'})
        prompts = await Prompts.build(client, a.base, corpus, scenario, a.seed)
        for c in (512, 1024, 2048):
            group = []
            for rep in range(3):
                directory = baseline / f'c{c:03d}-r{rep}'
                if (directory / 'summary.json').exists():
                    row = json.loads((directory / 'summary.json').read_text())
                elif directory.exists():
                    raise RuntimeError('Interrupted extension retained: ' + str(directory))
                else:
                    prompts.sequence = 0
                    row = await Round(a, scenario, c, rep, directory).run(client, prompts)
                group.append(row); rounds.append(row)
            current = statistics.median(r['output_tokens_per_second_per_gpu'] for r in group)
            gain = current / previous - 1
            steps.append({'concurrency': c, 'throughput_gain': gain, 'reference_throughput_per_gpu': previous})
            if any(r['failed_arrivals_after_drain'] or not r['valid_curve_point'] for r in group):
                stop = 'request_failures_or_incomplete_measurement'; break
            if max(r['ttft_s']['p95'] for r in group) > a.ttft_limit or max(r['e2e_s']['p95'] for r in group) > a.e2e_limit:
                stop = 'latency_limit'; break
            if gain < .05:
                stop = 'less_than_5_percent_throughput_gain'; break
            previous = current
    resolved = stop in ('latency_limit', 'less_than_5_percent_throughput_gain')
    save(baseline / 'EXTENSION_RESOLUTION.json', {'steps': steps, 'stop_reason': stop or 'client_safety_cap_2048',
         'saturation_or_latency_limit_observed': resolved, 'rounds': rounds})
    if resolved:
        flag = baseline / 'FOLLOWUP_REQUIRED.json'
        if flag.exists():
            save(baseline / 'FOLLOWUP_RESOLVED.json', json.loads(flag.read_text()))
            flag.unlink()


async def dispatch(args):
    # The already-running NVFP4 baseline uses the original control code. Its next
    # invocation (32K) resolves any >256 continuation before admitting long-context load.
    baseline = args.output.parent / 'synthetic-8192'
    if args.workload == 'synthetic' and args.input_tokens == 32768 and not args.cache and args.speculative == 'off':
        if (baseline / 'FOLLOWUP_REQUIRED.json').exists():
            await extend_saturation(args, baseline)
    if args.workload == 'coding':
        corpus = [json.loads(line) for line in args.corpus.read_text().splitlines()]
        counts = {}
        ranges = ((0, 8192), (8192, 32768), (32768, 65536), (65536, 130048))
        async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
            lengths = [len(await tokenize(client, args.base, r['prompt'])) for r in corpus]
        args.output.mkdir(parents=True, exist_ok=True)
        for lo, hi in ranges:
            label = f'native-{lo}-{hi}'
            counts[label] = sum(lo <= n < hi for n in lengths)
        save(args.output / 'INPUT_BUCKETS.json', {'ranges': counts, 'native_prompt_lengths': lengths,
             'corpus_sha256': hashlib.sha256(args.corpus.read_bytes()).hexdigest(), 'padding_or_truncation': False})
        for lo, hi in ranges:
            label = f'native-{lo}-{hi}'
            if not counts[label]:
                continue
            a = copy.copy(args)
            a.input_range, a.input_label = [lo, hi], label
            a.output = args.output.parent / ('coding-' + label)
            await run(a)
        return
    await run(args)
    if args.adaptive and (args.output / 'FOLLOWUP_REQUIRED.json').exists():
        await extend_saturation(args, args.output)


if __name__ == '__main__':
    asyncio.run(dispatch(parser().parse_args()))
