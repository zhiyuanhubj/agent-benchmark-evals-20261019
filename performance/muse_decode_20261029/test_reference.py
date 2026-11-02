import unittest
from pathlib import Path
from reference_plot import reference_points


class ReferenceProvenanceTest(unittest.TestCase):
    def test_pinned_image_digitization_preserves_batch_scope_and_axes(self):
        meta,points=reference_points(Path(__file__).parent/'reference')
        self.assertEqual([p['global_requests'] for p in points],[512,1024,2048,4096,8192,16384])
        self.assertEqual(meta['context_tokens'],131072)
        self.assertEqual(meta['tau'],3.25)
        self.assertTrue(all(a['speed_tokens_s_user_approx']>b['speed_tokens_s_user_approx'] for a,b in zip(points,points[1:])))
        self.assertTrue(all(a['throughput_tokens_s_gpu_approx']<b['throughput_tokens_s_gpu_approx'] for a,b in zip(points,points[1:])))


if __name__=='__main__':unittest.main()
