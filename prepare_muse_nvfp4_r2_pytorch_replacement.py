#!/usr/bin/env python3
"""Declare one separately scored storage-failure replacement on CPU allocation 2922."""
import copy
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
BASE = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
TASK = 'pytorch-model-cli'
JOB = 'muse-nvfp4-tb-v1-exact-r2-storage-replacement-pytorch-model-cli'
SOURCE = BASE / 'muse_nvfp4/configs/r2-completion-2866-b06.json'
CONFIG = BASE / 'muse_nvfp4/configs/r2-storage-replacement-pytorch-model-cli.json'
CLAIM = BASE / 'muse_nvfp4/state/r2-pytorch-model-cli-storage-replacement-claim.json'
EVIDENCE = ROOT / 'evidence/muse_nvfp4_r2_pytorch_model_cli_ungraded.json'
ROUTE = BASE / 'muse_nvfp4/state/future-routes/r2-completion-2866-b06-route.json'
ENDPOINT = 'http://10.1.95.27:31320/v1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_new(path, value):
    serialized = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        assert path.read_text() == serialized, f'Existing declaration changed: {path}'
    else:
        path.write_text(serialized)


evidence = json.loads(EVIDENCE.read_text())
assert evidence['native_verifier_reward'] is None
assert digest(Path(evidence['result_path'])) == evidence['result_sha256']
assert digest(ROUTE) == evidence['route_sha256']
source = json.loads(SOURCE.read_text())
assert source['job_name'] == 'muse-nvfp4-tb-v1-exact-r2-completion-2866-b06'
assert source['agents'][0]['kwargs']['api_base'] == ENDPOINT
assert source['retry']['max_retries'] == 0 and source['n_attempts'] == 1
tasks = [item for item in source['tasks'] if Path(item['path']).name == TASK]
assert len(tasks) == 1
opener = build_opener(ProxyHandler({}))
with opener.open(ENDPOINT + '/models', timeout=10) as response:
    models = json.load(response)
assert any(item.get('id') == 'muse-spark-open-nvfp4' for item in models['data'])
disk = subprocess.run(['/usr/local/bin/srun', '--jobid=2922', '--overlap', '--gres=none',
                       '-N1', '-n1', '-c1', '--immediate=10', 'df', '-Pk', '/opt/sagemaker'],
                      capture_output=True, text=True, timeout=20, check=True)
available_kib = int(disk.stdout.splitlines()[-1].split()[3])
assert available_kib >= 100_000_000, f'CPU host lacks 100 GB Docker headroom: {available_kib} KiB'

replacement = copy.deepcopy(source)
replacement['job_name'] = JOB
replacement['tasks'] = tasks
replacement['n_concurrent_trials'] = 1
save_new(CONFIG, replacement)
assert not (BASE / 'results/muse_nvfp4' / JOB).exists(), 'Storage replacement already started'
claim = dict(
    prepared_utc=datetime.now(timezone.utc).isoformat(),
    scope='One separately declared storage-failure replacement after an ungraded original exact-image TB2.1 round-2 draw.',
    original_result_path=evidence['result_path'], original_result_sha256=evidence['result_sha256'],
    original_ungraded_evidence=str(EVIDENCE), original_ungraded_evidence_sha256=digest(EVIDENCE),
    original_route_path=str(ROUTE), original_route_sha256=digest(ROUTE),
    source_job_config=str(SOURCE), source_job_config_sha256=digest(SOURCE),
    replacement_job_config=str(CONFIG), replacement_job_config_sha256=digest(CONFIG),
    replacement_job_name=JOB, task=TASK, task_toml_sha256=digest(Path(tasks[0]['path']) / 'task.toml'),
    cpu_allocation=2922, cpu_host_available_kib_before_launch=available_kib,
    model_endpoint=ENDPOINT, model_id='muse-spark-open-nvfp4', model_ready_check=models,
    only_changes=['job_name', 'single original task', 'one concurrent trial', 'CPU host 2922 for storage isolation', 'endpoint restored to original NVFP4 service'],
    no_retry=True,
    metric_policy='The original first draw remains ungraded. Preserve both draws. Report the replacement reward separately and, if native-graded, use it at most once in the explicitly labeled repaired-round metric; never select best-of.',
)
save_new(CLAIM, claim)
print(json.dumps(dict(claim=str(CLAIM), config=str(CONFIG), config_sha256=digest(CONFIG),
                      cpu_host_available_kib=available_kib)))
