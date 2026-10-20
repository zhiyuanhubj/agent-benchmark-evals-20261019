import asyncio
import os
import contextlib
from dataclasses import replace
import json
from pathlib import Path
import sys
import shutil

ROOT = Path(__file__).resolve().parent
OLD=Path('/fsx/home/zhiyuan/bench/strict_four_models_20261008')
sys.path.insert(0,str(OLD))
sys.path.insert(0,str(OLD/'sources/swe-pro/v2/tooling'))
sys.path.insert(0,str(ROOT))
from harbor.job import Job
from harbor.models.job.config import JobConfig
from harbor.models.task.config import NetworkPolicy
from harbor.trial.trial import Trial
from harbor.agents.installed.base import BaseInstalledAgent, NonZeroAgentExitCodeError

original_classify = BaseInstalledAgent._classify_exec_error
def classify_without_context_retries(self,command,result):
    classified=original_classify(self,command,result)
    tail=(result.stdout or '')[-12000:]+'\n'+(result.stderr or '')[-12000:]
    if 'ContextWindowExceededError:' in tail or result.return_code in {124,137}:
        # Task text can mention rate limits and confuse Harbor's free-text
        # matcher. A context-limit exit is an ordinary model failure.
        return NonZeroAgentExitCodeError(str(classified))
    return classified
BaseInstalledAgent._classify_exec_error=classify_without_context_retries

original_network_plan = Trial._network_plan
def strict_plan(self, *args, **kwargs):
    plan = original_network_plan(self,*args,**kwargs)
    # Preserve original task files/digests, resources and time budgets.
    # Terminal-Bench's requested offline variant changes agent egress only.
    remote = self.config.agent.import_path in {'revision_agents:RevisionOpenHands'}
    phase = NetworkPolicy(network_mode='allowlist',allowed_hosts=[os.environ['MIX_SERVER_IP']]) if remote else NetworkPolicy(network_mode='no-network')
    return replace(plan,agent_phase=phase)
Trial._network_plan = strict_plan

original_phase = Trial._phase_network_policy
@contextlib.asynccontextmanager
async def strict_phase(self, environment, *, baseline_policy, phase_policy):
    async with original_phase(self,environment,baseline_policy=baseline_policy,phase_policy=phase_policy):
        controlled = phase_policy.network_mode.value != 'public'
        if controlled:
            remote = phase_policy.network_mode.value == 'allowlist'
            assert not remote or phase_policy.allowed_hosts == [os.environ['MIX_SERVER_IP']]
            # The agent cannot change its sidecar firewall. Block UDP, DNS,
            # ICMP, other internal hosts and all non-model gateway ports.
            rules = 'set -e\nnft delete table inet strict_eval 2>/dev/null || true\n'
            rules += 'nft delete table netdev strict_eval_l2 2>/dev/null || true\n'
            rules += 'nft -f - <<\'STRICT_NFT\'\nadd table inet strict_eval\n'
            rules += 'add chain inet strict_eval output { type filter hook output priority 10; policy drop; }\n'
            rules += 'add rule inet strict_eval output udp dport 53 drop\nadd rule inet strict_eval output tcp dport 53 drop\n'
            rules += 'add rule inet strict_eval output oifname "lo" accept\n'
            if remote:
                rules += 'insert rule inet gost_egress output ip daddr 10.1.115.182 tcp dport 31203 return\n'
                rules += 'add rule inet strict_eval output ip daddr 10.1.115.182 tcp dport 31203 accept\n'
            # Packet sockets bypass the inet output hook. Enforce the same
            # policy at the actual interface, preserving raw sockets locally.
            rules += 'add table netdev strict_eval_l2\n'
            rules += 'add chain netdev strict_eval_l2 output { type filter hook egress device "eth0" priority 10; policy drop; }\n'
            rules += 'add rule netdev strict_eval_l2 output ether type arp accept\n'
            if remote:
                rules += 'add rule netdev strict_eval_l2 output ether type ip ip daddr 10.1.115.182 ip protocol tcp tcp dport 31203 accept\n'
            rules += 'add rule netdev strict_eval_l2 output counter drop\n'
            rules += 'STRICT_NFT\nnft list table inet strict_eval\nnft list table netdev strict_eval_l2\n'
            rules = rules.replace('10.1.115.182', os.environ['MIX_SERVER_IP']).replace('31203','31410')
            applied = await environment.service_exec(service=environment._EGRESS_CONTROL_SERVICE_NAME,command=rules,user='root',timeout_sec=15)
            assert applied.return_code == 0, applied
            directory = ROOT/'state'/'firewall-audits'
            directory.mkdir(exist_ok=True)
            (directory/f'{self.config.trial_name}-{environment.session_id}.json').write_text(json.dumps({'phase':phase_policy.model_dump(mode='json'),'rules':applied.stdout}))
        try:
            yield
        finally:
            if controlled:
                removed = await environment.service_exec(service=environment._EGRESS_CONTROL_SERVICE_NAME,command='nft -f - <<\'STRICT_REMOVE\'\ndelete table inet strict_eval\ndelete table netdev strict_eval_l2\nSTRICT_REMOVE',user='root',timeout_sec=15)
                assert removed.return_code == 0, removed
Trial._phase_network_policy = strict_phase

async def preserve_attempt(event):
    # Harbor removes a failed attempt's directory before an automatic retry.
    # Preserve its actual verifier result and patch before that can happen.
    target=ROOT/'state/attempt-history'/event.trial_name/str(event.trial_id)
    target.mkdir(parents=True,exist_ok=True)
    (target/'result.json').write_text(event.result.model_dump_json(indent=2))
    source=Path(event.config.trials_dir)/event.trial_name
    for relative in ['agent/model.patch','artifacts/logs/artifacts/model.patch',
                     'trial.log','agent/trajectory.json']:
        path=source/relative
        if path.exists():
            destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,destination)

async def main():
    spec = json.loads(Path(sys.argv[1]).read_text())
    config = JobConfig.model_validate(spec['config'])
    job = await Job.create(config)
    from harbor.trial.hooks import TrialEvent
    job.add_hook(TrialEvent.END,preserve_attempt)
    result = await job.run()
    (ROOT/'state'/f'{config.job_name}-done.json').write_text(result.model_dump_json(indent=2))
    if spec.get('regrade'):
        regrade = config.model_copy(deep=True)
        regrade.job_name += '-regrade'
        from harbor.models.trial.config import AgentConfig
        regrade.agents = [AgentConfig(import_path='patch_replay:PatchReplayAgent',model_name='replay',kwargs={'source_job':str(job.job_dir)})]
        regrade.n_attempts = 1
        regrade_job = await Job.create(regrade)
        regrade_job.add_hook(TrialEvent.END,preserve_attempt)
        regrade_result = await regrade_job.run()
        (ROOT/'state'/f'{regrade.job_name}-done.json').write_text(regrade_result.model_dump_json(indent=2))

if __name__ == '__main__':
    asyncio.run(main())
