"""Original revision agent with the Docker host bridge model endpoint.

Only the transport address changes. The served model, prompt, agent version,
sampling settings, task input, and native grader remain pinned to the originals.
"""
import json
import os
import re
import shlex
import socket
import struct
from urllib.parse import urlsplit

from vendor.openhands_sdk import OpenHandsSDK


class RevisionOpenHands(OpenHandsSDK):
    async def run(self, instruction, environment, context):
        route = await environment.exec(
            command="awk '$2==\"00000000\" {print $3; exit}' /proc/net/route",
            timeout_sec=10,
        )
        raw = route.stdout.strip()
        assert route.return_code == 0 and re.fullmatch(r"[0-9A-Fa-f]{8}", raw), (
            "Cannot identify isolated trial gateway", raw
        )
        gateway = socket.inet_ntoa(struct.pack("<L", int(raw, 16)))
        assert gateway.startswith("10.200."), ("Unexpected trial gateway", gateway)

        original = os.environ["LLM_BASE_URL"]
        parsed = urlsplit(original)
        assert parsed.scheme == "http" and parsed.port in (31410, 31411)
        host_bridge = os.environ["MIX_SERVER_IP"]
        assert host_bridge == "172.17.0.1", ("Unexpected model bridge", host_bridge)
        assert parsed.hostname == host_bridge, ("Agent endpoint differs from firewall allowlist", original)
        effective = original
        endpoint = effective.rstrip("/") + "/models"
        command = "curl --noproxy '*' -fsS --connect-timeout 5 --max-time 20 -H " + shlex.quote(
            "Authorization: Bearer " + os.environ["LLM_API_KEY"]
        ) + " " + shlex.quote(endpoint)
        response = await environment.exec(command=command, timeout_sec=25)
        models = json.loads(response.stdout).get("data", []) if response.return_code == 0 else []
        served = self.model_name.removeprefix("hosted_vllm/")
        ids = [item.get("id") for item in models]
        (self.logs_dir / "model-connectivity.json").write_text(json.dumps({
            "original_endpoint": original,
            "effective_endpoint": effective,
            "trial_gateway": gateway,
            "host_bridge": host_bridge,
            "return_code": response.return_code,
            "served_model_verified": served in ids,
            "model_ids": ids,
            "stdout_error": response.stdout[-300:] if response.return_code else None,
            "stderr_error": response.stderr[-300:] if response.return_code and response.stderr else None,
        }, indent=2))
        assert response.return_code == 0 and served in ids, "Model unavailable before first response"
        await super().run(instruction, environment, context)
