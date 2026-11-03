import unittest
from matrix import planned_points


class MatrixTest(unittest.TestCase):
    def test_groups_and_repetitions_are_distinct_and_retries_do_not_duplicate_points(self):
        allocation={'jobs':[{'precision':p,'mode':'long_and_paired_spec','input_lengths':[8192,32768,65536,131072]}
                            for p in ('nvfp4','bf16')]}
        allocation['jobs'].append({'precision':'nvfp4','mode':'baseline','input_lengths':[8192]})
        rows=planned_points(allocation)
        self.assertEqual(len(rows),120)
        self.assertEqual(len({(r['precision'],r['workload'],r['input_label'],r['speculative']) for r in rows}),16)
        self.assertEqual(sum(r['required_repeats'] for r in rows),364)
        self.assertEqual(sum(r['workload']=='synthetic' for r in rows),72)

    def test_dense_followup_adds_only_requested_points_and_keeps_base_sweep(self):
        base={'precision':'bf16','mode':'long','input_lengths':[65536]}
        dense={**base,'decode_concurrency':'40,48,56'}
        rows=planned_points({'jobs':[base,dense,dense]})
        self.assertEqual(len(rows),12)
        self.assertEqual({r['concurrency'] for r in rows},set((1,2,4,8,16,32,40,48,56,64,128,256)))
        self.assertEqual(len(planned_points({'jobs':[dense]})),3)

    def test_parallel_coding_partitions_preserve_original_24_points(self):
        base={'precision':'bf16','mode':'paired_spec','input_lengths':[]}
        jobs=[{**base,'coding_input_ranges':[bucket],'speculative_algorithms':[spec]}
              for bucket in ([0,8192],[8192,32768]) for spec in ('off','NGRAM')]
        expected=planned_points({'jobs':[base]})
        actual=planned_points({'jobs':jobs})
        self.assertEqual(actual,expected)
        self.assertTrue(all(len(planned_points({'jobs':[j]}))==6 for j in jobs))


if __name__=='__main__':unittest.main()
