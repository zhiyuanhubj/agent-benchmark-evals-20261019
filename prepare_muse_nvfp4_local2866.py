#!/usr/bin/env python3
"""Verify the original Muse node before routing untouched exact TB2.1 batches."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

HOME = Path('/fsx/home/zhiyuan')
BASE = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = BASE / 'muse_nvfp4'
STATE = WORK / 'state'
READY = STATE / 'extra_gpu/2866-ready.json'
ENDPOINT = 'http://10.1.95.27:31320/v1'
SERVICE = 'muse-review-serve-2866-reassigned-20261018.service'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


allocation = subprocess.check_output(['squeue', '-h', '-j', '2866', '-o', '%T|%N'], text=True).strip()
assert allocation == 'RUNNING|ip-10-1-95-27', allocation
assert subprocess.check_output(['systemctl', '--user', 'is-active', SERVICE], text=True).strip() == 'active'
opener = build_opener(ProxyHandler({}))
with opener.open(ENDPOINT + '/models', timeout=10) as response:
    models = json.load(response)
assert any(row.get('id') == 'muse-spark-open-nvfp4' for row in models.get('data', []))
plan = json.loads((STATE / 'completion-2866-plan.json').read_text())
for batch in ('b07', 'b08'):
    source = WORK / f'configs/r2-completion-2866-{batch}.json'
    row, = [item for item in plan['configurations'] if item['path'] == str(source)]
    config = json.loads(source.read_text())
    assert row['round'] == 2 and row['sha256'] == digest(source)
    assert config['agents'][0]['kwargs']['api_base'] == ENDPOINT
    assert config['retry']['max_retries'] == 0 and config['n_attempts'] == 1
    assert not (BASE / 'results/muse_nvfp4' / row['job_name']).exists()
    assert not (STATE / f'{source.stem}-extra-owner.json').exists()
    assert not (STATE / 'future-routes' / f'{source.stem}-local-started.json').exists()

proof = dict(
    utc=datetime.now(timezone.utc).timestamp(),
    job=2866, phase='ready', endpoint=ENDPOINT,
    model='muse-spark-open-nvfp4', model_check=models,
    service_unit=SERVICE, gpu_allocation='RUNNING|ip-10-1-95-27',
    claimed_round1_batches=[],
    purpose='Route untouched exact-image TB2.1 round-2/3 batches to the already-running original Muse NVFP4 model node, with atomic disjoint ownership.',
)
READY.parent.mkdir(parents=True, exist_ok=True)
if READY.exists():
    existing = json.loads(READY.read_text())
    assert {k: v for k, v in existing.items() if k != 'utc'} == {k: v for k, v in proof.items() if k != 'utc'}
else:
    READY.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(dict(ready=str(READY), sha256=digest(READY))))
