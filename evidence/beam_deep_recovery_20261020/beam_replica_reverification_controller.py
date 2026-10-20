"""Repeat full Beam conformance after one stochastic prior-thinking recall miss."""

import fcntl
import hashlib
import json
import subprocess
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BEAM = ROOT.parent
NODE = ROOT / 'allocation-2888-rank-0'
ENDPOINT = 'http://10.1.108.251:31328/v1'
READY = NODE / 'serving-conformance-ready.json'
IMAGE = 'lmsysorg/sglang@sha256:0ea912aadc3d7827858de9aa5a312c4d51c254e7dbe670dbbe8181895b92071d'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


with (NODE / 'conformance-retry1.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert not READY.exists()
    assert not (NODE / 'conformance-retry1-claim.json').exists()
    assert json.loads((NODE / 'conformance-exit.json').read_text())['returncode'] == 1
    first = (NODE / 'conformance.log').read_text()
    assert first.count(' PASSED') == 132 and first.count(' FAILED') == 1
    assert "Expected 'marigold'" in first and "got 'Nebula'" in first
    assert 'streaming-prior_turn_reasoning_is_available] PASSED' in first
    assert json.loads((ROOT / 'allocation-2887-rank-0/conformance-exit.json').read_text())['returncode'] == 0
    launch = json.loads((NODE / 'serve-launch.json').read_text())
    assert launch['revision'] == '78f8f654d40a40919b8e9954b40dd879ecb9a692'
    assert launch['precision'] == 'BF16' and launch['image_digest'] == IMAGE
    verified = json.loads((NODE / 'beam-verification.json').read_text())
    assert verified['complete'] and verified['revision'] == launch['revision']
    check = subprocess.run(['/usr/local/bin/srun', '--jobid=2888', '--overlap', '--gres=none',
                            '-N1', '-n1', '-c1', '--immediate=10', 'docker', 'inspect',
                            '--format', '{{.State.Running}}', 'zhiyuan-beam-bf16-2888'],
                           capture_output=True, text=True, timeout=35, check=True)
    assert check.stdout.strip() == 'true'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(ENDPOINT + '/models', timeout=20) as response:
        models = json.load(response)['data']
    assert any(model['id'] == 'Beam-1.0-501B-A23B' for model in models)
    (NODE / 'conformance-retry1-claim.json').write_text(json.dumps({
        'utc': time.time(), 'first_result': '132/133',
        'first_failed_case': 'non_streaming-prior_turn_reasoning_is_available',
        'first_failure': "Model returned Nebula instead of supplied prior reasoning codeword marigold; streaming version passed",
        'first_log_sha256': sha(NODE / 'conformance.log'),
        'pinned_launch_sha256': sha(NODE / 'serve-launch.json'),
        'pinned_verification_sha256': sha(NODE / 'beam-verification.json'),
        'model_endpoint': ENDPOINT,
        'policy': 'Repeat all 133 original compatibility tests with unchanged model, runtime, and settings; do not start evaluation until all pass.',
    }, indent=2) + '\n')
    with (NODE / 'conformance-retry1.log').open('a') as log:
        result = subprocess.run([str(BEAM / 'verifier-venv/bin/beam-verifier'), 'verify',
                                 '--base-url', ENDPOINT, '--model-name', 'Beam-1.0-501B-A23B'],
                                cwd=BEAM, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
    (NODE / 'conformance-retry1-exit.json').write_text(json.dumps({
        'utc': time.time(), 'returncode': result.returncode,
        'log_sha256': sha(NODE / 'conformance-retry1.log'),
    }, indent=2) + '\n')
    assert result.returncode == 0, 'Repeated full conformance still failed; preserve both reports'
    READY.write_text(json.dumps({
        'utc': time.time(), 'api_base': ENDPOINT,
        'model': 'reflection/Beam-1.0-501B-A23B',
        'revision': launch['revision'], 'precision': 'BF16', 'image_digest': IMAGE,
        'initial_conformance': '132/133; stochastic codeword recall miss',
        'full_retry_conformance': '133/133',
        'retry_claim': str(NODE / 'conformance-retry1-claim.json'),
        'retry_exit': str(NODE / 'conformance-retry1-exit.json'),
    }, indent=2) + '\n')
    subprocess.run(['/usr/local/bin/srun', '--jobid=2888', '--overlap', '--gres=none',
                    '-N1', '-n1', '-c1', '--immediate=10', 'docker', 'wait',
                    'zhiyuan-beam-bf16-2888'], check=False)
