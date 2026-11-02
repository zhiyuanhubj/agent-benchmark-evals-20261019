"""Overlay a pinned, explicitly digitized external reference without normalizing it."""
import csv
import hashlib
import json
import shutil
from pathlib import Path


def reference_points(folder):
    import numpy as np
    from PIL import Image
    folder=Path(folder)
    meta=json.loads((folder/'deepinfer_reference.json').read_text())
    path=folder/'deepinfer_decode_pareto.png'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==meta['image_sha256']
    rgb=np.asarray(Image.open(path).convert('RGB'))
    blue=(rgb[:,:,0]<90)&(rgb[:,:,1]>70)&(rgb[:,:,1]<160)&(rgb[:,:,2]>170)
    fits={axis:np.polyfit([p[1] for p in meta['pixel_axes'][axis+'_ticks']],
                         [p[0] for p in meta['pixel_axes'][axis+'_ticks']],1)
          for axis in ('x','y')}
    out=[]
    for marker in meta['markers']:
        px,py=marker['approx_pixel']
        yy,xx=np.mgrid[py-15:py+16,px-15:px+16]
        mask=blue[py-15:py+16,px-15:px+16]
        scores=[]
        for cy in np.arange(py-3,py+3.01,.25):
            for cx in np.arange(px-3,px+3.01,.25):
                radius=(xx-cx)**2+(yy-cy)**2
                disk=radius<=7.4**2
                # The disk distinguishes a marker from the connecting blue line.
                score=(mask&disk).sum()-2*(~mask&disk).sum()-.05*(mask&(radius>9**2)).sum()
                scores.append((score,cx,cy))
        peak=max(s[0] for s in scores)
        candidates=[s for s in scores if s[0]==peak]
        cx=float(np.mean([s[1] for s in candidates]));cy=float(np.mean([s[2] for s in candidates]))
        x=float(np.polyval(fits['x'],cx));y=float(np.polyval(fits['y'],cy))
        c=marker['requests_per_dp_rank']
        # Independent pixel axes should agree with the published plotting formula.
        assert abs(y-x*c/meta['cp_size'])/(x*c/meta['cp_size'])<.025
        out.append({'requests_per_dp_rank':c,'global_requests':c*meta['dp_size'],
                    'speed_tokens_s_user_approx':round(x,2),'throughput_tokens_s_gpu_approx':round(y,1),
                    'pixel_x':cx,'pixel_y':cy,'data_origin':meta['data_origin']})
    return meta,out


