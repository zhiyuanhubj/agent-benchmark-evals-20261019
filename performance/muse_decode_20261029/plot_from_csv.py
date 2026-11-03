#!/usr/bin/env python3
"""Replot published numeric values offline; no Slurm, model, or private paths required."""
import argparse,csv
from collections import defaultdict
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

COLORS={'nvfp4':'#2868d8','bf16':'#d26823'}
def read(path):
 return list(csv.DictReader(path.open(newline=''))) if path.exists() else []
def save(fig,out,name):
 fig.savefig(out/(name+'.png'),dpi=180)
 fig.savefig(out/(name+'.pdf'))
 fig.savefig(out/(name+'.svg'))
 plt.close(fig)
def decode(rows,out,workload):
 selected=[r for r in rows if r['workload']==workload]
 labels=['8192','32768','65536','131072'] if workload=='synthetic' else ['native-0-8192','native-8192-32768']
 fig,axes=plt.subplots(2 if workload=='synthetic' else 1,2,figsize=(13,9 if workload=='synthetic' else 6),squeeze=False)
 xmax=max((float(r['decode_p50'])+3*float(r['decode_sd']) for r in selected),default=80)*1.15
 ymax=max((float(r['tokens_s_gpu'])+3*float(r['throughput_sd']) for r in selected),default=100)*1.15
 for ax,label in zip(axes.flat,labels):
  for precision in COLORS:
   for spec in ('off','NGRAM'):
    ps=sorted([r for r in selected if r['input_label']==label and r['precision']==precision and r['speculative']==spec],key=lambda r:int(r['concurrency']))
    if not ps:continue
    gpus=8 if precision=='nvfp4' else 16
    ax.errorbar([float(r['decode_p50']) for r in ps],[float(r['tokens_s_gpu']) for r in ps],xerr=[float(r['decode_sd']) for r in ps],yerr=[float(r['throughput_sd']) for r in ps],color=COLORS[precision],linestyle='-' if spec=='off' else '--',marker='o',capsize=3,label=f'{precision.upper()} / {gpus} H200 / {spec}')
    for r in ps:ax.annotate('C='+r['concurrency'],(float(r['decode_p50']),float(r['tokens_s_gpu'])),xytext=(4,5),textcoords='offset points',fontsize=7)
  ax.set_title(f'{int(label)//1024}K input tokens' if workload=='synthetic' else label.replace('native-','Coding: '))
  ax.set_xlim(0,xmax);ax.set_ylim(0,ymax);ax.grid(alpha=.25)
  if ax.lines:ax.legend(fontsize=7)
 fig.suptitle('Muse decode-only performance: '+workload+'\nMeasured points; labels: global concurrency; error bars: repetition SD',fontsize=13)
 fig.supxlabel('Median per-request decode speed (output tokens/s/user)')
 fig.supylabel('Actual decode-window output tokens / decode-window seconds / GPU')
 fig.tight_layout(rect=(.02,.025,1,.92));save(fig,out,'decode_pareto_'+workload+'_panels')
def prefill(rows,out):
 if not rows:return
 for mode in ('throughput','pareto'):
  fig,ax=plt.subplots(figsize=(11,7));groups=defaultdict(list)
  for r in rows:groups[(r['precision'],r['concurrency'] if mode=='throughput' else r['input_tokens'])].append(r)
  for key,ps in sorted(groups.items()):
   ps.sort(key=lambda r:int(r['input_tokens'] if mode=='throughput' else r['concurrency']))
   xs=[float(r['input_tokens'])/1024 if mode=='throughput' else float(r['prefill_latency_p50_s']) for r in ps]
   ax.errorbar(xs,[float(r['input_tokens_s_gpu']) for r in ps],xerr=None if mode=='throughput' else [float(r['latency_p50_sd']) for r in ps],yerr=[float(r['throughput_sd']) for r in ps],marker='o',capsize=3,label=f'{key[0].upper()} / '+('C='+key[1] if mode=='throughput' else str(int(key[1])//1024)+'K'))
   if mode=='pareto':
    for x,r in zip(xs,ps):ax.annotate('C='+r['concurrency'],(x,float(r['input_tokens_s_gpu'])),xytext=(4,4),textcoords='offset points',fontsize=8)
  ax.set_xlabel('Input length (K tokens)' if mode=='throughput' else 'Native prefill-phase latency P50 (s/request)');ax.set_ylabel('Actual input tokens / native prefill-phase seconds / GPU');ax.set_title('Muse native prefill-only measurements; repetition SD error bars');ax.grid(alpha=.25);ax.legend(fontsize=8);fig.tight_layout();save(fig,out,'prefill_'+mode)
def reference(rows,refs,out):
 if not refs:return
 for scale in ('log','linear'):
  fig,axes=plt.subplots(1,2,figsize=(15,8))
  for ax,label in zip(axes,('8192','131072')):
   for precision in COLORS:
    ps=sorted([r for r in rows if r['workload']=='synthetic' and r['input_label']==label and r['speculative']=='off' and r['precision']==precision],key=lambda r:int(r['concurrency']))
    if not ps:continue
    ax.errorbar([float(r['decode_p50']) for r in ps],[float(r['tokens_s_gpu']) for r in ps],xerr=[float(r['decode_sd']) for r in ps],yerr=[float(r['throughput_sd']) for r in ps],marker='o',capsize=3,color=COLORS[precision],label=f'Muse {precision.upper()} / {8 if precision=="nvfp4" else 16} H200')
   ax.plot([float(r['speed_tokens_s_user_approx']) for r in refs],[float(r['throughput_tokens_s_gpu_approx']) for r in refs],'D--',color='#25845a',label='DeepInfer reference / 64 SM100 / 128K (digitized)')
   ax.set_title('Muse '+str(int(label)//1024)+'K input vs. published reference');ax.set_xlabel('Per-user token rate: definitions differ');ax.set_ylabel('Output tokens/s/GPU: hardware and timing differ');ax.grid(alpha=.25);ax.legend(fontsize=7)
   if scale=='log':ax.set_yscale('log');ax.set_ylim(1,50000)
   else:ax.set_ylim(0,31000)
   ax.set_xlim(0,365)
  fig.suptitle('External reference only: not a matched-hardware comparison',fontsize=14)
  fig.text(.06,.06,'Muse: H200, global concurrency, native output-token increments, per-request P50.\nDeepInfer: 64 SM100, per-DP-rank concurrency, mean step rate multiplied by assumed tau=3.25.\nOfficial-image digitization is not a local H200 measurement; no hardware conversion or speedup ratio.',fontsize=9)
  fig.tight_layout(rect=(0,.14,1,.94));save(fig,out,'decode_vs_deepinfer_'+scale)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 rows=read(a.data/'decode_points.csv');assert rows,'decode_points.csv has no measured points'
 for workload in ('synthetic','coding'):decode(rows,a.out,workload)
 prefill(read(a.data/'prefill_points.csv'),a.out);reference(rows,read(a.data/'reference/deepinfer_digitized_points.csv'),a.out)
 print(f'Rendered {len(rows)} measured decode points into {a.out}')
if __name__=='__main__':main()
