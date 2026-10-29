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


if __name__=='__main__':unittest.main()