def render_comparison(points,folder,dest):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    meta,reference=reference_points(folder)
    provenance=dest/'reference';provenance.mkdir(exist_ok=True)
    for name in ['deepinfer_reference.json','deepinfer_decode_pareto.png','DeepInfer-LICENSE']:
        shutil.copy2(Path(folder)/name,provenance/name)
    with (provenance/'deepinfer_digitized_points.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(reference[0]));w.writeheader();w.writerows(reference)
    colors={'nvfp4':'#2868d8','bf16':'#d26823'}
    for scale in ('log','linear'):
        fig,axes=plt.subplots(1,2,figsize=(15,8))
        for ax,length in zip(axes,[8192,131072]):
            for precision in ('nvfp4','bf16'):
                ps=sorted([r for r in points if r['precision']==precision and r['workload']=='synthetic'
                           and r['input_label']==str(length) and r['speculative']=='off'],key=lambda r:r['concurrency'])
                if not ps:
                    continue
                ax.errorbar([r['decode_p50'] for r in ps],[r['tokens_s_gpu'] for r in ps],
                            xerr=[r['decode_sd'] for r in ps],yerr=[r['throughput_sd'] for r in ps],
                            color=colors[precision],marker='o',capsize=3,
                            label=f'Muse {precision.upper()} / {8 if precision=="nvfp4" else 16} H200 / {length//1024}K')
                for r in ps:
                    ax.annotate('G'+str(r['concurrency']),(r['decode_p50'],r['tokens_s_gpu']),
                                xytext=(4,5),textcoords='offset points',fontsize=7,color=colors[precision])
            ax.plot([r['speed_tokens_s_user_approx'] for r in reference],
                    [r['throughput_tokens_s_gpu_approx'] for r in reference],
                    color='#25845a',linestyle='--',marker='D',label='DeepInfer official ref. / 64 SM100 / 128K (digitized)')
            for r in reference:
                ax.annotate('D'+str(r['requests_per_dp_rank']),
                            (r['speed_tokens_s_user_approx'],r['throughput_tokens_s_gpu_approx']),
                            xytext=(3,7),textcoords='offset points',fontsize=8,color='#25845a')
            if length==131072 and not any(r['precision']=='bf16' and r['workload']=='synthetic'
                                         and r['input_label']=='131072' for r in points):
                ax.text(.03,.82 if scale=='log' else .95,'Muse BF16 128K: awaiting measurements',transform=ax.transAxes,va='top',fontsize=9)
            ax.set_title('Muse 8K vs reference 128K (different context)' if length==8192 else '128K input context (closest context match)',fontsize=11)
            ax.set_xlabel('Tokens/s/user: Muse request P50; reference mean step rate x assumed tau',fontsize=9)
            ax.set_ylabel('Tokens/s/GPU (hardware and timing differ)',fontsize=10)
            ax.set_xlim(0,365)
            if scale=='log':
                ax.set_yscale('log');ax.set_ylim(1,50000)
            else:
                ax.set_ylim(0,31000)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda y,_:f'{y:,.0f}'))
            ax.grid(alpha=.22,which='both');ax.legend(loc='lower right' if scale=='log' else 'upper right',fontsize=7)
        fig.suptitle('Muse and DeepInfer published decode curves — EXTERNAL REFERENCE ONLY',fontsize=15,y=.98)
        fig.text(.5,.93,'No hardware conversion, no inferred speedup ratio. '+('Logarithmic Y axis.' if scale=='log' else 'Shared linear axes; Muse is compressed near zero.'),ha='center',fontsize=10)
        fig.text(.06,.18,
                 'Muse: SGLang; real KV and streamed token increments; global concurrency G; 8/16 H200; speculative OFF; repeat SD error bars.\n'
                 'DeepInfer: DeepSeek V4.1 Flash; 64 SM100 in one scale-up domain; EP64/DP64; context 131,072; fixed nextn=3.\n'
                 'Reference labels D are requests PER DP RANK: D8 = 512 global, D256 = 16,384 global; not Muse G8/G256.\n'
                 'Reference axes use mean steps/s x tau, tau=1+3 x assumed 75%=3.25; not request P50 or native accepted-token throughput.\n'
                 'Reference values are digitized from the pinned official PNG; no raw repetitions or measurement error bars are available.',
                 fontsize=9,va='top',linespacing=1.5)
        fig.text(.06,.025,'Source: deepseek-ai/DeepInfer @ '+meta['commit'][:12]+'; original image, Apache-2.0 license and pixel provenance included.',fontsize=8)
        fig.subplots_adjust(left=.065,right=.985,top=.86,bottom=.29,wspace=.20)
        for suffix in ('png','pdf','svg'):
            fig.savefig(dest/f'decode_vs_deepinfer_{scale}.{suffix}',dpi=180)
        plt.close(fig)
    report='''# DeepInfer 外部参考曲线

这是官方 PNG 的数字化参考值，不是我们本地运行 DeepInfer 得到的结果，也不是官方原始测量 JSON。
两轴按原图刻度独立换算，保存 marker 像素坐标、标定点、文件 SHA-256 和固定 Git commit；数字化约有 1 像素误差，不伪造重复测试或误差棒。

| 条件 | Muse 本地曲线 | DeepInfer 官方参考 |
|---|---|---|
| 模型 | Muse Spark Open | DeepSeek V4.1 Flash |
| 硬件 | NVFP4 8×H200；BF16 16×H200 | 64×SM100，同一 scale-up 域 |
| 并行 | TP8/EP8 或 TP16/EP16 | EP64/DP64，CP1 |
| 上下文 | 8K/32K/64K/128K | 131,072 |
| 并发标注 | 整个副本全局请求数 G | 每 DP rank 请求数 D；全局为 D×64 |
| 横轴 | 真实流式 Decode 区间内逐请求速度 P50 | 平均 step/s × τ |
| 纵轴 | native 输出 token 增量÷区间时长÷物理 GPU 数 | 平均 step/s × 每 rank 请求数 × τ÷CP |
| 投机 | 基础曲线关闭；coding 单列 NGRAM 对照 | fixed nextn=3，设定接受率75%，τ=3.25 |
| 测量 | 客户端选取所有请求都在 decode 的区间 | engine steady-step benchmark；排除 LB flush 区间 |

不能把同名并发标注视为相同负载，也不能用每 GPU 归一代替硬件、拓扑和统计口径对齐。图中未做 SM100→H200 换算。
128K 面板只对齐了输入长度；仍不能据图计算框架效率或模型速度倍数。

若要比较本地服务体验，应在相同 H200 数量、全局并发、输入输出长度、采样/缓存/投机策略下，用同一流式闭环客户端测两种模型。
这只能比较该部署条件下的模型与框架组合，不能归因为框架本身。官方发布列出的 NVIDIA 支持是 SM100，并未声明 H200 支持，因此不能假定 DeepInfer 可直接在本集群复现。
若要严格重现官方图，需要其支持的硬件与规模、模型和 engine-step 测量协议。

## H200 本地复测

用户要求用现有 H200 进行本地对照；新 H200 曲线只采用本地实际测量，原 SM100 参考数值和标注保留。
DeepSeek + DeepInfer 的 H200 行目前是待实测：固定版本的关键稀疏 Decode 算子要求 SM100f，尚未提交 H200 推理作业。
SGLang 镜像内已找到 DeepSeek V4.1 实现；若采用该框架，会明确标为 SGLang 并先做运行验证。
具体硬件表、固定口径、模型文件版本及源码检查证据见 [H200 本地对照方案](../../../performance/muse_decode_20261029/H200_LOCAL_COMPARISON_20261102.zh-CN.md)。

![shared logarithmic axes](../decode_vs_deepinfer_log.png)

![shared linear axes](../decode_vs_deepinfer_linear.png)

'''
    report+='\n'.join(f'- [{name}]({url})' for name,url in meta['source_links'].items())+'\n'
    (provenance/'README.zh-CN.md').write_text(report)
