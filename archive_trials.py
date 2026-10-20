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
OPUS_REVIEW = BASE / '.private/opus47_review_20261020'

GROUPS = {
    **{f'muse_pro_shard{i}': [M / f'shard{i}/results/muse-pro'] for i in range(4)},
    **{f'muse_harbor_shard{i}': [M / f'shard{i}/results'] for i in range(4)},
    'muse_deep_round3_remainder': [M / 'remaining_deep3_2812_20261018/results'],
    'muse_deep_canonical_3round': [M / 'remaining_deep3_2812_20261018/state/three-round-completion-audit.json'],
    'muse_review': [*(M / 'review_bench_20261018/swe_review' / split / 'results' for split in ('glm5_500', 'qwen3_coder_30b_500', 'qwen3_30b_instruct2507_500')), M / 'review_bench_20261018/review_recovery_20261018/results'],
    'muse_review_full_io': [*(M / 'review_bench_20261018/swe_review' / split / 'results' for split in ('glm5_500', 'qwen3_coder_30b_500', 'qwen3_30b_instruct2507_500')), M / 'review_bench_20261018/review_recovery_20261018/results'],
    'muse_review_verifier': [*(M / 'review_bench_20261018/swe_review' / split / 'results' for split in ('glm5_500', 'qwen3_coder_30b_500', 'qwen3_30b_instruct2507_500')), M / 'review_bench_20261018/review_recovery_20261018/results'],
    'muse_swr_raw': [M / 'review_bench_20261018/swrbench/raw_responses', M / 'review_bench_20261018/swrbench/judge_raw_responses'],
    'muse_tb_recovery': [M / 'infra_repair', M / 'review_bench_20261018/tb_remaining_after_swr/results'],
    'beam_legacy': [B / 'legacy_bench_20261018'],
    'beam_exact_tb': [B / 'tb_v1_exact_images_20261019/results/beam_bf16'],
    'beam_review': [B / 'review_bench/swe_review', B / 'review_bench/queue/results'],
    'beam_review_full_io': [B / 'review_bench/swe_review', B / 'review_bench/queue/results'],
    'beam_review_verifier': [B / 'review_bench/swe_review', B / 'review_bench/queue/results'],
    'muse_review_revision_inputs': [*(M / 'review_bench_20261018/revision/prepared' / split
                                      for split in ('glm5_500', 'qwen3_coder_30b_500', 'qwen3_30b_instruct2507_500')),
                                    M / 'review_bench_20261018/revision/generation/qwen3_coder_30b_500/gateway-recovery-20261020/queue',
                                    M / 'review_bench_20261018/revision/generation/qwen3_30b_instruct2507_500/gateway-recovery-20261020/queue'],
    'beam_review_revision_inputs': [*(B / 'review_bench/revision/prepared' / split
                                      for split in ('glm5_500', 'qwen3_coder_30b_500', 'qwen3_30b_instruct2507_500')),
                                    B / 'review_bench/revision/generation/qwen3_coder_30b_500/gateway-recovery-20261020/queue',
                                    B / 'review_bench/revision/generation/qwen3_coder_30b_500/gateway-portfix-20261020/queue',
                                    B / 'review_bench/revision/generation/qwen3_30b_instruct2507_500/gateway-recovery-20261020/queue'],
    'muse_revision_review_full_io': [*(M / 'review_bench_20261018/revision/generation' / split / 'queue/results'
                                       for split in ('glm5_500', 'qwen3_coder_30b_500', 'qwen3_30b_instruct2507_500')),
                                     M / 'review_bench_20261018/revision/generation/qwen3_coder_30b_500/gateway-recovery-20261020/queue/results',
                                     M / 'review_bench_20261018/revision/generation/qwen3_30b_instruct2507_500/gateway-recovery-20261020/queue/results'],
    'beam_revision_review_full_io': [*(B / 'review_bench/revision/generation' / split / 'queue/results'
                                       for split in ('glm5_500', 'qwen3_coder_30b_500', 'qwen3_30b_instruct2507_500')),
                                     B / 'review_bench/revision/generation/qwen3_coder_30b_500/gateway-recovery-20261020/queue/results',
                                     B / 'review_bench/revision/generation/qwen3_coder_30b_500/gateway-portfix-20261020/queue/results',
                                     B / 'review_bench/revision/generation/qwen3_30b_instruct2507_500/gateway-recovery-20261020/queue/results'],
    'beam_swr_raw': [B / 'review_bench/swrbench/raw_responses', B / 'review_bench/swrbench/judge_raw_responses'],
    'opus47_legacy': [O],
    'opus47_exact_tb': [B / 'tb_v1_exact_images_20261019/results/opus47'],
    'opus47_review_inputs': [OPUS_REVIEW / 'configs',
                             *(M / 'review_bench_20261018/swe_review' / split / 'tasks'
                               for split in ('glm5_500', 'qwen3_coder_30b_500',
                                             'qwen3_30b_instruct2507_500'))],
    'opus47_review_full_io': [*(OPUS_REVIEW / 'swe_review' / split / 'results'
                                for split in ('glm5_500', 'qwen3_coder_30b_500',
                                              'qwen3_30b_instruct2507_500'))],
    'muse_exact_tb': [B / 'tb_v1_exact_images_20261019/results/muse_nvfp4'],
    'muse_bf16': [BF / 'legacy_bench/pro-results', BF / 'legacy_bench/tb-results', BF / 'legacy_bench/deep-results', BF / 'review_bench/swe_review', BF / 'review_bench/queue/results'],
    'muse_bf16_swr': [BF / 'review_bench/swrbench', BASE / 'bench/code-review-eval/data/repos/swrbench/data'],
    'muse_bf16_review_inputs': [BF / 'review_bench/queue'],
}

