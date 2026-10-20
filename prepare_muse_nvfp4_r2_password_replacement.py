#!/usr/bin/env python3
"""Prepare one declared infrastructure replacement for an ungraded TB2.1 trial."""
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
BASE = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
TASK = 'password-recovery'
JOB = 'muse-nvfp4-tb-v1-exact-r2-infra-replacement-password-recovery'
CLAIM = BASE / 'muse_nvfp4/state/r2-password-recovery-infra-replacement-claim.json'
CONFIG = BASE / 'muse_nvfp4/configs/r2-infra-replacement-password-recovery.json'
SOURCE = BASE / 'muse_nvfp4/configs/r2-completion-2866-b05.json'
READY = BASE / 'muse_nvfp4/state/reassigned-2867/endpoint-ready.json'
EVIDENCE = ROOT / 'evidence/muse_nvfp4_r2_password_recovery_ungraded.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        assert path.read_text() == serialized, f'Existing claim changed: {path}'
    else:
        path.write_text(serialized)


evidence = json.loads(EVIDENCE.read_text())
original_result = HOME / evidence['result_path']
assert digest(original_result) == evidence['result_sha256']
assert evidence['native_verifier_reward'] is None
source = json.loads(SOURCE.read_text())
assert source['job_name'] == 'muse-nvfp4-tb-v1-exact-r2-completion-2866-b05'
assert source['retry']['max_retries'] == 0 and source['n_attempts'] == 1
tasks = [task for task in source['tasks'] if Path(task['path']).name == TASK]
assert len(tasks) == 1
ready = json.loads(READY.read_text())
assert ready['allocation'] == 2867 and ready['model'] == 'muse-spark-open-nvfp4'
assert ready['api_base'] == 'http://10.1.105.182:31321/v1'

replacement = copy.deepcopy(source)
replacement['job_name'] = JOB
replacement['tasks'] = tasks
replacement['n_concurrent_trials'] = 1
replacement['agents'][0]['kwargs']['api_base'] = ready['api_base']
save_new(CONFIG, replacement)
assert not (BASE / 'results/muse_nvfp4' / JOB).exists(), 'Replacement has already begun'

claim = dict(
    prepared_utc=datetime.now(timezone.utc).isoformat(),
    scope='One declared infrastructure replacement of the original ungraded Muse NVFP4 exact-image TB2.1 round-2 password-recovery attempt.',
    original_result_path=str(original_result), original_result_sha256=digest(original_result),
    original_ungraded_evidence=str(EVIDENCE), original_ungraded_evidence_sha256=digest(EVIDENCE),
    source_job_config=str(SOURCE), source_job_config_sha256=digest(SOURCE),
    replacement_job_config=str(CONFIG), replacement_job_config_sha256=digest(CONFIG),
    replacement_job_name=JOB,
    task=TASK,
    task_toml_sha256=digest(Path(tasks[0]['path']) / 'task.toml'),
    model_ready_proof=str(READY), model_ready_proof_sha256=digest(READY),
    model_endpoint=ready['api_base'],
    only_changes=['job_name', 'single original task', 'one concurrent trial', 'equivalent pinned NVFP4 model replica endpoint'],
    no_retry=True,
    metric_policy='Never count the original ungraded attempt as reward zero or as a success. One replacement attempt is eligible to fill this single missing native grade; preserve both draws and do not select best-of.',
)
save_new(CLAIM, claim)
print(json.dumps(dict(claim=str(CLAIM), config=str(CONFIG), config_sha256=digest(CONFIG))))
