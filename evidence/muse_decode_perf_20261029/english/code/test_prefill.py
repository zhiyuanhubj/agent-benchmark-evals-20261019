import unittest
from prefill import phase_window


class PrefillPhaseTest(unittest.TestCase):
    def test_phase_envelope_uses_actual_input_counts_and_excludes_initial_queue(self):
        rows=[{'valid':True,'meta':{'forward_entry_time':10,'prefill_finished_time':12,'prompt_tokens':8192,'num_retractions':0,'cached_tokens':0}},
              {'valid':True,'meta':{'forward_entry_time':11,'prefill_finished_time':14,'prompt_tokens':4096,'num_retractions':0,'cached_tokens':0}}]
        w=phase_window(rows,8)
        self.assertEqual(w['actual_input_tokens'],12288)
        self.assertEqual(w['engine_seconds'],4)
        self.assertEqual(w['input_tokens_s_gpu'],12288/4/8)
        self.assertEqual(w['request_prefill_latencies_s'],[2,3])
        rows[0]['meta']['num_retractions']=1
        self.assertFalse(phase_window(rows,8)['valid'])


if __name__=='__main__':unittest.main()
