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
from matrix import planned_points


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
    rows=[];groups=defaultdict(list);states={};prefill_rows=[];prefill_groups=defaultdict(list);active=[];invalid=[]
    for job in jobs:
        state=Path(job['state']);s=state/'status.json'
        states[str(job['job'])]=json.loads(s.read_text()) if s.exists() else {'phase':'queued'}
        frames=[f for path in (state/job['precision']/'gpu').glob('*.jsonl.gz') for f in records(path)]
        for path in state.glob('*/prefill/*/c*/summary.json'):
            r=json.loads(path.read_text());counts=defaultdict(int)
            for f in frames:
                if any(w['engine_start_unix']<=f['unix']<w['engine_end_unix'] for w in r['windows']):
                    for values in f.get('rows',[]):
                        row=dict(zip(f['fields'],values))
                        try:float(row['utilization.gpu']);float(row['memory.used'])
                        except (ValueError,KeyError):continue
                        counts[row['uuid']]+=1
            gpu_ok=len(counts)==r['gpus'] and min(counts.values(),default=0)>=r['engine_seconds']*.8
            d=distribution(r['request_prefill_latencies_s'])
            row={'job':job['job'],'precision':r['precision'],'input_tokens':r['input_tokens'],'concurrency':r['concurrency'],
                 'repeat':r['repeat'],'valid':r['valid'] and gpu_ok,'gpu_telemetry_complete':gpu_ok,
                 'engine_seconds':r['engine_seconds'],'actual_input_tokens':r['actual_input_tokens'],
                 'input_tokens_s_gpu':r['input_tokens_s_gpu'],'prefill_latency_p50_s':d['p50'],'prefill_latency_p95_s':d['p95'],
                 'successful_requests':r['successful_requests'],'artifact':str(path)}
            prefill_rows.append(row)
            if row['valid']:prefill_groups[(r['precision'],r['input_tokens'],r['concurrency'])].append(r)
        for path in state.glob('*/*/*/c*/progress.json'):
            if not (path.parent/'summary.json').exists():active.append({'job':job['job'],'path':str(path),'progress':json.loads(path.read_text())})
        for path in state.glob('*/*/*/c*/INVALID.json'):
            invalid.append({'job':job['job'],'artifact':str(path),'record':json.loads(path.read_text())})
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
    prefill_points=[]
    if prefill_rows:
        with (dest/'prefill_rounds.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(prefill_rows[0]));w.writeheader();w.writerows(prefill_rows)
    for key,rs in sorted(prefill_groups.items()):
        if len(rs)<3:continue
        precision,length,c=key;seconds=sum(r['engine_seconds'] for r in rs);tokens=sum(r['actual_input_tokens'] for r in rs)
        ds=distribution([v for r in rs for v in r['request_prefill_latencies_s']])
        prefill_points.append({'precision':precision,'input_tokens':length,'concurrency':c,'repeats':len(rs),
             'input_tokens_s_gpu':tokens/seconds/rs[0]['gpus'],'engine_seconds':seconds,'actual_input_tokens':tokens,
             'prefill_latency_p50_s':ds['p50'],'prefill_latency_p95_s':ds['p95'],
             'throughput_sd':statistics.stdev(r['input_tokens_s_gpu'] for r in rs),
             'latency_p50_sd':statistics.stdev(distribution(r['request_prefill_latencies_s'])['p50'] for r in rs)})
    if prefill_points:
        with (dest/'prefill_points.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(prefill_points[0]));w.writeheader();w.writerows(prefill_points)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        for kind in ['throughput','pareto']:
            fig,ax=plt.subplots(figsize=(11,7));lines=defaultdict(list)
            for r in prefill_points:
                group=(r['precision'],r['concurrency'] if kind=='throughput' else r['input_tokens'])
                lines[group].append(r)
            for key,values in sorted(lines.items()):
                values.sort(key=lambda r:r['input_tokens'] if kind=='throughput' else r['concurrency'])
                xs=[r['input_tokens']/1024 if kind=='throughput' else r['prefill_latency_p50_s'] for r in values]
                label=f'{key[0]} / C={key[1]}' if kind=='throughput' else f'{key[0]} / {key[1]//1024}K'
                ax.errorbar(xs,[r['input_tokens_s_gpu'] for r in values],
                    xerr=None if kind=='throughput' else [r['latency_p50_sd'] for r in values],
                    yerr=[r['throughput_sd'] for r in values],marker='o',capsize=3,label=label)
                if kind=='pareto':
                    for x,r in zip(xs,values):ax.annotate('C='+str(r['concurrency']),(x,r['input_tokens_s_gpu']),xytext=(5,5),textcoords='offset points',fontsize=8)
            ax.set_xlabel('Input length (Ki tokens)' if kind=='throughput' else 'Native prefill phase latency p50 (seconds/request)')
            ax.set_ylabel('Actual input tokens / native prefill phase seconds / GPU')
            xmax=max(r['input_tokens']/1024 if kind=='throughput' else r['prefill_latency_p50_s']+3*r['latency_p50_sd'] for r in prefill_points)
            ymax=max(r['input_tokens_s_gpu']+3*r['throughput_sd'] for r in prefill_points)
            ax.set_xlim(0,xmax*1.15);ax.set_ylim(0,ymax*1.15)
            ax.set_title('Muse prefill-only cohorts — IN PROGRESS\n1 output token; includes engine scheduling + first-token sampling; error bars: repetition SD')
            ax.grid(alpha=.25);ax.legend(fontsize=8);fig.tight_layout()
            for suffix in ['png','pdf','svg']:fig.savefig(dest/('prefill_'+kind+'.'+suffix),dpi=180)
            plt.close(fig)
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
    planned=planned_points(allocation)
    for target in planned:
        key=(target['precision'],target['workload'],target['input_label'],target['speculative'],target['concurrency'])
        target['valid_repeats']=len(groups.get(key,[]))
        target['status']='complete' if target['valid_repeats']>=target['required_repeats'] else ('partial' if target['valid_repeats'] else 'pending_or_above_unresolved_boundary')
    with (dest/'decode_matrix.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(planned[0]));w.writeheader();w.writerows(planned)
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
        from matplotlib.lines import Line2D
        colors={'nvfp4':'#2868d8','bf16':'#d26823'}
        for workload,labels in [('synthetic',['8192','32768','65536','131072']),
                                ('coding',['native-0-8192','native-8192-32768'])]:
            fig,axes=plt.subplots(2 if workload=='synthetic' else 1,2,figsize=(13,9 if workload=='synthetic' else 6),squeeze=False)
            selected=[r for r in points if r['workload']==workload]
            xmax=max((r['decode_p50']+3*r['decode_sd'] for r in selected),default=80)*1.15
            ymax=max((r['tokens_s_gpu']+3*r['throughput_sd'] for r in selected),default=100)*1.15
            for ax,label in zip(axes.flat,labels):
                subset=[r for r in selected if r['input_label']==label]
                for precision in ['nvfp4','bf16']:
                    for spec in (['off'] if workload=='synthetic' else ['off','NGRAM']):
                        ps=sorted([r for r in subset if r['precision']==precision and r['speculative']==spec],key=lambda r:r['concurrency'])
                        if not ps:continue
                        ax.errorbar([r['decode_p50'] for r in ps],[r['tokens_s_gpu'] for r in ps],
                            xerr=[r['decode_sd'] for r in ps],yerr=[r['throughput_sd'] for r in ps],
                            color=colors[precision],linestyle='-' if spec=='off' else '--',marker='o',capsize=3)
                        for r in ps:ax.annotate(str(r['concurrency']),(r['decode_p50'],r['tokens_s_gpu']),xytext=(4,5),textcoords='offset points',fontsize=7)
                ax.set_title(f'{int(label)//1024}K real input context' if workload=='synthetic' else label)
                ax.set_xlim(0,xmax);ax.set_ylim(0,ymax);ax.grid(alpha=.25)
                if not subset:ax.text(.5,.5,'Awaiting required valid repetitions',ha='center',transform=ax.transAxes,fontsize=9)
            handles=[Line2D([],[],color=colors[p],marker='o',label=p+' / '+('8' if p=='nvfp4' else '16')+' x H200') for p in colors]
            if workload=='coding':handles += [Line2D([],[],color='#555555',linestyle=s,label=l) for s,l in [('-','Spec OFF'),('--','NGRAM')]]
            fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,.935 if workload=='synthetic' else .895),ncol=len(handles),fontsize=9)
            fig.suptitle('Muse decode-only curves — IN PROGRESS\nFixed model/framework/parallel/KV configuration per line; labels: concurrency; error bars: repeat SD',fontsize=13,y=.995)
            fig.supxlabel('Per-request decode speed p50 (output tokens/s/user)',y=.035)
            fig.supylabel('Actual decode-window output tokens / decode-window seconds / GPU',x=.025)
            fig.subplots_adjust(left=.085,right=.98,top=.85 if workload=='synthetic' else .78,bottom=.105,wspace=.17,hspace=.25)
            for suffix in ['png','pdf','svg']:fig.savefig(dest/('decode_pareto_'+workload+'_panels.'+suffix),dpi=180)
            plt.close(fig)
    progress={'updated_unix':time.time(),'allocation':allocation,'slurm':queue.stdout.splitlines(),'states':states,
              'valid_rounds':sum(r['valid'] for r in rows),'accepted_points':len(points),
              'prefill_valid_rounds':sum(r['valid'] for r in prefill_rows),'prefill_accepted_points':len(prefill_points),
              'active_measurements':active,'invalid_attempts':invalid,
              'planned_configuration_groups':len({(r['precision'],r['workload'],r['input_label'],r['speculative']) for r in planned}),
              'planned_configuration_points_upper_bound':len(planned),
              'planned_repetitions_upper_bound':sum(r['required_repeats'] for r in planned),
              'dense_followups':{str(j['job']):json.loads((Path(j['state'])/'DENSE_EXTENSION.json').read_text()) for j in jobs if (Path(j['state'])/'DENSE_EXTENSION.json').exists()},
              'prefill_followups':{str(j['job']):json.loads((Path(j['state'])/'PREFILL_FOLLOWUP.json').read_text()) for j in jobs if (Path(j['state'])/'PREFILL_FOLLOWUP.json').exists()},
              'measurement_kind':'real_KV_full_resident_decode_only_windows','serving_measurements_reused':False}
    (dest/'progress.json').write_text(json.dumps(progress,indent=2)+'\n')
    text=['# Muse decode-only 测试', '', '这是独立新测量，尚未完成；不复用之前包含 prefill 的服务曲线。', '',
          '更新时间：'+time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime()),'',
          f'累计申请 {allocation["requested_nodes"]} 个节点；完成 {sum(r["valid"] for r in rows)} 个有效重复、{len(points)} 个满足重复要求的测点。', '',
          '## 调度实况', '', '```',queue.stdout.strip(),'```','',
          '## 多组、多点矩阵', '',
          'NVFP4/BF16 × 8K/32K/64K/128K，共 8 组基础曲线；每组目标并发 1、2、4、8、16、32、64、128、256。coding 的两个实际长度桶 × 两种精度 × 投机开关，另有 8 组曲线，各目标并发 1、2、4、8、16、32。', '',
          f'上限共 {len(planned)} 个独立配置点、{sum(r["required_repeats"] for r in planned)} 次重复。实际遇到 KV、延迟或稳定性边界时保留失败记录并明确标注，不能把未测试点补成完成，也不宣称达到全硬件峰值。', '',
          '逐点计划与完成次数：[decode_matrix.csv](decode_matrix.csv)。当前 32K 的三点扫描正常继续；随后在同一热模型实例补测余下并发，原始记录保留。', '',
          '## 定义', '',
          '每批实际完成 prefill 并生成 1024 tokens。取所有请求都进入 decode 的共同区间，额外剔除每个请求首尾各 64 tokens；区间内不补入新请求。检查 native KV retraction 计数未增加。', '',
          '每重复热身至少 60 秒有效 decode；正式累计至少 120 秒有效 decode 和 32 个成功请求。不同批次之间 prefill/refill/排空时间不计入分母。这是多个纯 decode 区间之和，并非连续 120 秒的闭环 serving 窗口。', '',
          '横轴是区间内逐请求解码速度中位数；纵轴是区间内实际 native output token 增量之和 / 区间时长之和 / 物理 GPU 数。保留 reasoning、输出、逐 token 时间戳、完整原始请求、GPU 与后台遥测。', '',
          '投机对照保持采样参数不变，使用 NGRAM 原生 target-only 验证路径；移除不受支持的 draft_probs rejection 路径。对照双方均固定 decode graph max batch 32，防止之前 8 GiB verify page-table 分配失败。', '',
          '服务器接入/流式传输仍有开销，本图不声称是 CUDA kernel 的纯设备计时。硬件、模型、并行和上下文未与 DeepInfer 对齐，不直接作吞吐倍数比较。', '',
          '配置与控制器：[测试代码](../../performance/muse_decode_20261029/README.md)。原始详细状态：[progress.json](progress.json)。']
    if points:text += ['', '![decode context groups](decode_pareto_synthetic_panels.png)', '',
                      '![coding decode groups](decode_pareto_coding_panels.png)', '',
                      '[全部 context 曲线叠加](decode_pareto_synthetic.png)；[coding 曲线叠加](decode_pareto_coding.png)。']
    text += ['', '## Prefill 独立测量', '',
             f'已完成 {sum(r["valid"] for r in prefill_rows)} 个有效重复、{len(prefill_points)} 个三重复测点。', '',
             '每请求实际 prefill 完整输入，只生成 1 token，不混入后续 decode 工作。分母取 native `forward_entry_time` 至 `prefill_finished_time` 的整批包络；分子为该批 native `prompt_tokens` 之和。保存客户端耗时，但不拿 TTFT 代替这个 native prefill 阶段计时。', '',
             '该阶段计时包括 chunk 调度和首 token sampling，属于 engine 阶段 wall time，不宣称是独立 CUDA kernel 时间。每重复热身至少 60 秒，正式累计至少 120 秒及 32 个请求，三重复后画图，保留 GPU/后台遥测。']
    if prefill_points:text += ['', '![prefill throughput](prefill_throughput.png)', '', '![prefill Pareto](prefill_pareto.png)']
    (dest/'README.zh-CN.md').write_text('\n'.join(text)+'\n')
    git('add','--sparse','--','evidence/muse_decode_perf_20261029')
    git('-c','user.name=Zhiyuan Hu','-c','user.email=29817400+zhiyuanhubj@users.noreply.github.com','commit','-m','Update independent Muse decode-only measurement progress')
    print(git('push','origin','HEAD:main').stderr,flush=True)


if __name__=='__main__':main()