def include(path, root, group):
    rel = path.relative_to(root)
    if group == 'opus47_review_inputs':
        if root.name == 'configs':
            return len(rel.parts) == 1 and path.suffix == '.json'
        visible = {'task.toml', 'instruction.md', 'environment/Dockerfile',
                   'environment/data/problem_statement.txt',
                   'environment/data/summary.json', 'environment/data/predicted.json'}
        return len(rel.parts) >= 2 and '/'.join(rel.parts[1:]) in visible
    if group.endswith('review_revision_inputs'):
        parts = rel.parts
        if root.name == 'queue':
            return ((path.name in ('queue-plan.json', 'queue-exit.json', 'resume-audit.json')
                     or path.name.startswith('queue-exit-pre-resume-'))
                    and path.suffix == '.json' and len(parts) == 1) or (
                parts[0] in ('task-receipts', 'images', 'configs', 'claims')
                and path.suffix == '.json')
        if path.name == 'receipt.json' and len(parts) == 1:
            return True
        visible = {'task.toml', 'instruction.md', 'environment/Dockerfile',
                   'environment/data/problem_statement.txt',
                   'environment/data/summary.json', 'environment/data/predicted.json'}
        return len(parts) >= 3 and parts[0] == 'tasks' and '/'.join(parts[2:]) in visible
    if group.endswith('revision_review_full_io') and path.name == 'model-connectivity.json':
        return True
    if group.endswith('revision_review_full_io') and path.name == 'model.patch' and 'agent' in rel.parts:
        return True
    if group == 'muse_bf16_review_inputs':
        parts = rel.parts
        if path.name == 'queue-plan.json' and len(parts) == 1:
            return True
        if parts[0] == 'tasks':
            visible = {
                'task.toml', 'instruction.md', 'environment/Dockerfile',
                'environment/data/problem_statement.txt',
                'environment/data/summary.json', 'environment/data/predicted.json',
            }
            return len(parts) >= 4 and '/'.join(parts[3:]) in visible
        return parts[0] in ('task-receipts', 'images', 'configs', 'claims') and path.suffix == '.json'
    if group == 'muse_bf16_swr':
        if root == BASE / 'bench/code-review-eval/data/repos/swrbench/data':
            return path.name == 'swr_datasets_d5c5.jsonl'
        return (path.name in ('generation.jsonl', 'evaluation-gpt-5.5.json.tmp.jsonl',
                             'evaluation-gpt-5.5.json', 'launch.json',
                             'controller-complete.json', 'judge-state.json',
                             'completion-audit-current.json', 'failures.json')
                or ('raw_responses' in rel.parts and path.suffix == '.json')
                or ('judge_raw_responses' in rel.parts and path.suffix == '.json'))
    verifier_file = 'verifier' in rel.parts and path.name in ('review_report.json', 'report.json', 'reward.txt', 'test-stdout.txt')
    if group.endswith('review_verifier'):
        return verifier_file
    if group.endswith('review_full_io') and verifier_file:
        return True
    if group.endswith('_swr_raw'):
        return path.suffix == '.json'
    if group.startswith('muse_harbor_shard') and 'muse-pro' in rel.parts:
        return False
    if group == 'opus47_legacy' and not any(x in rel.parts for x in ('pro-results', 'tb-results', 'deep-results', 'api_archive')):
        return False
    if group == 'beam_legacy' and not any(x in rel.parts for x in ('pro-results', 'tb-results', 'deep-results', 'results', 'remaining_pro', 'remaining_tb', 'remaining_deep')):
        return False
    parts = rel.parts
    if path.name in ('result.json', 'task.json', 'config.json', 'trajectory.json', 'exception.txt', 'trial.log', 'openhands_sdk.txt'):
        return True
    if group in ('beam_legacy', 'muse_bf16') and path.name == 'mini-swe-agent.trajectory.json':
        # Harbor's generic trajectory omits reasoning_content for DeepSWE;
        # the native mini-swe-agent trajectory contains the returned thinking.
        # Active files can be rewritten; archive the stable terminal copy.
        result = path.parent.parent / 'result.json'
        if not result.is_file():
            return False
        try:
            return bool(json.loads(result.read_text()).get('finished_at'))
        except json.JSONDecodeError:
            return False
    if 'raw_responses' in parts and path.suffix == '.json':
        return True
    if 'completions' in parts and path.suffix == '.json':
        return True
    if group == 'opus47_legacy' and 'api_archive' in parts and path.suffix == '.json':
        return True
    return False

