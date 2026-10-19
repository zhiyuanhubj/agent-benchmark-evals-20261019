#!/usr/bin/env python3
"""Archive native benchmark input/output without weights, caches or credentials."""
import argparse
import hashlib
import json
import os
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
HERE = Path(__file__).resolve().parent
M = BASE / '.private/muse_spark_open_20261016'
B = BASE / '.private/beam_20261018'
O = BASE / 'bench/opus47_full_20261018'
BF = BASE / '.private/muse_bf16_20261018'

GROUPS = {
    **{f'muse_pro_shard{i}': [M / f'shard{i}/results/muse-pro'] for i in range(4)},
    **{f'muse_harbor_shard{i}': [M / f'shard{i}/results'] for i in range(4)},
    'muse_deep_round3_remainder': [M / 'remaining_deep3_2812_20261018/results'],
    'muse_review': [M / 'review_bench_20261018/swe_review'],
    'muse_tb_recovery': [M / 'infra_repair', M / 'review_bench_20261018/tb_remaining_after_swr/results'],
    'beam_legacy': [B / 'legacy_bench_20261018'],
    'beam_exact_tb': [B / 'tb_v1_exact_images_20261019/results/beam_bf16'],
    'beam_review': [B / 'review_bench/swe_review'],
    'opus47_legacy': [O],
    'opus47_exact_tb': [B / 'tb_v1_exact_images_20261019/results/opus47'],
    'muse_exact_tb': [B / 'tb_v1_exact_images_20261019/results/muse_nvfp4'],
    'muse_bf16': [BF / 'legacy_bench/results', BF / 'review_bench'],
}

def include(path, root, group):
    rel = path.relative_to(root)
    if group.startswith('muse_harbor_shard') and 'muse-pro' in rel.parts:
        return False
    if group == 'opus47_legacy' and not any(x in rel.parts for x in ('pro-results', 'tb-results', 'deep-results', 'api_archive')):
        return False
    if group == 'beam_legacy' and not any(x in rel.parts for x in ('pro-results', 'tb-results', 'deep-results', 'results', 'remaining_pro', 'remaining_tb', 'remaining_deep')):
        return False
    parts = rel.parts
    if path.name in ('result.json', 'task.json', 'config.json', 'trajectory.json', 'exception.txt', 'trial.log'):
        return True
    if 'raw_responses' in parts and path.suffix == '.json':
        return True
    if group == 'opus47_legacy' and 'api_archive' in parts and path.suffix == '.json':
        return True
    return False

def iter_files(group):
    seen = set()
    for root in GROUPS[group]:
        if not root.exists():
            continue
        for directory, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', '.venv', 'node_modules', 'sandbox', 'artifacts', 'verifier')]
            for name in names:
                path = Path(directory) / name
                if not path.is_file() or path.is_symlink() or not include(path, root, group):
                    continue
                if path in seen:
                    continue
                seen.add(path)
                yield path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('group', choices=GROUPS)
    args = parser.parse_args()
    group = args.group
    dest_dir = HERE / '.release_assets'
    dest_dir.mkdir(exist_ok=True)
    final = dest_dir / f'{group}.tar.zst'
    temp = dest_dir / f'{group}.tar.zst.tmp'
    if final.exists():
        raise SystemExit(f'Archive already exists: {final}')
    files = sorted(iter_files(group))
    if not files:
        raise SystemExit(f'No input/output files found for {group}')
    proc = subprocess.Popen(['zstd', '-q', '-T2', '-3', '-o', str(temp)], stdin=subprocess.PIPE)
    counts = {}
    input_count = output_count = raw_count = 0
    try:
        with tarfile.open(fileobj=proc.stdin, mode='w|') as tar:
            for path in files:
                arcname = str(path.relative_to(BASE))
                tar.add(str(path), arcname=arcname, recursive=False)
                counts[path.name] = counts.get(path.name, 0) + 1
                input_count += path.name in ('task.json', 'config.json')
                output_count += path.name in ('result.json', 'trajectory.json', 'trial.log')
                raw_count += 'raw_responses' in path.parts
        proc.stdin.close()
        rc = proc.wait()
        if rc:
            raise RuntimeError(f'zstd exited {rc}')
        temp.rename(final)
    except BaseException:
        proc.kill()
        temp.unlink(missing_ok=True)
        raise
    digest = hashlib.file_digest(final.open('rb'), 'sha256').hexdigest()
    manifest = {
        'group': group,
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'archive_name': final.name,
        'archive_size_bytes': final.stat().st_size,
        'archive_sha256': digest,
        'file_count': len(files),
        'input_file_count': input_count,
        'output_file_count': output_count,
        'raw_response_count': raw_count,
        'filename_counts': counts,
        'source_roots': [str(x) for x in GROUPS[group]],
        'scope': 'Native task/config inputs, result outputs, trajectories, raw API responses and trial logs present at snapshot time. Excludes model weights, Docker images, caches, artifacts, sandbox and verifier internals.',
    }
    out = HERE / 'input_output/archive_manifests' / f'{group}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))

if __name__ == '__main__':
    main()
