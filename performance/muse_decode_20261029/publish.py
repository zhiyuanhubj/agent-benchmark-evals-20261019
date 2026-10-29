#!/usr/bin/env python3
"""Queue status and genuine decode-only curves; never import serving measurements."""
import argparse
import csv
import fcntl
import gzip
import json
import os
import statistics
import subprocess
import sys
import time
import zlib
from collections import defaultdict
from pathlib import Path

from native_client import distribution


def records(path):
    try:
        with gzip.open(path,'rt') as f:
            for line in f:
                try:yield json.loads(line)
                except json.JSONDecodeError:break
    except (EOFError,OSError,zlib.error):return


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--repo',type=Path,required=True);a=p.parse_args()
    lock=(a.root/'publish.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    allocation=json.loads((a.root/'ALLOCATIONS.json').read_text());jobs=allocation['jobs']
    queue=subprocess.run(['squeue','-h','-j',','.join(str(j['job']) for j in jobs),'-o','%i|%T|%D|%R'],capture_output=True,text=True)
    rows=[];groups=defaultdict(list);states={}
    for job in jobs:
        state=Path(job['state']);s=state/'status.json'
        states[str(job['job'])]=json.loads(s.read_text()) if s.exists() else {'phase':'queued'}
        frames=[f for path in (state/job['precision']/'gpu').glob('*.jsonl.gz') for f in records(path)]
        for path in sorted(state.glob('*/spec-*/*/c*/summary.json')):
            r=json.loads(path.read_text());scenario=r['scenario'];counts=defaultdict(int);util=[];mem=[]
            windows=[(w['start_monotonic']+w['unix_offset'],w['end_monotonic']+w['unix_offset']) for w in r['windows']]
            for f in frames:
                if not any(lo<=f['unix']<hi for lo,hi in windows):continue
                for values in f.get('rows',[]):
                    row=dict(zip(f['fields'],values))
                    try:
                        u=float(row['utilization.gpu']);m=float(row['memory.used'])
                    except (KeyError,ValueError):continue
                    counts[row['uuid']]+=1;util.append(u);mem.append(m)
            gpu_ok=len(counts)==r['gpus'] and min(counts.values(),default=0)>=r['decode_seconds']*.8
            valid=r['valid'] and gpu_ok
            label=scenario.get('input_label',str(scenario['input_tokens']))
            row={'job':job['job'],'precision':r['precision'],'workload':scenario['workload'],'input_label':label,
                 'speculative':scenario['speculative'],'concurrency':r['concurrency'],'repeat':r['repeat'],
                 'valid':valid,'gpu_telemetry_complete':gpu_ok,'decode_seconds':r['decode_seconds'],
                 'actual_output_tokens':r['actual_output_tokens'],'tokens_s_gpu':r['output_tokens_s_gpu'],
                 'decode_p50':r['request_decode_speed']['p50'],'tpot_p50_s':r['tpot_s']['p50'],'tpot_p95_s':r['tpot_s']['p95'],
                 'successful_requests':r['successful_measured_requests'],'failed_requests':r['failed_measured_requests'],
                 'spec_accept_length':r['spec_accept_length'],'gpu_util_mean':statistics.mean(util) if util else None,
                 'gpu_memory_mib_max':max(mem,default=None),'artifact':str(path)}
            rows.append(row)
            if valid:groups[(r['precision'],scenario['workload'],label,scenario['speculative'],r['concurrency'])].append(r)
    if not (a.repo/'.git').exists():
        subprocess.run(['git','clone','--filter=blob:none','--sparse','https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019.git',str(a.repo)],check=True)
        for key,value in [('user.name','Zhiyuan Hu'),('user.email','29817400+zhiyuanhubj@users.noreply.github.com')]:
            subprocess.run(['git','-C',str(a.repo),'config',key,value],check=True)
    def git(*args):return subprocess.run(['git','-C',str(a.repo),*args],capture_output=True,text=True,check=True)
    git('sparse-checkout','set','--no-cone','/evidence/muse_decode_perf_20261029/')
    git('pull','--rebase','origin','main')
    dest=a.repo/'evidence/muse_decode_perf_20261029';dest.mkdir(parents=True,exist_ok=True)
    if rows:
        with (dest/'decode_rounds.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    points=[]
    for key,rs in sorted(groups.items()):
        precision,workload,label,spec,c=key
        required=5 if precision=='nvfp4' and label=='8192' and c in (4,8) else 3
        if len(rs)<required:continue
        samples=[v for r in rs for v in r['request_decode_speeds']]
        duration=sum(r['decode_seconds'] for r in rs);tokens=sum(r['actual_output_tokens'] for r in rs)
        points.append({'precision':precision,'workload':workload,'input_label':label,'speculative':spec,'concurrency':c,
             'repeats':len(rs),'decode_p50':statistics.median(samples),'tokens_s_gpu':tokens/duration/rs[0]['gpus'],
             'decode_seconds':duration,'actual_output_tokens':tokens,
             'decode_sd':statistics.stdev(r['request_decode_speed']['p50'] for r in rs),
             'throughput_sd':statistics.stdev(r['output_tokens_s_gpu'] for r in rs)})
    if points:
        with (dest/'decode_points.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(points[0]));w.writeheader();w.writerows(points)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        for workload in ['synthetic','coding']:
            fig,ax=plt.subplots(figsize=(11,7));lines=defaultdict(list)
            for r in points:
                if r['workload']==workload:lines[(r['precision'],r['input_label'],r['speculative'])].append(r)
            for key,values in sorted(lines.items()):
                values.sort(key=lambda r:r['concurrency'])
                ax.errorbar([r['decode_p50'] for r in values],[r['tokens_s_gpu'] for r in values],
                    xerr=[r['decode_sd'] for r in values],yerr=[r['throughput_sd'] for r in values],marker='o',capsize=3,label=' / '.join(key))
                for r in values:ax.annotate(str(r['concurrency']),(r['decode_p50'],r['tokens_s_gpu']),xytext=(4,5),textcoords='offset points',fontsize=8)
            ax.set_xlabel('Per-request decode speed p50 (output tokens/s/user)')
            ax.set_ylabel('Actual decode-window output tokens / decode-window seconds / GPU')
            ax.set_title('Muse: real-KV decode-only windows — '+workload+'\nExcludes prefill, refill gaps and cohort tails; error bars: repetition SD')
            ax.grid(alpha=.25)
            if lines:ax.legend(fontsize=8)
            fig.tight_layout()
            for suffix in ['png','pdf','svg']:fig.savefig(dest/('decode_pareto_'+workload+'.'+suffix),dpi=180)
            plt.close(fig)
    progress={'updated_unix':time.time(),'allocation':allocation,'slurm':queue.stdout.splitlines(),'states':states,
              'valid_rounds':sum(r['valid'] for r in rows),'accepted_points':len(points),
              'measurement_kind':'real_KV_full_resident_decode_only_windows','serving_measurements_reused':False}
    (dest/'progress.json').write_text(json.dumps(progress,indent=2)+'\n')
    text=['# Muse decode-only 测试', '', '这是独立新测量，尚未完成；不复用之前包含 prefill 的服务曲线。', '',
          '更新时间：'+time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime()),'',
          f'累计申请 {allocation["requested_nodes"]} 个节点；完成 {sum(r["valid"] for r in rows)} 个有效重复、{len(points)} 个满足重复要求的测点。', '',
          '## 调度实况', '', '```',queue.stdout.strip(),'```','',
          '## 定义', '',
          '每批实际完成 prefill 并生成 1024 tokens。取所有请求都进入 decode 的共同区间，额外剔除每个请求首尾各 64 tokens；区间内不补入新请求。检查 native KV retraction 计数未增加。', '',
          '每重复热身至少 60 秒有效 decode；正式累计至少 120 秒有效 decode 和 32 个成功请求。不同批次之间 prefill/refill/排空时间不计入分母。这是多个纯 decode 区间之和，并非连续 120 秒的闭环 serving 窗口。', '',
          '横轴是区间内逐请求解码速度中位数；纵轴是区间内实际 native output token 增量之和 / 区间时长之和 / 物理 GPU 数。保留 reasoning、输出、逐 token 时间戳、完整原始请求、GPU 与后台遥测。', '',
          '投机对照保持采样参数不变，使用 NGRAM 原生 target-only 验证路径；移除不受支持的 draft_probs rejection 路径。对照双方均固定 decode graph max batch 32，防止之前 8 GiB verify page-table 分配失败。', '',
          '服务器接入/流式传输仍有开销，本图不声称是 CUDA kernel 的纯设备计时。硬件、模型、并行和上下文未与 DeepInfer 对齐，不直接作吞吐倍数比较。', '',
          '配置与控制器：[测试代码](../../performance/muse_decode_20261029/README.md)。原始详细状态：[progress.json](progress.json)。']
    if points:text += ['', '![decode curve](decode_pareto_synthetic.png)', '', '![coding decode curve](decode_pareto_coding.png)']
    (dest/'README.zh-CN.md').write_text('\n'.join(text)+'\n')
    git('add','--sparse','--','evidence/muse_decode_perf_20261029')
    git('-c','user.name=Zhiyuan Hu','-c','user.email=29817400+zhiyuanhubj@users.noreply.github.com','commit','-m','Update independent Muse decode-only measurement progress')
    print(git('push','origin','HEAD:main').stderr,flush=True)


if __name__=='__main__':main()
