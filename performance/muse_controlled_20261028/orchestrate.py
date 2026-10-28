#!/usr/bin/env python3
"""Autonomous dedicated-job preparation, fixed configurations, measurement, plots."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

from bench import save


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--precision', choices=['nvfp4', 'bf16'], required=True)
    p.add_argument('--reuse-prepared', action='store_true', help='Resume only from complete, pinned per-rank weight proofs')
    p.add_argument('--client-on-node', action='store_true', help='Control from head, run each load client on the model head GPU host')
    a = p.parse_args()
    def interrupted(*_):
        raise KeyboardInterrupt('Slurm termination')
    signal.signal(signal.SIGTERM, interrupted)
    plan = json.loads((a.state / 'PLAN.json').read_text())
    plot_env = dict(os.environ)
    plot_env['PYTHONPATH'] = str(a.state / 'plot_deps')
    job = int(os.environ['SLURM_JOB_ID'])
    assert plan['jobs'][a.precision] == job
    n = 1 if a.precision == 'nvfp4' else 2
    # A recovery controller can itself run in a one-node step of a two-node job.
    # Query the allocation instead of trusting that step's narrowed environment.
    node_list = subprocess.check_output(['squeue', '-h', '-j', str(job), '-o', '%N'], text=True).strip()
    hosts = subprocess.check_output(['scontrol', 'show', 'hostnames', node_list], text=True).split()
    assert len(hosts) == n
    base = 'http://' + hosts[0].removeprefix('ip-').replace('-', '.') + ':31420'
    root = a.state / a.precision
    root.mkdir(exist_ok=True)
    prefix = ['srun', '--jobid=' + str(job), '--nodelist=' + node_list, '--overlap', '--exact', '--gres=none', '-N' + str(n),
              '-n' + str(n), '--ntasks-per-node=1', '-c64', '--immediate=30', sys.executable,
              str(a.state / 'node.py')]
    common = ['--state', str(a.state), '--precision', a.precision]
    status = root / 'status.json'
    def update(phase, **kw):
        save(status, {'utc_unix': time.time(), 'job': job, 'hosts': hosts, 'precision': a.precision, 'phase': phase, **kw})
    update('preparing_and_verifying_pinned_weights')
    if a.reuse_prepared:
        for rank in range(n):
            proof = json.loads((root / ('rank' + str(rank)) / 'weights.json').read_text())
            assert proof['complete'] and proof['revision'] == plan['models'][a.precision]['revision']
            assert set(proof['verified_files']) == {f['file'] for f in plan['models'][a.precision]['files']}
    else:
        subprocess.run([*prefix, 'prepare', *common], check=True)
    monitor = subprocess.Popen(['srun', '--jobid=' + str(job), '--nodelist=' + node_list, '--overlap', '--exact', '--gres=none',
        '-N' + str(n), '-n' + str(n), '--ntasks-per-node=1', '-c1', sys.executable,
        str(a.state / 'gpu.py'), '--output', str(root / 'gpu')])
    server = None
    failures = []
    try:
        for cache, speculative in ((False, 'off'), (True, 'off'), (False, 'NGRAM')):
            phase = ('cache-on' if cache else 'cache-off') + '-' + speculative
            update('starting_fixed_server_configuration', configuration=phase)
            flags = (['--cache'] if cache else []) + ['--speculative', speculative]
            log = (root / (phase + '-server.log')).open('a')
            server = subprocess.Popen([*prefix, 'serve', *common, *flags], stdout=log, stderr=subprocess.STDOUT)
            ready = False
            with httpx.Client(trust_env=False, timeout=10) as client:
                for _ in range(1080):
                    if server.poll() is not None:
                        break
                    try:
                        r = client.get(base + '/server_info')
                        if r.status_code == 200:
                            info = r.json()
                            assert info['served_model_name'] == 'muse-spark-open-' + a.precision
                            assert bool(info['disable_radix_cache']) is not cache
                            assert (info.get('speculative_algorithm') or None) == (None if speculative == 'off' else speculative)
                            save(root / (phase + '-server-info.json'), info)
                            ready = True; break
                    except httpx.HTTPError:
                        pass
                    time.sleep(10)
            if not ready:
                failures.append({'configuration': phase, 'reason': 'Server failed readiness; see preserved startup log'})
                # A failed optional NGRAM configuration is reported, never relabelled as tested.
                if speculative == 'off':
                    raise RuntimeError('Required baseline/cache server failed readiness')
            else:
                cases = []
                if not cache and speculative == 'off':
                    cases.append(('synthetic', 8192, '1,2,4,8,16,32,64,128', True))
                if speculative == 'off':
                    cases.extend(('synthetic', tokens, '1,8,32', False) for tokens in (32768, 65536))
                if not cache:
                    cases.append(('coding', 0, '1,8,32', False))
                for workload, tokens, concurrency, adaptive in cases:
                    assert monitor.poll() is None, 'GPU telemetry collector exited'
                    directory = root / phase / (workload + '-' + str(tokens))
                    update('measuring', configuration=phase, workload=workload, input_tokens=tokens,
                           output=str(directory))
                    command = [sys.executable, str(a.state / 'bench.py'), '--base', base,
                        '--output', str(directory), '--corpus', str(a.state / 'coding_prompts.jsonl'),
                        '--precision', a.precision, '--gpus', str(8 * n), '--input-tokens', str(tokens),
                        '--workload', workload, '--concurrency', concurrency, '--server-cap', str(plan['server_cap']),
                        '--seconds', str(plan['measurement_min_seconds']), '--warmup', str(plan['warmup_min_seconds']),
                        '--min-samples', str(plan['minimum_samples']), '--ttft-limit', str(plan['ttft_p95_limit_s']),
                        '--e2e-limit', str(plan['e2e_p95_limit_s']), *flags]
                    if adaptive:
                        command += ['--adaptive']
                    if a.client_on_node:
                        command = ['srun', '--jobid=' + str(job), '--nodelist=' + hosts[0],
                            '--chdir=' + str(a.state), '--overlap', '--exact', '--gres=none',
                            '-N1', '-n1', '-c8', '--immediate=30', *command]
                    result = subprocess.run(command)
                    if result.returncode:
                        failures.append({'configuration': phase, 'case': workload + '-' + str(tokens), 'returncode': result.returncode})
                    if (directory / 'FOLLOWUP_REQUIRED.json').exists():
                        failures.append({'configuration': phase, 'case': workload + '-' + str(tokens), 'reason': 'Larger-cap saturation followup required; no peak claimed'})
                    subprocess.run([sys.executable, str(a.state / 'plot.py'), '--state', str(a.state)], env=plot_env, check=False)
            subprocess.run([*prefix, 'stop', *common], check=False)
            try:
                server.wait(timeout=90)
            except subprocess.TimeoutExpired:
                server.terminate(); server.wait(timeout=30)
            server = None
            log.close()
        update('finished' if not failures else 'finished_with_incomplete_cases', failures=failures)
    except BaseException as exc:
        update('failed', error=type(exc).__name__ + ': ' + str(exc), failures=failures)
        raise
    finally:
        subprocess.run([*prefix, 'stop', *common], check=False)
        if server is not None:
            try:
                server.wait(timeout=90)
            except subprocess.TimeoutExpired:
                server.terminate()
        monitor.send_signal(signal.SIGTERM)
        try:
            monitor.wait(timeout=15)
        except subprocess.TimeoutExpired:
            monitor.kill()
        subprocess.run([sys.executable, str(a.state / 'plot.py'), '--state', str(a.state)], env=plot_env, check=False)


if __name__ == '__main__':
    main()