def iter_files(group):
    seen = set()
    if group == 'muse_deep_canonical_3round':
        audit = json.loads(GROUPS[group][0].read_text())
        for rnd in audit['rounds']:
            for row in rnd['rows'].values():
                result = Path(row['result'])
                if not result.exists():
                    raise FileNotFoundError(result)
                for directory, dirs, names in os.walk(result.parent):
                    dirs[:] = [d for d in dirs if d not in ('artifacts', 'verifier', 'sandbox')]
                    for name in names:
                        path = Path(directory) / name
                        if path.is_file() and not path.is_symlink() and include(path, result.parent, group) and path not in seen:
                            seen.add(path)
                            yield path
        return
    for root in GROUPS[group]:
        if not root.exists():
            continue
        for directory, dirs, names in os.walk(root):
            excluded = {'.git', '__pycache__', '.venv', 'node_modules', 'sandbox', 'artifacts'}
            if group in ('muse_bf16_review_inputs', 'opus47_review_inputs'):
                excluded.update({'solution', 'tests', 'results'})
            if group.endswith('review_revision_inputs'):
                excluded.update({'solution', 'tests', 'results', 'verifier', 'agent'})
            if not (group.endswith('review_verifier') or group.endswith('review_full_io')):
                excluded.add('verifier')
            if group.endswith('review_verifier'):
                excluded.update({'agent', 'completions', 'logs'})
            dirs[:] = [d for d in dirs if d not in excluded]
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
                category = 'judge_raw_response.json' if 'judge_raw_responses' in path.parts else ('raw_response.json' if 'raw_responses' in path.parts else ('completion.json' if 'completions' in path.parts else ('api_archive.json' if 'api_archive' in path.parts else path.name)))
                counts[category] = counts.get(category, 0) + 1
                if group in ('muse_bf16_review_inputs', 'opus47_review_inputs') or group.endswith('review_revision_inputs'):
                    input_count += 1
                elif group == 'muse_bf16_swr':
                    input_count += path.name in ('swr_datasets_d5c5.jsonl', 'launch.json')
                    output_count += path.name in ('generation.jsonl',
                                                  'evaluation-gpt-5.5.json.tmp.jsonl',
                                                  'evaluation-gpt-5.5.json')
                else:
                    input_count += path.name in ('task.json', 'config.json')
                    output_count += path.name in ('result.json', 'trajectory.json', 'trial.log')
                raw_count += 'raw_responses' in path.parts or 'judge_raw_responses' in path.parts or 'completions' in path.parts
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
        'scope': ('Exact official SWE-Review model-visible task cards and frozen Opus 4.7 review configs. Hidden solution and tests, credentials, model weights and outputs are excluded; outputs are archived separately.'
                  if group == 'opus47_review_inputs' else
                  'Original-generator SWE-Review revision task instructions, task cards, Dockerfiles and public model-visible task data, plus canonical preparation and isolated gateway recovery queue receipts. Hidden solution/ and tests/ directories, credentials, model weights and results are excluded; results are archived separately.'
                  if group.endswith('review_revision_inputs') else
                  'Original-generator revision native I/O. Original host-IP and Beam Coder wrong-port trials that failed before any model response are preserved as infrastructure evidence; only the separate corrected gateway queue paths are eligible for RRR scoring. Includes trajectories, completions, native verifier results, and model connectivity receipts. Excludes credentials, weights, caches and hidden solution files.'
                  if group.endswith('revision_review_full_io') else
                  'Model-visible BF16 SWE-Review task instructions, task cards, Dockerfiles and public task data, plus queue/config/claim/image receipts. Hidden solution/ and tests/ directories, credentials, model weights and results are excluded; results are archived separately.'
                  if group == 'muse_bf16_review_inputs' else
                  'The exact 1000-item SWRBench source dataset, launch config, live generated reviews, GPT-5.5 judge records and raw responses present at snapshot time; later deltas replace growing JSONL files. Excludes credentials and model weights.'
                  if group == 'muse_bf16_swr' else
                  'Native task/config inputs, result outputs, trajectories, raw API responses and trial logs present at snapshot time. Excludes model weights, Docker images, caches, artifacts, sandbox and verifier internals.'),
    }
    out = HERE / 'input_output/archive_manifests' / f'{group}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: manifest[k] for k in ('group', 'archive_name', 'archive_size_bytes', 'archive_sha256', 'file_count', 'input_file_count', 'output_file_count', 'raw_response_count')}))

if __name__ == '__main__':
    main()
