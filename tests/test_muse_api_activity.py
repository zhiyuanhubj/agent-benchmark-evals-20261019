"""Exercise real/background request separation and cancellation before headers."""
import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

import httpx


class RelayActivityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        keys = []
        for label in ('primary', 'client-01', 'background'):
            path = root / (label + '.key')
            path.write_text(label + '-test-secret')
            keys.append({'file': str(path), 'label': label, 'models': ['muse'],
                         'background': label == 'background'})
        cfg = root / 'config.json'
        cfg.write_text(json.dumps({'upstream_base': 'http://upstream/v1',
                                  'models': {'muse': 'muse-bf16'}, 'keys': keys,
                                  'background_idle_seconds': 0}))
        self.old_config = os.environ.get('MUSE_OPENAI_RELAY_CONFIG')
        os.environ['MUSE_OPENAI_RELAY_CONFIG'] = str(cfg)
        script = Path(__file__).resolve().parents[1] / 'protocol/muse_openai_key_relay_20261021.py'
        spec = importlib.util.spec_from_file_location('relay_test', script)
        self.relay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.relay)
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

        async def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body['model'], 'muse-bf16')
            if body['messages'][0]['content'] == 'slow':
                self.started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cancelled.set()
            if body.get('stream'):
                class SSE(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        yield b'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":3}}\n\n'
                        yield b'data: [DONE]\n\n'
                return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                      stream=SSE())
            return httpx.Response(200, json={'choices': [{'message': {
                'content': 'ok', 'reasoning_content': 'thinking'}}],
                'usage': {'prompt_tokens': 5, 'completion_tokens': 2}})

        self.upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.relay.app.state.http = self.upstream
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.relay.app),
                                        base_url='http://relay')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.upstream.aclose()
        if self.old_config is None:
            os.environ.pop('MUSE_OPENAI_RELAY_CONFIG', None)
        else:
            os.environ['MUSE_OPENAI_RELAY_CONFIG'] = self.old_config
        self.temp.cleanup()

    def headers(self, label):
        return {'Authorization': 'Bearer ' + label + '-test-secret'}

    async def post(self, label, prompt='ok', **extra):
        return await self.client.post('/v1/chat/completions', headers=self.headers(label),
            json={'model': 'muse', 'messages': [{'role': 'user', 'content': prompt}],
                  'max_tokens': 128, **extra})

    async def test_authentication_usage_and_thinking_passthrough(self):
        self.assertEqual((await self.client.get('/v1/models')).status_code, 401)
        response = await self.post('client-01')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['choices'][0]['message']['reasoning_content'], 'thinking')
        self.assertEqual((await self.client.get('/admin/usage', headers=self.headers('client-01'))).status_code, 403)
        usage = (await self.client.get('/admin/usage', headers=self.headers('primary'))).json()
        self.assertEqual(usage['by_key']['client-01']['requests'], 1)
        self.assertEqual(usage['by_key']['client-01']['completion_tokens'], 2)
        self.assertEqual(usage['real_active'], 0)

    async def test_real_request_cancels_background_before_upstream_headers(self):
        background = asyncio.create_task(self.post('background', 'slow'))
        await asyncio.wait_for(self.started.wait(), 2)
        real = await self.post('client-01')
        self.assertEqual(real.status_code, 200)
        self.assertEqual((await asyncio.wait_for(background, 2)).status_code, 499)
        await asyncio.wait_for(self.cancelled.wait(), 2)
        snapshot = self.relay.activity.snapshot()
        self.assertEqual(snapshot['by_key']['background']['errors'], 1)
        self.assertEqual(snapshot['by_key']['client-01']['requests'], 1)
        self.assertEqual(snapshot['background_active'], 0)
        self.relay.activity.idle_seconds = 120
        self.assertEqual((await self.post('background')).status_code, 429)

    async def test_streaming_usage_and_persistent_counts(self):
        response = await self.post('client-01', stream=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('[DONE]', response.text)
        from protocol.muse_api_activity_20261021 import Activity
        restored = Activity(self.relay.activity.path)
        self.assertEqual(restored.snapshot()['by_key']['client-01']['prompt_tokens'], 7)
        self.assertEqual(restored.snapshot()['real_active'], 0)
        self.assertEqual((await self.post('background', stream=True)).status_code, 400)


if __name__ == '__main__':
    unittest.main()
