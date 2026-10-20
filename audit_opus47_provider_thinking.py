#!/usr/bin/env python3
"""Audit thinking preservation in the resumed Opus 4.7 provider archive."""

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path('/fsx/home/zhiyuan')
ARCHIVE = ROOT / 'bench/opus47_full_20261018/api_archive/claude'
OUTPUT = ROOT / 'agent-benchmark-evals-20261019/evidence/opus47_review_provider_thinking_full_20261020.json'
GATEWAY_STARTED_EPOCH = 1792534387.0
EXPECTED_THINKING = {'type': 'adaptive', 'display': 'summarized'}
EXPECTED_EFFORT = {'effort': 'high'}


def raw_thinking_count(events):
    count = 0
    for event in events:
        for line in event.get('raw_stream_lines', []):
            if not line.startswith('data: '):
                continue
            try:
                chunk = json.loads(line[6:])
            except json.JSONDecodeError:
                continue  # Includes the normal [DONE] stream marker.
            for choice in chunk.get('choices', []):
                delta = choice.get('delta') or {}
                provider = delta.get('provider_specific_fields') or {}
                if (delta.get('thinking_blocks') or delta.get('reasoning_content')
                        or provider.get('thinking_blocks')):
                    count += 1
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--since-epoch', type=float, default=GATEWAY_STARTED_EPOCH)
    parser.add_argument('--until-epoch', type=float, default=time.time())
    args = parser.parse_args()
    statuses = Counter()
    presence = Counter()
    config_mismatch = []
    raw_without_assembled = []
    assembled_without_raw = []
    read_errors = []
    digest = hashlib.sha256()
    count = 0
    raw_thinking_lines = 0
    assembled_blocks = 0
    newest_started = 0.0
    for entry in sorted(os.scandir(ARCHIVE), key=lambda item: item.name):
        if not entry.name.endswith('.json') or not args.since_epoch <= entry.stat().st_mtime <= args.until_epoch:
            continue
        try:
            data = Path(entry.path).read_bytes()
            record = json.loads(data)
        except (OSError, ValueError) as error:
            read_errors.append({'file': entry.name, 'error': str(error)})
            continue
        started = float(record.get('started') or 0)
        if not args.since_epoch <= started <= args.until_epoch:
            continue
        count += 1
        newest_started = max(newest_started, started)
        digest.update(entry.name.encode() + b' ' + hashlib.sha256(data).hexdigest().encode() + b'\n')
        statuses[str(record.get('status'))] += 1
        request = record.get('request') or {}
        if request.get('thinking') != EXPECTED_THINKING or request.get('output_config') != EXPECTED_EFFORT:
            config_mismatch.append(entry.name)
        choices = (record.get('response') or {}).get('choices') or []
        message = (choices[0].get('message') or {}) if choices else {}
        blocks = message.get('thinking_blocks') or []
        reasoning = message.get('reasoning_content') or ''
        raw_count = raw_thinking_count(record.get('events') or [])
        raw_thinking_lines += raw_count
        assembled_blocks += len(blocks)
        raw_present = raw_count > 0
        assembled_present = bool(blocks or reasoning)
        presence[f'raw={raw_present},assembled={assembled_present}'] += 1
        if raw_present and not assembled_present:
            raw_without_assembled.append(entry.name)
        if assembled_present and not raw_present:
            assembled_without_raw.append(entry.name)

    result = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Provider requests archived by the restored Opus 4.7 gateway for SWE-Review; request/response preservation only, not a trajectory or reward-hacking audit.',
        'archive_directory': str(ARCHIVE),
        'since_epoch_inclusive': args.since_epoch,
        'until_epoch_inclusive': args.until_epoch,
        'included_provider_requests': count,
        'member_name_and_sha256_digest': digest.hexdigest(),
        'http_status_counts': dict(sorted(statuses.items())),
        'expected_request_thinking': EXPECTED_THINKING,
        'expected_request_output_config': EXPECTED_EFFORT,
        'request_config_mismatches': config_mismatch,
        'raw_and_assembled_presence_counts': dict(sorted(presence.items())),
        'raw_stream_thinking_delta_count': raw_thinking_lines,
        'assembled_thinking_block_count': assembled_blocks,
        'raw_thinking_without_assembled_response': raw_without_assembled,
        'assembled_thinking_without_raw_stream': assembled_without_raw,
        'read_errors': read_errors,
        'newest_provider_started_epoch': newest_started,
        'qualification': ('thinking_preservation_verified_for_this_provider_snapshot'
                          if count and not config_mismatch and not raw_without_assembled
                          and not assembled_without_raw and not read_errors
                          and statuses == {'200': count} else 'needs_review'),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    os.replace(temporary, OUTPUT)
    print(json.dumps({key: result[key] for key in ('generated_utc', 'included_provider_requests',
          'http_status_counts', 'raw_and_assembled_presence_counts', 'qualification')}, ensure_ascii=False))
    if result['qualification'] != 'thinking_preservation_verified_for_this_provider_snapshot':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
