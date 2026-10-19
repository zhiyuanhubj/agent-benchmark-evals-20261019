#!/usr/bin/env python3
"""Reconcile scored Opus 4.7 TB round-3 thinking with saved provider SSE."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
TRIALS = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/results/opus47/opus47-tb-v1-exact-r3'
ARCHIVE = BASE / 'bench/opus47_full_20261018/api_archive/claude'
OUT = ROOT / 'evidence/opus47_r3_thinking_transport_audit.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stream_evidence(path):
    payload = json.loads(path.read_text())
    reasoning_chars = 0
    thinking_chars = 0
    signed_blocks = 0
    for event in payload.get('events') or []:
        for line in event.get('raw_stream_lines') or []:
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if not data or data == '[DONE]':
                continue
            chunk = json.loads(data)
            for choice in chunk.get('choices') or []:
                delta = choice.get('delta') or {}
                reasoning_chars += len(delta.get('reasoning_content') or '')
                for block in delta.get('thinking_blocks') or []:
                    thinking_chars += len(block.get('thinking') or '')
                    signed_blocks += bool(block.get('signature'))
    return payload, reasoning_chars, thinking_chars, signed_blocks


def main():
    counts = {'scored_tasks': 0, 'raw_responses': 0, 'with_thinking_text': 0,
              'without_text_zero_reasoning_tokens': 0,
              'without_text_positive_reasoning_tokens': 0,
              'without_text_unknown_reasoning_tokens': 0}
    missing = {}
    for trial in TRIALS.iterdir():
        if not trial.is_dir() or not (trial / 'result.json').exists():
            continue
        counts['scored_tasks'] += 1
        for response_path in (trial / 'agent/raw_responses').glob('*.json'):
            response = json.loads(response_path.read_text())
            choices = response.get('choices') or [{}]
            message = choices[0].get('message') or {}
            tokens = (((response.get('usage') or {}).get('completion_tokens_details') or {})
                      .get('reasoning_tokens'))
            text = bool((message.get('reasoning_content') or '').strip()
                        or any((block.get('thinking') or '').strip()
                               for block in (message.get('thinking_blocks') or [])))
            counts['raw_responses'] += 1
            if text:
                counts['with_thinking_text'] += 1
            elif isinstance(tokens, (int, float)) and tokens > 0:
                counts['without_text_positive_reasoning_tokens'] += 1
                assert response['id'] not in missing
                missing[response['id']] = {
                    'task': trial.name, 'reasoning_tokens': tokens,
                    'response_id_sha256': hashlib.sha256(response['id'].encode()).hexdigest(),
                    'raw_response_path': str(response_path.relative_to(BASE)),
                    'raw_response_sha256': digest(response_path),
                    'response_file_mtime': response_path.stat().st_mtime,
                }
            elif tokens == 0:
                counts['without_text_zero_reasoning_tokens'] += 1
            else:
                counts['without_text_unknown_reasoning_tokens'] += 1

    for entry in os.scandir(ARCHIVE):
        if not entry.is_file():
            continue
        stamp = entry.stat().st_mtime
        if not any(abs(stamp - row['response_file_mtime']) < 240 for row in missing.values()):
            continue
        path = Path(entry.path)
        payload = json.loads(path.read_text())
        response_id = (payload.get('response') or {}).get('id')
        if response_id not in missing:
            continue
        row = missing[response_id]
        assert 'provider_archive_path' not in row, response_id
        _, reasoning_chars, thinking_chars, signed_blocks = stream_evidence(path)
        row.update(provider_archive_path=str(path.relative_to(BASE)),
                   provider_archive_sha256=digest(path),
                   provider_status=payload['status'],
                   request_thinking=payload['request'].get('thinking'),
                   request_output_config=payload['request'].get('output_config'),
                   provider_reasoning_text_chars=reasoning_chars,
                   provider_thinking_text_chars=thinking_chars,
                   provider_signed_thinking_blocks=signed_blocks)

    cases = sorted(missing.values(), key=lambda row: row['task'])
    for row in cases:
        assert row.get('provider_archive_path'), row['task']
        assert row['provider_status'] == 200
        assert row['request_thinking'] == {'type': 'adaptive', 'display': 'summarized'}
        assert row['provider_reasoning_text_chars'] == 0
        assert row['provider_thinking_text_chars'] == 0
        assert row['provider_signed_thinking_blocks'] >= 1
        del row['response_file_mtime']
    report = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Currently terminal Opus 4.7 exact-image TB2.1 round-3 trials only.',
        'counts': counts, 'cases': cases,
        'conclusion': 'These positive reasoning-token responses have no thinking text in saved upstream SSE; no text can be recovered. Each upstream response has a signed empty thinking block. The gateway-assembled client JSON did not retain that block. Exclude these replies from full-thinking training export; benchmark rewards are unchanged.',
        'limit': 'This audit does not certify every trajectory as clean or guarantee that all future responses have thinking text.',
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'counts': counts, 'cases': len(cases)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
