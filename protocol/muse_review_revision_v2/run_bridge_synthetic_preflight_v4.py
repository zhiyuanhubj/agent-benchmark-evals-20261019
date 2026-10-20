"""One synthetic Harbor task checks the isolated trial's full model transport."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(sys.argv[1])
prefix = sys.argv[2] if len(sys.argv) > 2 else "synthetic-preflight"
config = ROOT / (prefix + "-config.json")
job = json.loads(config.read_text())["config"]
agent_env = job["agents"][0]["env"]
env = dict(os.environ)
env.update(agent_env)
env.update(
    OPENAI_API_KEY="dummy-key",
    LLM_API_KEY="dummy-key",
    MIX_SERVER_IP="172.17.0.1",
    PYTHONPATH=str(ROOT / "harness") + ":/fsx/home/zhiyuan/bench/strict_four_models_20261008",
    HF_HOME="/fsx/home/zhiyuan/bench/hf_home",
    UV_CACHE_DIR="/fsx/home/zhiyuan/bench/uv_cache",
)
for name in ("LITELLM_EXTRA_BODY", "LLM_TEMPERATURE"):
    env.pop(name, None)
command = [
    "/fsx/home/zhiyuan/.local/share/uv/tools/harbor/bin/python",
    str(ROOT / "harness/swe_entry.py"),
    str(config),
]
with (ROOT / (prefix + ".log")).open("a") as stream:
    result = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT)
receipt = {
    "utc": time.time(),
    "scope": "Synthetic transport and tool use only; no official benchmark task or score",
    "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    "returncode": result.returncode,
    "native_results_dir": job["jobs_dir"],
}
(ROOT / (prefix + "-exit.json")).write_text(json.dumps(receipt, indent=2) + "\n")
raise SystemExit(result.returncode)
