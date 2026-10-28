"""Boundary tokens and latency tails must not inflate or censor the curve."""
import unittest
import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from bench import Round, percentile, summarize, window_tokens


def request(start, finish, valid=True):
    return {'started': start, 'finished': finish, 'valid': valid,
            'meta': {'completion_tokens': 100, 'prompt_tokens': 8192, 'cached_tokens': 0},
            'ttft_s': 1., 'tpot_s': .1, 'e2e_s': finish - start,
            'decode_tokens_per_second': 10.}


class MetricsTest(unittest.TestCase):
    def test_strict_window_counts_warmup_and_drain_boundaries(self):
        # Include received tokens from an already-running warmup request; exclude drain.
        events = [(9.9, 5), (10., 2), (15., 7), (19.99, 3), (20., 11)]
        self.assertEqual(window_tokens(events, 10, 20), 12)
        rows = [request(8, 11), request(12, 25)]
        summary = summarize(rows, events, 10, 20, 8)
        self.assertEqual(summary['output_tokens_per_second_per_gpu'], 12 / 10 / 8)
        self.assertEqual(summary['completed_in_window'], 1)
        self.assertEqual(summary['successful_arrivals_after_drain'], 1)
        self.assertEqual(summary['e2e_s']['p95'], 13)  # The slow drained tail remains.

    def test_failure_is_retained_but_not_a_successful_latency_sample(self):
        rows = [request(11, 14), request(12, 17, False)]
        summary = summarize(rows, [(13, 100), (16, 3)], 10, 20, 16)
        self.assertEqual(summary['failed_arrivals_after_drain'], 1)
        self.assertEqual(summary['failed_in_window'], 1)
        self.assertEqual(summary['ttft_s']['n'], 1)
        self.assertEqual(summary['output_tokens_received_in_window'], 103)

    def test_percentile_is_over_request_metrics_not_pooled_intertoken_events(self):
        self.assertEqual(percentile([1., 2., 10.], .5), 2.)
        self.assertAlmostEqual(percentile([1., 2., 10.], .95), 9.2)
        self.assertIsNone(percentile([], .95))


class StreamingProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_native_cumulative_counts_include_thinking_and_final_text(self):
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for count, text in ((1, 'thinking'), (512, 'thinking and intermediate'), (1024, 'thinking and final answer')):
                    obj = {'text': text, 'meta_info': {'completion_tokens': count, 'prompt_tokens': 8192,
                                                      'cached_tokens': 0, 'reasoning_tokens': 900}}
                    yield ('data: ' + json.dumps(obj) + '\n\n').encode()
                yield b'data: [DONE]\n\n'
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body['sampling_params']['max_new_tokens'], 1024)
            return httpx.Response(200, stream=Stream())
        load = Round(SimpleNamespace(base='http://test'), {}, 1, 0, Path('.'))
        load.raw = io.StringIO()
        prompts = SimpleNamespace(next=lambda: ([2] * 8192, {'id': 'fixture'}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            row = await load.request(c, prompts, 0)
        self.assertTrue(row['valid'])
        self.assertEqual(sum(n for _, n in load.events), 1024)
        self.assertEqual(row['meta']['reasoning_tokens'], 900)
        self.assertEqual(row['text'], 'thinking and final answer')


if __name__ == '__main__':
    unittest.main()
