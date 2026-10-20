#!/usr/bin/env python3
"""Check the extra Muse endpoint and preserve its reasoning probe."""

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path


STATE = Path('/fsx/home/zhiyuan/.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/replicas-extra-20261020')
MODEL = 'muse-spark-open-nvfp4'


def main():
    assert len(sys.argv) == 2 and sys.argv[1] in ('2869', '2899')
    directory = STATE / sys.argv[1]
    for _ in range(720):
        if (directory / 'endpoint-ready.json').exists():
            break
        time.sleep(10)
    else:
        raise RuntimeError('Muse endpoint did not become ready within two hours')
    proof = json.loads((directory / 'endpoint-ready.json').read_text())
    assert proof['model'] == MODEL and proof['precision'] == 'NVFP4'
    endpoint = proof['api_base']
    body = {
        'model': MODEL, 'messages': [{'role': 'user', 'content': 'What is 2 + 2? Answer briefly.'}],
        'max_tokens': 512, 'temperature': 1.0, 'top_p': 1.0, 'top_k': -1,
        'chat_template_kwargs': {'reasoning_effort': 'xhigh'},
    }
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(endpoint + '/chat/completions',
                                     data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer EMPTY'})
    for attempt in range(12):
        try:
            with opener.open(request, timeout=300) as response:
                raw = json.load(response)
            break
        except OSError:
            if attempt == 11:
                raise
            time.sleep(15)
    assert raw['model'] == MODEL
    assert len(raw['choices']) == 1
    reasoning = raw['choices'][0]['message'].get('reasoning_content')
    assert isinstance(reasoning, str) and reasoning.strip(), 'No thinking in Muse preflight response'
    result = {'utc': time.time(), 'allocation': int(sys.argv[1]),
              'endpoint_ready': str(directory / 'endpoint-ready.json'),
              'request': body, 'response': raw,
              'response_sha256': hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
              'nonempty_reasoning_content': True}
    output = directory / 'reasoning-preflight.json'
    assert not output.exists(), 'Preflight already recorded; reconcile before repeating'
    temporary = directory / 'reasoning-preflight.json.tmp'
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(output)
    print(json.dumps({'allocation': int(sys.argv[1]), 'model': raw['model'],
                      'reasoning_characters': len(reasoning),
                      'finish_reason': raw['choices'][0].get('finish_reason')}))


if __name__ == '__main__':
    main()
