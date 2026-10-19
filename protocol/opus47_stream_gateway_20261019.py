"""Keep the provider connection streaming; return complete JSON to Terminus.

This preserves sampling, token budgets, thinking summaries and signatures.
Every provider stream event is retained alongside the assembled response.
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from litellm import ModelResponseStream, stream_chunk_builder
import uvicorn

from settings import ROOT, MODELS

app = FastAPI()
limit = asyncio.Semaphore(12)
client = httpx.AsyncClient(timeout=httpx.Timeout(3600, connect=15))


def assemble(chunks):
    indexes = {c.get('index', 0) for chunk in chunks for c in chunk.get('choices', [])}
    finished = {c.get('index', 0) for chunk in chunks for c in chunk.get('choices', [])
                if c.get('finish_reason')}
    if not indexes or not indexes.issubset(finished):
        raise ValueError('Provider stream ended before a finish reason')
    result = stream_chunk_builder(chunks=[ModelResponseStream(**chunk) for chunk in chunks],
                                  count_prompt_tokens=lambda: 0)
    if result is None:
        raise ValueError('Provider returned an empty stream')
    response = result.model_dump()
    if not response.get('choices') or not all(c.get('finish_reason') for c in response['choices']):
        raise ValueError('Provider stream ended before a finish reason')
    # LiteLLM's stream builder drops a signed thinking block when the provider
    # sends an empty summarized-thinking string. Keep that block for the client;
    # the upstream event archive remains the source of truth for its contents.
    signed_empty_blocks = {}
    for chunk in chunks:
        for choice in chunk.get('choices') or []:
            delta = choice.get('delta') or {}
            for block in delta.get('thinking_blocks') or []:
                if isinstance(block, dict) and block.get('signature') and not block.get('thinking'):
                    signed_empty_blocks.setdefault(choice.get('index', 0), []).append(block)
    for choice in response['choices']:
        message = choice.get('message') or {}
        provider_fields = message.get('provider_specific_fields') or {}
        blocks = signed_empty_blocks.get(choice.get('index', 0)) or []
        if blocks:
            if not message.get('thinking_blocks'):
                message['thinking_blocks'] = blocks
            if not provider_fields.get('thinking_blocks'):
                provider_fields['thinking_blocks'] = blocks
            message['provider_specific_fields'] = provider_fields
            choice['message'] = message
    return response


async def provider_call(body, headers, event):
    chunks = []
    async with client.stream('POST', 'https://llm.zhiyuanllm.com/v1/chat/completions',
                             json=body, headers=headers) as response:
        event['status'] = response.status_code
        if response.status_code != 200:
            payload = (await response.aread()).decode(errors='replace')
            try:
                returned = json.loads(payload)
            except ValueError:
                returned = {'error': {'type': 'provider_http_error', 'message': payload}}
            event['error_response'] = returned
            return response.status_code, returned
        async for line in response.aiter_lines():
            event['raw_stream_lines'].append(line)
            if not line.startswith('data:'):
                continue
            payload = line[5:].strip()
            if payload == '[DONE]':
                event['done_marker_seen'] = True
                break
            if payload:
                chunks.append(json.loads(payload))
    return 200, assemble(chunks)


async def guarded(awaitable, request):
    pending = asyncio.ensure_future(awaitable)
    try:
        while not pending.done():
            if await request.is_disconnected() and not pending.done():
                raise asyncio.CancelledError('Evaluation client disconnected')
            await asyncio.wait([pending], timeout=1)
        return await pending
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@app.get('/v1/models')
async def models():
    return {'object': 'list', 'data': [{'id': MODELS['claude'], 'object': 'model'}]}


@app.get('/health')
async def health():
    return {'ready': True, 'provider_streaming': True, 'max_upstream_concurrency': 12}


@app.post('/v1/chat/completions')
async def completion(request: Request):
    received = await request.json()
    if received.get('model', '').removeprefix('openai/') != MODELS['claude'] or received.get('stream'):
        raise HTTPException(400, 'Expected the configured Claude model and nonstreaming client')
    body = dict(received)
    body.update(body.pop('extra_body', {}))
    for key in ['reasoning_effort', 'session_id', 'chat_template_kwargs', 'top_p']:
        body.pop(key, None)
    body.update({'model': MODELS['claude'], 'temperature': 1,
                 'max_tokens': min(body.get('max_tokens') or 32768, 32768),
                 'thinking': {'type': 'adaptive', 'display': 'summarized'},
                 'output_config': {'effort': 'high'}, 'stream': True,
                 'stream_options': {'include_usage': True}})
    started = time.time()
    events = []
    code = 502
    returned = {'error': {'type': 'transport_error', 'message': 'No completed provider response'}}
    acquired = False
    try:
        await guarded(limit.acquire(), request)
        acquired = True
        headers = {'Authorization': 'Bearer ' + Path('/fsx/home/zhiyuan/bench/model-relay-token.txt').read_text().strip()}
        for attempt in range(4):
            before = time.time()
            event = {'attempt': attempt + 1, 'raw_stream_lines': []}
            events.append(event)
            try:
                code, returned = await guarded(provider_call(body, headers, event), request)
            except (httpx.HTTPError, ValueError) as error:
                code = 502
                returned = {'error': {'type': type(error).__name__, 'message': str(error)}}
                event['transport_error'] = type(error).__name__
            finally:
                event['seconds'] = time.time() - before
            if code not in {429, 500, 502, 503, 504, 520, 522, 524}:
                break
            if attempt < 3:
                await guarded(asyncio.sleep(2 ** attempt), request)
    except asyncio.CancelledError:
        code = 499
        returned = {'error': {'type': 'evaluation_client_disconnected', 'message': 'Canceled the upstream request'}}
    finally:
        if acquired:
            limit.release()
        directory = ROOT / 'api_archive/claude'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (uuid.uuid4().hex + '.json')).write_text(json.dumps({
            'model': MODELS['claude'], 'session': request.headers.get('X-Session-ID', ''),
            'backend': 'https://llm.zhiyuanllm.com/v1/chat/completions',
            'transport': 'provider_stream_assembled_to_client_json', 'started': started,
            'seconds': time.time() - started, 'status': code, 'request': body,
            'received_request': received, 'response': returned, 'events': events}, ensure_ascii=False))
    return JSONResponse(returned, status_code=code)


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=31352, log_level='warning')
