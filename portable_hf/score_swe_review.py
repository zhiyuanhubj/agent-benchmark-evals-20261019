#!/usr/bin/env python3
"""Run the bundled official DA scorer and optional revision/RRR workflow."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
OFFICIAL=ROOT/'workspace/bench/code-review-eval/data/repos/swe-review'
SIZES={'glm5_500':500,'qwen3_coder_30b_500':462,'qwen3_30b_instruct2507_500':422}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--review-job',type=Path,required=True,help='Harbor job directory containing individual trial subdirectories')
    p.add_argument('--split',choices=SIZES,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--revision',action='store_true')
    p.add_argument('--revision-model',help='Use the original PR generator for the selected split')
    p.add_argument('--revision-api-base',default='http://172.17.0.1:31321/v1')
    p.add_argument('--concurrency',type=int,default=4)
    args=p.parse_args()
    results=[json.loads(path.read_text()) for path in args.review_job.glob('*/result.json')]
    ids=[r.get('task_name') for r in results]
    assert len(ids)==len(set(ids))==SIZES[args.split] and all(ids), 'Full DA requires exactly one native result per split task'
    assert all(r.get('finished_at') for r in results),'Review job is still running'
    if args.revision:assert args.revision_model,'Specify the original PR generator model, not the reviewer alias'
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'results').symlink_to(args.review_job.resolve(),target_is_directory=True)
    env=dict(os.environ)
    env['PYTHONPATH']=str(OFFICIAL/'SWE-bench')+os.pathsep+env.get('PYTHONPATH','')
    tools=OFFICIAL/'SWE-Review-Bench'
    subprocess.run([sys.executable,str(tools/'compute_da.py'),'--results-dir',str(out),
        '--benchmark-split',args.split,'--output',str(out/'da_metrics.json')],env=env,cwd=OFFICIAL,check=True)
    if args.revision:
        env.update(LLM_API_KEY='EMPTY',LLM_BASE_URL=args.revision_api_base,
                   OPENAI_API_KEY='EMPTY',OPENHANDS_LLM_NATIVE_TOOL_CALLING='true',
                   CONCURRENCY=str(args.concurrency))
        subprocess.run(['bash',str(tools/'run_revision.sh'),str(out),
            args.revision_model,args.split],env=env,cwd=OFFICIAL,check=True)
        expected=len(list((out/'revision/tasks').glob('*/task.toml')))
        native=[json.loads(p.read_text()) for p in (out/'revision/results').rglob('result.json')
                if p.parent.name not in ('results',)]
        native=[r for r in native if r.get('task_name')]
        assert len(native)==expected,'Revision is incomplete; do not label partial RRR as final'
        assert all(r.get('finished_at') and (r.get('verifier_result') or {}).get('rewards') is not None for r in native), 'Revision has ungraded infrastructure errors'
        subprocess.run([sys.executable,str(tools/'compute_rrr.py'),'--results-dir',str(out),
            '--benchmark-split',args.split,'--output',str(out/'rrr_metrics.json')],env=env,cwd=OFFICIAL,check=True)


if __name__=='__main__':main()
