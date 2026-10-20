"""Freeze the verified 2901 Beam TB round-three handoff evidence."""

import copy
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
NODE = BASE / '.private/beam_20261018/expanded_capacity_20261018/allocation-2901-rank-0'
OUT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


original = ROOT / 'beam/configs/r3.json'
effective = ROOT / 'beam/configs/r3-2901.json'
claim_path = ROOT / 'beam/state/r3-launch.json'
claim = json.loads(claim_path.read_text())
before = json.loads(original.read_text())
after = json.loads(effective.read_text())
assert claim['owner'] == 'beam_exact_round3_2901.py'
assert claim['model_allocation'] == 2901 and claim['cpu_allocation'] == 2919
assert claim['source_config_sha256'] == sha(original)
assert claim['effective_config_sha256'] == sha(effective)
assert len(before['tasks']) == len(after['tasks']) == 89
assert before['retry']['max_retries'] == after['retry']['max_retries'] == 0
assert before['n_concurrent_trials'] == after['n_concurrent_trials'] == 4
assert after['agents'][0]['kwargs']['api_base'] == claim['endpoint']
comparison = copy.deepcopy(after)
comparison['agents'][0]['kwargs']['api_base'] = before['agents'][0]['kwargs']['api_base']
assert comparison == before, 'Only the equivalent pinned replica endpoint may change'
ready = json.loads((NODE / 'serving-conformance-ready.json').read_text())
assert ready['api_base'] == claim['endpoint']
assert ready['revision'] == '78f8f654d40a40919b8e9954b40dd879ecb9a692'
assert claim['replica_ready_sha256'] == sha(NODE / 'serving-conformance-ready.json')
verification = json.loads((NODE / 'beam-verification.json').read_text())
assert verification['complete'] and verification['revision'] == ready['revision']
assert len(verification['verified_files']) == 198
conformance = (NODE / 'conformance.log').read_text()
assert conformance.count(' PASSED') == 133 and conformance.count(' FAILED') == 0
assert json.loads((NODE / 'conformance-exit.json').read_text())['returncode'] == 0
images = json.loads((ROOT / 'allocation-2919/images-ready.json').read_text())
assert images['count'] == 89 and images['all_archive_identities_verified']

sources = {
    'original_r3_config.json': original,
    'effective_r3_config.json': effective,
    'r3_launch_claim.json': claim_path,
    'r1_exit.json': ROOT / 'beam/state/r1-exit.json',
    'r2_launch_claim.json': ROOT / 'beam/state/r2-launch.json',
    'exact_images_ready.json': ROOT / 'allocation-2919/images-ready.json',
    'replica_weights_verification.json': NODE / 'beam-verification.json',
    'replica_conformance.log': NODE / 'conformance.log',
    'replica_conformance_exit.json': NODE / 'conformance-exit.json',
    'replica_serving_ready.json': NODE / 'serving-conformance-ready.json',
}
files = {}
for name, source in sources.items():
    assert source.is_file(), source
    destination = OUT / name
    shutil.copyfile(source, destination)
    assert sha(destination) == sha(source)
    files[name] = {'source': str(source), 'sha256': sha(source),
                   'size_bytes': source.stat().st_size}

manifest = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'model': 'reflection/Beam-1.0-501B-A23B',
    'revision': ready['revision'], 'precision': 'BF16',
    'round': 3, 'expected_tasks': 89,
    'conformance': 'Full 133/133 passed before any round-three trial launched.',
    'protocol': 'Original 89 exact images, task IDs, retry=0, generation and concurrency=4 retained; only the pinned equivalent model endpoint changed.',
    'round_two_owner': '2887 continues round 2; the exclusive r3-launch receipt prevents duplicate round 3.',
    'files': files,
}
(OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'files': len(files), 'conformance': '133/133',
                  'manifest': str(OUT / 'manifest.json')}))
