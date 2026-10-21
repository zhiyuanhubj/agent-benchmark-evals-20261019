#!/usr/bin/env python3
"""OpenAI-compatible Muse relay with per-key model alias allowlists."""

import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


CONFIG = Path(os.environ['MUSE_OPENAI_RELAY_CONFIG'])
config = json.loads(CONFIG.read_text())
upstream = config['upstream_base'].rstrip('/')
assert upstream.startswith('http://') or upstream.startswith('https://')
models = config['models']
assert models and all(isinstance(alias, str) and isinstance(model, str)
                      for alias, model in models.items())
key_bindings = []
for binding in config['keys']:
    secret = Path(binding['file']).read_text().strip()
    assert secret and set(binding['models']).issubset(models)
    key_bindings.append((secret, frozenset(binding['models'])))
assert key_bindings


@asynccontextmanager
async def lifespan(app):
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(3600, connect=15),
                                       trust_env=False)
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def allowed(request):
    header = request.headers.get('authorization', '')
    if not header.lower().startswith('bearer '):
        raise HTTPException(401, 'Bearer API key required', headers={'WWW-Authenticate': 'Bearer'})
    supplied = header[7:].strip()
    permitted = set()
    for secret, aliases in key_bindings:
        if hmac.compare_digest(supplied, secret):
            permitted.update(aliases)
    if not permitted:
        raise HTTPException(401, 'Invalid API key', headers={'WWW-Authenticate': 'Bearer'})
    return permitted


@app.get('/healthz')
async def health():
    try:
        response = await app.state.http.get(upstream + '/models', timeout=10)
        response.raise_for_status()
        available = {row['id'] for row in response.json()['data']}
        assert set(models.values()).issubset(available)
        return {'status': 'ok', 'upstream_models': len(available)}
    except Exception:
        return JSONResponse({'status': 'upstream_unavailable'}, status_code=503)


@app.get('/v1/models')
async def list_models(request: Request):
    permitted = allowed(request)
    return {'object': 'list', 'data': [{'id': alias, 'object': 'model', 'owned_by': 'zhiyuan'}
                                      for alias in sorted(permitted)]}


@app.get('/v1/models/{alias}')
async def get_model(alias: str, request: Request):
    permitted = allowed(request)
    if alias not in permitted:
        raise HTTPException(404, 'Model unavailable for this API key')
    return {'id': alias, 'object': 'model', 'owned_by': 'zhiyuan'}


@app.post('/v1/{operation:path}')
async def forward(operation: str, request: Request):
    if operation not in ('chat/completions', 'completions'):
        raise HTTPException(404, 'Unsupported endpoint')
    permitted = allowed(request)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, 'JSON body required')
    if not isinstance(body, dict):
        raise HTTPException(400, 'JSON object required')
    alias = body.get('model')
    if not isinstance(alias, str) or alias not in permitted:
        raise HTTPException(403, 'Model not allowed for this API key')
    body['model'] = models[alias]
    headers = {'Content-Type': 'application/json'}
    for name in ('x-request-id', 'x-session-id'):
        if request.headers.get(name):
            headers[name] = request.headers[name]
    try:
        upstream_request = app.state.http.build_request('POST', upstream + '/' + operation,
                                                         json=body, headers=headers)
        response = await app.state.http.send(upstream_request, stream=True)
    except httpx.HTTPError:
        raise HTTPException(502, 'Muse upstream unavailable')

    response_headers = {'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    content_type = response.headers.get('content-type', 'application/json')
    if body.get('stream') and response.status_code == 200:
        async def chunks():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()
        return StreamingResponse(chunks(), status_code=response.status_code,
                                 media_type=content_type, headers=response_headers)
    try:
        payload = await response.aread()
    finally:
        await response.aclose()
    return Response(content=payload, status_code=response.status_code,
                    media_type=content_type, headers=response_headers)
