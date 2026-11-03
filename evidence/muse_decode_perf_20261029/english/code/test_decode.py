import unittest
from decode import decode_window, counters, RETRACTION_TOTAL, no_kv_retractions


class DecodeWindowTest(unittest.TestCase):
    def test_lazy_counter_series_and_native_zero_are_valid(self):
        self.assertTrue(no_kv_retractions([{'meta':{'num_retractions':0}}],{},{}))
        self.assertFalse(no_kv_retractions([{'meta':{'num_retractions':1}}],{},{}))
        self.assertFalse(no_kv_retractions([{'meta':{'num_retractions':0}}],{},{RETRACTION_TOTAL:[1]}))
        self.assertFalse(no_kv_retractions([{'meta':{}}],{},{}))

    def test_retraction_validation_uses_monotonic_counter_not_resetting_gauge(self):
        body='sglang:num_retracted_reqs{pid="1"} 0\nsglang:num_retracted_requests_total{pid="1"} 7\n'
        c=counters(body)
        self.assertEqual(c[RETRACTION_TOTAL],[7.])
        self.assertNotIn('sglang:num_retracted_reqs',c)

    def test_excludes_prefill_and_tail_and_counts_actual_increments(self):
        # Last first token is t=2; earliest last token is t=5. Output jumps
        # deliberately differ, so C times an average speed cannot pass.
        rows=[{'valid':True,'started':0,'meta':{'completion_tokens':9},'token_timing':[(1,1),(2,2),(3,5),(4,7),(5,9)]},
              {'valid':True,'started':0,'meta':{'completion_tokens':8},'token_timing':[(2,1),(3,2),(4,5),(6,8)]}]
        w=decode_window(rows,8,guard_tokens=0)
        self.assertTrue(w['valid']);self.assertAlmostEqual(w['decode_seconds'],3)
        self.assertEqual(w['actual_output_tokens'],9)
        self.assertAlmostEqual(w['output_tokens_s_gpu'],9/3/8)
        self.assertEqual(w['request_decode_speeds'],[2.,3.])

    def test_failed_or_nonoverlapping_cohorts_are_not_decode_points(self):
        self.assertFalse(decode_window([{'valid':False}],8)['valid'])
        r=[{'valid':True,'started':0,'meta':{'completion_tokens':2},'token_timing':[(1,1),(2,2)]},
           {'valid':True,'started':0,'meta':{'completion_tokens':2},'token_timing':[(3,1),(4,2)]}]
        self.assertEqual(decode_window(r,8,guard_tokens=0)['reason'],'no_full_resident_decode_interval')


if __name__=='__main__':unittest.main()
