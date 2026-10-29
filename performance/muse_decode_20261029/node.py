#!/usr/bin/env python3
"""Prepare/serve only the freshly allocated controlled-test hosts."""
import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
from pathlib import Path

IMAGE = 'lmsysorg/sglang@sha256:8cfc5a72cb296771f5f8a4a4688cb6d05685610a830cbb616fa4ab0eb7bb2b0a'


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def docker(*args):
    env = os.environ.copy()
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    return ['docker', '--host=unix:///var/run/docker.sock', *args], env


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['prepare', 'serve', 'stop'])
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--precision', choices=['nvfp4', 'bf16'], required=True)
    p.add_argument('--cache', action='store_true')
    p.add_argument('--speculative', default='off')
    p.add_argument('--paired-graphs',action='store_true')
    a = p.parse_args()
    job = os.environ['SLURM_JOB_ID']
    plan = json.loads((a.state / 'PLAN.json').read_text())
    assert int(job) == plan['jobs'][a.precision]
    node_list = subprocess.check_output(['squeue', '-h', '-j', job, '-o', '%N'], text=True).strip()
    hosts = subprocess.check_output(['scontrol', 'show', 'hostnames', node_list], text=True).split()
    assert socket.gethostname() in hosts
    rank = hosts.index(socket.gethostname())
    assert len(hosts) == (1 if a.precision == 'nvfp4' else 2)
    local = Path('/opt/dlami/nvme') / ('zhiyuan-muse-perf-' + job + '-' + str(rank))
    shared = a.state / a.precision / ('rank' + str(rank))
    shared.mkdir(parents=True, exist_ok=True)
    local.mkdir(parents=True, exist_ok=True)
    name = 'zhiyuan-muse-controlled-' + job + '-' + str(rank)
    if a.action == 'stop':
        cmd, env = docker('stop', '-t', '30', name)
        subprocess.run(cmd, env=env)
        return
    cmd, env = docker('info', '--format', '{{.ServerVersion}}')
    run(cmd, env=env)
    # These jobs are dedicated to this suite; never stop another user's process.
    apps = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'], text=True).strip()
    assert not apps, 'Allocated GPUs are occupied; refusing to overwrite a workload'
    hardware = subprocess.check_output(['nvidia-smi', '--query-gpu=name,uuid,driver_version,memory.total',
                                         '--format=csv,noheader,nounits'], text=True).splitlines()
    assert len(hardware) == 8 and all('H200' in row for row in hardware)
    (shared / 'hardware.json').write_text(json.dumps({'hostname': socket.gethostname(), 'gpus': hardware}, indent=2))
    cmd, env = docker('image', 'inspect', IMAGE)
    if subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        cmd, env = docker('pull', IMAGE)
        run(cmd, env=env)
    if a.action == 'prepare':
        manifest = plan['models'][a.precision]
        if a.precision == 'nvfp4':
            weights = Path(manifest['shared_path'])
            # Shared immutable weights were fully hashed by the first replica.
            # Reuse that receipt only when every file predates the allocation
            # and therefore remained unchanged throughout that verification.
            cutoff=json.loads((Path(plan['controller_root'])/'ALLOCATIONS.json').read_text())['created_unix']
            stable=all((weights/r['file']).is_file() and (weights/r['file']).stat().st_size==r['bytes'] and
                       (weights/r['file']).stat().st_ctime < cutoff and (weights/r['file']).stat().st_mtime < cutoff
                       for r in manifest['files'])
            if stable:
                for receipt in sorted(Path(plan['controller_root']).glob('*/nvfp4/rank0/weights.json')):
                    prior=json.loads(receipt.read_text())
                    if prior.get('complete') and prior['revision']==manifest['revision'] and prior['path']==str(weights) and set(prior['verified_files'])=={r['file'] for r in manifest['files']}:
                        prior['reused_verified_shared_receipt']=str(receipt)
                        prior['metadata_unchanged_since_before_first_verification']=True
                        (shared/'weights.json').write_text(json.dumps(prior,indent=2)+'\n')
                        return
        else:
            weights = local / 'weights'
            # Reuse a complete local, pinned candidate before downloading 1.64 TB.
            for candidate in sorted(Path('/opt/dlami/nvme').glob('zhiyuan-muse-perf-*/weights')):
                if all((candidate/r['file']).is_file() and (candidate/r['file']).stat().st_size==r['bytes'] and
                       (candidate/r['file']).resolve().is_relative_to(candidate.resolve()) for r in manifest['files']):
                    weights=candidate;break
            if not all((weights/r['file']).is_file() and (weights/r['file']).stat().st_size==r['bytes'] for r in manifest['files']):
                needed=sum(r['bytes'] for r in manifest['files'] if not (weights/r['file']).exists())
                free=shutil.disk_usage(local).free
                assert free > needed+250*2**30, f'Insufficient local NVMe space: free={free}, missing={needed}; no unrelated files deleted'
                os.environ['HF_XET_CACHE']=str(local/'xet-cache')
                from huggingface_hub import snapshot_download
                snapshot_download(manifest['repo'], revision=manifest['revision'],
                                  local_dir=weights, allow_patterns=[r['file'] for r in manifest['files']], max_workers=8)
        checked = []
        for row in manifest['files']:
            target = weights / row['file']
            assert target.is_file() and target.stat().st_size == row['bytes'], str(target)
            h = hashlib.sha256() if row['algorithm'] == 'sha256' else hashlib.sha1()
            if row['algorithm'] == 'git-blob-sha1':
                h.update(('blob ' + str(row['bytes']) + '\0').encode())
            with target.open('rb') as stream:
                for block in iter(lambda: stream.read(16 * 2**20), b''):
                    h.update(block)
            assert h.hexdigest() == row['expected'], 'Pinned weight mismatch: ' + str(target)
            checked.append(row['file'])
        (shared / 'weights.json').write_text(json.dumps({'path': str(weights), 'repo': manifest['repo'],
            'revision': manifest['revision'], 'verified_files': checked, 'complete': True}, indent=2))
        return
    proof = json.loads((shared / 'weights.json').read_text())
    assert proof['complete']
    weights_root = Path(proof['path']).resolve()
    for row in plan['models'][a.precision]['files']:
        target = weights_root / row['file']
        assert target.is_file() and target.stat().st_size == row['bytes'], str(target)
        assert target.resolve().is_relative_to(weights_root), 'Weight target escapes read-only container mount: ' + str(target)
    args = ['run', '--rm', '--init', '--name', name, '--gpus', 'all', '--network', 'host', '--ipc', 'host',
            '--ulimit', 'memlock=-1', '--ulimit', 'stack=67108864', '-v', proof['path'] + ':/weights:ro',
            '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1']
    if a.precision == 'bf16':
        compat = local / 'efa-compat'; compat.mkdir(exist_ok=True)
        for lib in ('libefa.so.1', 'libibverbs.so.1', 'libnl-3.so.200', 'libnl-route-3.so.200'):
            shutil.copyfile(Path('/usr/lib/x86_64-linux-gnu') / lib, compat / lib)
        ip = socket.gethostname().removeprefix('ip-').replace('-', '.')
        interfaces = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr', 'show'], text=True))
        iface = next(r['ifname'] for r in interfaces if any(v.get('local') == ip for v in r.get('addr_info', [])))
        args += ['-v', '/opt/amazon:/opt/amazon:ro', '-v', str(compat) + ':/host-efa:ro',
                 '-v', '/usr/lib/x86_64-linux-gnu/libibverbs:/usr/lib/x86_64-linux-gnu/libibverbs:ro',
                 '-v', '/etc/libibverbs.d:/etc/libibverbs.d:ro',
                 '-e', 'LD_LIBRARY_PATH=/host-efa:/opt/amazon/ofi-nccl/lib:/opt/amazon/efa/lib:/usr/local/cuda/lib64:/usr/local/lib',
                 '-e', 'FI_PROVIDER=efa', '-e', 'FI_EFA_FORK_SAFE=1', '-e', 'FI_EFA_USE_HUGE_PAGE=0',
                 '-e', 'OFI_NCCL_FORCE_NUM_RAILS=1', '-e', 'NCCL_SOCKET_IFNAME=' + iface,
                 '-e', 'GLOO_SOCKET_IFNAME=' + iface]
        for device in sorted(Path('/dev/infiniband').iterdir()):
            args += ['--device=' + str(device)]
    size = '8' if a.precision == 'nvfp4' else '16'
    model = 'muse-spark-open-' + a.precision
    server = ['--model-path', '/weights', '--served-model-name', model, '--tp-size', size, '--ep-size', size,
              '--host', '0.0.0.0', '--port', '31420', '--context-length', '1048576',
              '--max-running-requests', str(plan['server_cap']), '--kv-cache-dtype', 'fp8_e4m3',
              '--reasoning-parser', 'muse', '--tool-call-parser', 'muse', '--attention-backend', 'fa3',
              '--enable-metrics', '--enable-cache-report', '--stream-interval', '1', '--mm-feature-transport', 'cpu']
    if a.precision == 'nvfp4':
        server += ['--quantization', 'modelopt_fp4', '--moe-runner-backend', 'marlin', '--mem-fraction-static', '0.9']
    else:
        server += ['--dtype', 'bfloat16', '--mem-fraction-static', '0.88', '--nnodes', '2',
                   '--cuda-graph-backend-prefill', 'disabled',
                   '--node-rank', str(rank), '--dist-init-addr', hosts[0].removeprefix('ip-').replace('-', '.') + ':31460']
    if not a.cache:
        server += ['--disable-radix-cache']
    if a.speculative != 'off':
        assert a.speculative == 'NGRAM'
        server += ['--speculative-algorithm', 'NGRAM', '--speculative-num-draft-tokens', '8']
    if a.paired_graphs:
        # Paired controls use the same graph sizes. Eight verify tokens x 256
        # graph slots previously allocated an 8 GiB FA3 page table and failed.
        server += ['--cuda-graph-config', '{"decode":{"max_bs":32},"prefill":{"backend":"disabled"}}']
    cmd, env = docker(*args, '--entrypoint', 'python', IMAGE, '-m', 'sglang.launch_server', *server)
    phase = ('cache-on' if a.cache else 'cache-off') + '-' + a.speculative
    (shared / (phase + '-command.json')).write_text(json.dumps(cmd, indent=2))
    process = subprocess.Popen(cmd, env=env)
    def interrupted(*_):
        raise KeyboardInterrupt('Slurm termination')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        raise SystemExit(process.wait())
    finally:
        stop, stop_env = docker('stop', '-t', '20', name)
        subprocess.run(stop, env=stop_env, timeout=40)
        if process.poll() is None:
            process.terminate()


if __name__ == '__main__':
    main()
