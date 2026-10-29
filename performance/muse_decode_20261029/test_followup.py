import tempfile
import unittest
from pathlib import Path
from dense_followup import proc_matches


class FollowupIdentityTest(unittest.TestCase):
    def test_reused_pid_wrong_task_and_zombie_are_not_signal_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'123';p.mkdir()
            fields=['0']*22;fields[2]='S';fields[21]='900'
            (p/'stat').write_text(' '.join(fields))
            (p/'cmdline').write_bytes(b'python\0/test/control.py\0--state\0/test/state\0')
            self.assertTrue(proc_matches(123,'900',Path('/test/control.py'),Path('/test/state'),root))
            self.assertFalse(proc_matches(123,'901',Path('/test/control.py'),Path('/test/state'),root))
            self.assertFalse(proc_matches(123,'900',Path('/test/control.py'),Path('/other/state'),root))
            fields[2]='Z';(p/'stat').write_text(' '.join(fields))
            self.assertFalse(proc_matches(123,'900',Path('/test/control.py'),Path('/test/state'),root))


if __name__=='__main__':unittest.main()
