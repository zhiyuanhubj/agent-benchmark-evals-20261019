#!/usr/bin/env python3
"""Freeze one interrupted Opus SWE-Review task for a separate recovery draw."""

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from harbor.models.job.config import JobConfig


HOME = Path('/fsx/home/zhiyuan')
ROOT = HOME / 'agent-benchmark-evals-20261019'
PRIVATE = HOME / '.private/opus47_review_20261020'
SOURCE_CONFIG = PRIVATE / 'configs/qwen3_30b_instruct2507_500.json'
SOURCE_JOB = PRIVATE / 'swe_review/qwen3_30b_instruct2507_500/results/opus47-swe-review-qwen3_30b_instruct2507_500-r1'
TRIAL_NAME = 'scikit-learn__scikit-learn-26194__kAYQa3c'
TASK_NAME = 'scikit-learn__scikit-learn-26194'
JOB_NAME = 'opus47-swe-review-instruct-cancelled-recovery-20261020'
RECOVERY = PRIVATE / 'cancelled_recovery_20261020'
CONFIG = RECOVERY / 'config.json'
CLAIM = ROOT / 'evidence/opus47_review_instruct_cancelled_recovery_claim.json'
METRIC_PLAN = HOME / '.private/muse_spark_open_20261016/review_bench_20261018/revision_capacity_20261018/revision-execution-plan.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    assert not CONFIG.exists() and not CLAIM.exists(), 'Recovery already prepared'
    source = json.loads(SOURCE_CONFIG.read_text())
    base = source['config']
    original = JobConfig.model_validate(base)
    assert source['regrade'] is False
    assert original.job_name == 'opus47-swe-review-qwen3_30b_instruct2507_500-r1'
    assert original.n_attempts == 1 and original.n_concurrent_trials == 2
    assert original.agents[0].model_name == 'openai/claude-opus-4-7'
    assert original.agents[0].kwargs['send_reasoning_content_models'] == ['claude-opus-4-7']
    assert original.agents[0].env['LLM_BASE_URL'] == 'http://10.1.115.182:31352/v1'
    assert len(original.datasets) == 1 and not original.tasks
    task = Path(original.datasets[0].path) / TASK_NAME
    assert task.is_dir() and (task / 'task.toml').is_file()
    metric = json.loads(METRIC_PLAN.read_text())['splits']['qwen3_30b_instruct2507_500']
    assert TASK_NAME in metric['expected_ids'] and len(metric['expected_ids']) == 422

    job_result = json.loads((SOURCE_JOB / 'result.json').read_text())
    assert job_result['finished_at'] is not None
    assert job_result['stats']['n_completed_trials'] == 422
    trial = SOURCE_JOB / TRIAL_NAME
    result_path = trial / 'result.json'
    result = json.loads(result_path.read_text())
    assert Path(result['task_id']['path']) == task
    assert result['config']['agent']['model_name'] == original.agents[0].model_name
    assert result['exception_info']['exception_type'] == 'CancelledError'
    assert result['verifier'] is None and result['verifier_result'] is None
    assert not (trial / 'verifier/review_report.json').exists()
    assert not (trial / 'agent/trajectory.json').exists()
    completions = sorted((trial / 'agent/completions').glob('*.json'))
    assert completions, 'This was a model-started interruption, not a pre-model failure'
    assert not (Path(original.jobs_dir) / JOB_NAME).exists()

    replacement = copy.deepcopy(source)
    config = replacement['config']
    config['job_name'] = JOB_NAME
    config['n_concurrent_trials'] = 1
    config['datasets'] = []
    config['tasks'] = [{'path': str(task)}]
    recovered = JobConfig.model_validate(config)
    assert recovered.n_attempts == 1 and len(recovered.tasks) == 1 and not recovered.datasets
    restored = copy.deepcopy(config)
    for field in ('job_name', 'n_concurrent_trials', 'datasets'):
        restored[field] = base[field]
    restored.pop('tasks')
    assert restored == base, 'Unexpected protocol change'

    save_new(CONFIG, replacement)
    claim = {
        'prepared_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Opus 4.7 SWE-Review qwen3_30b_instruct2507_500; one designated replacement for a cancelled model-started trial.',
        'original_job': original.job_name,
        'original_job_result_sha256': sha(SOURCE_JOB / 'result.json'),
        'original_config': str(SOURCE_CONFIG),
        'original_config_sha256': sha(SOURCE_CONFIG),
        'original_trial': str(trial),
        'original_trial_result_sha256': sha(result_path),
        'original_exception': 'CancelledError',
        'original_model_completion_count': len(completions),
        'original_model_completion_hashes': {path.name: sha(path) for path in completions},
        'original_verifier_result': None,
        'original_trajectory': None,
        'task': TASK_NAME,
        'task_toml_sha256': sha(task / 'task.toml'),
        'official_metric_plan_sha256': sha(METRIC_PLAN),
        'replacement_job': JOB_NAME,
        'replacement_config': str(CONFIG),
        'replacement_config_sha256': sha(CONFIG),
        'model_endpoint': original.agents[0].env['LLM_BASE_URL'],
        'thinking_preserved': True,
        'recovery_policy': 'One predeclared replacement draw for an externally cancelled, ungraded task. Keep source completions. Report replacement separately from the original first-attempt split; never select by correctness.',
    }
    save_new(CLAIM, claim)
    print(json.dumps({'claim': str(CLAIM), 'replacement_config': str(CONFIG),
                      'original_model_completion_count': len(completions)}))


if __name__ == '__main__':
    main()
