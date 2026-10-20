"""Freeze the exact Beam DeepSWE recovery inputs and conformance provenance."""

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
BEAM = BASE / '.private/beam_20261018'
DEEP = BEAM / 'legacy_bench_20261018/remaining_deep'
NODE = BEAM / 'expanded_capacity_20261018/allocation-2888-rank-0'
OUT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


r2_claim = json.loads((DEEP / 'state/r2-2922-resume-claim.json').read_text())
r3_claim = json.loads((DEEP / 'state/r3-2888-launch.json').read_text())
r2 = DEEP / 'configs/deep-r2.json'
r3_template = DEEP / 'configs/deep-r3.template.json'
r3 = DEEP / 'configs/deep-r3.json'
assert sha(r2) == r2_claim['config_sha256']
assert sha(r3_template) == r3_claim['original_template_sha256']
assert sha(r3) == r3_claim['effective_config_sha256']
original = json.loads(r3_template.read_text())
effective = json.loads(r3.read_text())
assert len(original['config']['tasks']) == len(effective['config']['tasks']) == 113
assert original['config']['n_attempts'] == effective['config']['n_attempts'] == 1
assert effective['config']['n_concurrent_trials'] == 4
effective['config']['n_concurrent_trials'] = original['config']['n_concurrent_trials']
effective['slurm_job'] = original['slurm_job']
assert json.loads(json.dumps(effective).replace('http://10.1.108.251:31328/v1',
                                         'http://10.1.25.253:31328/v1')) == original
first = (NODE / 'conformance.log').read_text()
retry = (NODE / 'conformance-retry1.log').read_text()
assert first.count(' PASSED') == 132 and first.count(' FAILED') == 1
assert retry.count(' PASSED') == 133 and retry.count(' FAILED') == 0
assert json.loads((NODE / 'conformance-exit.json').read_text())['returncode'] == 1
assert json.loads((NODE / 'conformance-retry1-exit.json').read_text())['returncode'] == 0
ready = json.loads((NODE / 'serving-conformance-ready.json').read_text())
assert ready['api_base'] == 'http://10.1.108.251:31328/v1'
assert ready['revision'] == '78f8f654d40a40919b8e9954b40dd879ecb9a692'

sources = {
    'beam_r2_config.json': r2,
    'beam_r3_template.json': r3_template,
    'beam_r3_effective.json': r3,
    'beam_r2_resume_claim.json': DEEP / 'state/r2-2922-resume-claim.json',
    'beam_r2_interrupted_manifest.json': DEEP / 'state/r2-2812-interrupted-original/manifest.json',
    'beam_r3_launch_claim.json': DEEP / 'state/r3-2888-launch.json',
    'beam_r2_resume_controller.py': DEEP / 'resume_r2_on_2922.py',
    'beam_r3_controller.py': DEEP / 'run_r3_on_2888.py',
    'beam_replica_reverification_controller.py': BEAM / 'expanded_capacity_20261018/reverify_2888.py',
    'beam_replica_weights_verification.json': NODE / 'beam-verification.json',
    'beam_replica_launch.json': NODE / 'serve-launch.json',
    'beam_replica_conformance_first.log': NODE / 'conformance.log',
    'beam_replica_conformance_first_exit.json': NODE / 'conformance-exit.json',
    'beam_replica_conformance_retry_claim.json': NODE / 'conformance-retry1-claim.json',
    'beam_replica_conformance_retry.log': NODE / 'conformance-retry1.log',
    'beam_replica_conformance_retry_exit.json': NODE / 'conformance-retry1-exit.json',
    'beam_replica_ready.json': NODE / 'serving-conformance-ready.json',
}
files = {}
for name, source in sources.items():
    destination = OUT / name
    shutil.copyfile(source, destination)
    assert sha(destination) == sha(source)
    files[name] = {'source': str(source), 'sha256': sha(source), 'bytes': source.stat().st_size}

manifest = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'model': 'reflection/Beam-1.0-501B-A23B',
    'revision': ready['revision'], 'precision': 'BF16',
    'round_2': 'Original CPU allocation 2812 ended at 25 terminal tasks; its unfinished trial is preserved and only missing tasks resume on CPU 2922 against Beam 2733.',
    'round_3': 'Previously unstarted 113 tasks use the unchanged source task, image and sampling settings against the pinned 2888 Beam replica; orchestration concurrency is 4.',
    'conformance': 'Initial full test 132/133 with one prior-thinking recall miss; unchanged full repeat 133/133 before launching round 3.',
    'thinking_release_assets': [
        'beam_legacy_delta_20261020T095850Z.tar.zst',
        'muse_bf16_delta_20261020T095921Z.tar.zst',
    ],
    'files': files,
}
(OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'files': len(files), 'conformance': '133/133',
                  'manifest': str(OUT / 'manifest.json')}))
