"""Install only a known missing model-client dependency before the first query."""
from pathlib import Path
import hashlib
import json
import shlex
import tempfile
import time

ROOT = Path(__file__).resolve().parent
WHEELS = Path('/fsx/home/zhiyuan/.private/nemotron35super/runs/opus48_mix3_20261014/early9_full_validation_20261017/state/client-dependency-repair-wheels')
PYTHON = '/root/.local/share/uv/tools/mini-swe-agent/bin/python'
PACKAGES = 'import importlib.metadata as m,json; print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()},sort_keys=True))'


async def ensure_client_dependency(agent, environment):
    probe = await environment.exec(command=shlex.quote(PYTHON) + ' -c ' + shlex.quote('import mcp'), timeout_sec=30)
    if probe.return_code == 0:
        return
    assert "No module named 'mcp'" in (probe.stderr or '') + (probe.stdout or ''), probe
    checked = await environment.exec(command=shlex.quote(PYTHON) + ' -c ' + shlex.quote(PACKAGES), timeout_sec=30)
    assert checked.return_code == 0, checked
    before = json.loads(checked.stdout)
    assert before.get('mini-swe-agent') == '2.4.2' and before.get('litellm') in {'1.106.0', '1.106.1'}
    assert 'mcp' not in before
    record = dict(utc=time.time(), session=agent.session_id, before=before,
                  scope='Known missing client import repaired before the agent subprocess/model query. Existing package versions, model settings, tasks, verifier and deadlines unchanged.',
                  wheels={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in WHEELS.glob('*.whl')})
    await environment.upload_dir(source_dir=WHEELS, target_dir='/tmp/pinned-client-dependency-wheels')
    with tempfile.TemporaryDirectory(prefix='opus47-client-constraints-') as temporary:
        path = Path(temporary) / 'constraints.txt'
        path.write_text(''.join(k + '==' + v + '\n' for k, v in before.items()))
        await environment.upload_file(source_path=path, target_path='/tmp/pinned-client-dependency-constraints.txt')
    install = await environment.exec(command='/root/.local/bin/uv pip install --python ' + shlex.quote(PYTHON)
        + ' --no-index --find-links /tmp/pinned-client-dependency-wheels --constraint /tmp/pinned-client-dependency-constraints.txt mcp==2.2.0', timeout_sec=90)
    assert install.return_code == 0, install
    checked = await environment.exec(command=shlex.quote(PYTHON) + ' -c ' + shlex.quote('import mcp; ' + PACKAGES), timeout_sec=30)
    assert checked.return_code == 0, checked
    after = json.loads(checked.stdout)
    assert all(after.get(k) == v for k, v in before.items())
    record.update(after=after, status='import_verified_before_first_model_query')
    (ROOT / 'state' / ('client-setup-' + agent.session_id + '.json')).write_text(json.dumps(record, indent=2) + '\n')
