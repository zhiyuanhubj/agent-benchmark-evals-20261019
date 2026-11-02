import tempfile
import unittest
import json
from unittest.mock import patch
from pathlib import Path
from placement import choose_weights, retry_placement


class PlacementTest(unittest.TestCase):
    def test_retry_never_uses_a_stale_or_foreign_capacity_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rank=root/'bf16/rank0';rank.mkdir(parents=True)
            receipt=rank/'placement.json'
            for record in [dict(job=1,hostname='a',updated_unix=1),dict(job=2,hostname='a',updated_unix=20),dict(job=1,hostname='foreign',updated_unix=20)]:
                receipt.write_text(json.dumps({**record,'reason':'insufficient_local_NVMe'}))
                with patch('placement.subprocess.run') as run:
                    self.assertFalse(retry_placement(root,{'precision':'bf16','placement_retry_limit':3},1,['a','b'],10,lambda *_:None))
                    run.assert_not_called()

    def test_retry_updates_only_its_own_job_and_retains_prior_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rank=root/'bf16/rank0';rank.mkdir(parents=True)
            (rank/'placement.json').write_text(json.dumps(dict(job=1,hostname='a',updated_unix=20,reason='insufficient_local_NVMe')))
            (root/'PLACEMENT_RETRIES.json').write_text(json.dumps([{'excluded_nodes':['previous']}]))
            def save(p,d):p.write_text(json.dumps(d))
            with patch('placement.subprocess.run') as run:
                self.assertTrue(retry_placement(root,{'precision':'bf16','placement_retry_limit':3,'excluded_nodes':['known']},1,['a','b'],10,save))
                self.assertEqual(run.call_args_list[0].args[0],['scontrol','update','JobId=1','ExcNodeList=a,known,previous'])
                self.assertEqual(run.call_args_list[1].args[0],['scontrol','requeue','1'])

    def test_complete_local_weights_allow_reuse_when_disk_is_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cached=root/'zhiyuan-muse-perf-3137-0/weights';cached.mkdir(parents=True)
            (cached/'model').write_bytes(b'1234')
            d=choose_weights(root,root/'new',{'files':[{'file':'model','bytes':4}]},0,reserve=10)
            self.assertTrue(d['valid']);self.assertTrue(d['reuses_complete_weights'])
            self.assertEqual(d['path'],str(cached))

    def test_wrong_size_existing_file_still_requires_full_download_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);local=root/'new';(local/'weights').mkdir(parents=True)
            (local/'weights/model').write_bytes(b'1')
            d=choose_weights(root,local,{'files':[{'file':'model','bytes':4}]},12,reserve=10)
            self.assertFalse(d['valid']);self.assertEqual(d['missing_bytes'],4)

    def test_external_symlink_is_not_reused_as_a_complete_container_mount(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cached=root/'zhiyuan-muse-perf-3137-0/weights';cached.mkdir(parents=True)
            (root/'outside').write_bytes(b'1234');(cached/'model').symlink_to(root/'outside')
            d=choose_weights(root,root/'new',{'files':[{'file':'model','bytes':4}]},0,reserve=10)
            self.assertFalse(d['valid']);self.assertFalse(d['reuses_complete_weights'])


if __name__=='__main__':unittest.main()
