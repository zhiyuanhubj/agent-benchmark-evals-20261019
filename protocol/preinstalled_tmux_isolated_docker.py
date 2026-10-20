"""Supply the harness tmux binary without changing the pinned TB task image.

Only the declared train-fasttext infrastructure correction uses this class.
The task image, task files, network isolation, model, and verifier remain fixed.
"""

import json

from isolated_docker import IsolatedDocker


TOOL_MOUNTS = (
    ('/usr/bin/tmux', '/usr/bin/tmux'),
    ('/lib/x86_64-linux-gnu/libutempter.so.1.2.1',
     '/lib/x86_64-linux-gnu/libutempter.so.0'),
    ('/lib/x86_64-linux-gnu/libevent_core-2.1.so.7.0.1',
     '/lib/x86_64-linux-gnu/libevent_core-2.1.so.7'),
)


class PreinstalledTmuxIsolatedDocker(IsolatedDocker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        overlay = json.loads(self._strict_overlay.read_text())
        assert overlay['networks']['default']['external'] is True
        assert 'services' not in overlay
        overlay['services'] = {
            'main': {
                'volumes': [
                    {'type': 'bind', 'source': source, 'target': target,
                     'read_only': True}
                    for source, target in TOOL_MOUNTS
                ]
            }
        }
        self._strict_overlay.write_text(json.dumps(overlay))
