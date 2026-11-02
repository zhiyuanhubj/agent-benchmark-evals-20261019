import copy
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from activate_bf16 import allocation_hosts, backend_matches, gateway_config
from bf16_backend import verify_bf16


class RestorationTest(unittest.TestCase):
    def test_expired_allocation_does_not_count_as_a_live_backend(self):
        with patch('activate_bf16.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='',stderr='slurm_load_jobs error: Invalid job id specified')):
            self.assertEqual(allocation_hosts(1,'owner'),(None,'not_allocated'))
        with patch('activate_bf16.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='foreign|RUNNING|host\n',stderr='')):
            with self.assertRaises(RuntimeError):allocation_hosts(1,'owner')

    def test_switch_preserves_keys_roles_and_usage_without_aliasing_nvfp4_to_bf16(self):
        old={'upstream_base':'http://old/v1','models':{'muse-spark-open-nvfp4':'nvfp4'},
             'keys':[{'file':'/private/original.key','label':'client-01','models':['muse-spark-open-nvfp4']},
                     {'file':'/private/bg.key','label':'bg','models':['muse-spark-open-nvfp4'],'background':True}],
             'usage_db':'/original/usage.sqlite3','admin_labels':['primary']}
        before=copy.deepcopy(old);new=gateway_config(old,'test','http://new/v1')
        self.assertEqual(old,before);self.assertEqual(new['usage_db'],old['usage_db'])
        self.assertEqual([k['file'] for k in new['keys']],[k['file'] for k in old['keys']])
        self.assertTrue(new['keys'][1]['background'])
        self.assertNotIn('muse-spark-open-nvfp4',new['models'])
        self.assertEqual(new['models']['muse-spark-open'],'muse-spark-open-bf16')

    def test_activation_rejects_stale_foreign_and_wrong_host_backend_markers(self):
        marker=dict(job=1,nodes=['ip-10-1-1-1','ip-10-1-1-2'],precision='bf16',phase='ready_api_backend',
                    native_base='http://10.1.1.1:31420',gpus=16,global_admission_cap=8,updated_unix=100)
        self.assertTrue(backend_matches(marker,1,marker['nodes'],150))
        self.assertFalse(backend_matches(marker,2,marker['nodes'],150))
        self.assertFalse(backend_matches(marker,1,marker['nodes'],191))
        self.assertFalse(backend_matches({**marker,'native_base':'http://foreign:31420'},1,marker['nodes'],150))
        self.assertFalse(backend_matches({**marker,'updated_unix':200},1,marker['nodes'],150))

    def test_actual_bf16_dtype_and_parallel_configuration_are_required(self):
        info=dict(served_model_name='muse-spark-open-bf16',dtype='bfloat16',quantization=None,
                  tp_size=16,ep_size=16,nnodes=2,max_running_requests=8,reasoning_parser='muse',tool_call_parser='muse')
        verify_bf16(info)
        for field,value in [('dtype','float16'),('quantization','modelopt_fp4'),('tp_size',8),('max_running_requests',256)]:
            with self.assertRaises(AssertionError):verify_bf16({**info,field:value})


if __name__=='__main__':unittest.main()
