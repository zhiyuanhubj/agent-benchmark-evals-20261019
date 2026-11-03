"""Build the exact DeepInfer FlashMLA dependency and call its real CUDA entrypoints."""
import json,os,subprocess,sys,time,traceback
from pathlib import Path

STATE=Path('/evidence');WORK=Path('/work')
PIN='2e5429fc5653bab6e081f09477126f731882a6a9'
def save(phase,**kw):
 p=STATE/'probe-result.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps({'utc':time.time(),'phase':phase,'flashmla_commit':PIN,'valid_performance_points':0,**kw},indent=2));tmp.replace(p)
def run(args,**kw):return subprocess.run(args,check=True,text=True,**kw)

if '--kernel-call' in sys.argv:
 import torch,flash_mla
 from flash_mla import flash_mla_sparse_fwd,flash_mla_with_kvcache
 from flash_mla.flash_mla_interface import FlashMLASchedMeta
 assert str(Path(flash_mla.__file__).resolve()).startswith('/work/site/'),'Must probe the freshly built pinned dependency'
 info={'torch':torch.__version__,'cuda':torch.version.cuda,'capability':torch.cuda.get_device_capability(),'device':torch.cuda.get_device_name(),'module':flash_mla.__file__};results=[]
 for name in ('prefill','decode'):
  try:
   if name=='prefill':
    q=torch.zeros((1,64,512),dtype=torch.bfloat16,device='cuda');kv=torch.zeros((1,1,512),dtype=torch.bfloat16,device='cuda');ix=torch.zeros((1,1,128),dtype=torch.int32,device='cuda')
    flash_mla_sparse_fwd(q,kv,ix,512**-.5)
   else:
    q=torch.zeros((1,1,64,512),dtype=torch.bfloat16,device='cuda');kv=torch.zeros((1,64,1,528),dtype=torch.uint8,device='cuda');ix=torch.zeros((1,1,128),dtype=torch.int32,device='cuda')
    flash_mla_with_kvcache(q,kv,None,None,512,FlashMLASchedMeta(),indices=ix)
   torch.cuda.synchronize();results.append({'entrypoint':name,'success':True})
  except Exception as exc:results.append({'entrypoint':name,'success':False,'error':type(exc).__name__+': '+str(exc)})
 save('operator_probe_passed_engine_not_yet_validated' if all(x['success'] for x in results) else 'operator_probe_failed_h200_port_required',hardware=info,operator_results=results,full_model_inference_attempted=False)
 raise SystemExit(0)

try:
 import torch
 save('checking_build_environment',hardware={'torch':torch.__version__,'cuda':torch.version.cuda,'capability':torch.cuda.get_device_capability(),'device':torch.cuda.get_device_name()})
 source=WORK/'FlashMLA'
 if not (source/'.git').exists():run(['git','clone','--filter=blob:none','https://github.com/deepseek-ai/FlashMLA.git',str(source)])
 run(['git','-C',str(source),'checkout','--detach',PIN]);run(['git','-C',str(source),'submodule','update','--init','--recursive','--depth','1'])
 env=os.environ.copy();env.update(FLASH_MLA_BUILD_TARGET_PLATFORM='CUDA',MAX_JOBS='8',NVCC_THREADS='2',PIP_CACHE_DIR=str(WORK/'pip-cache'))
 # The serving image uses CUDA 13.0; this pinned upstream dependency requires
 # NVCC >=13.1. Keep the newer toolchain in this probe's disposable NVMe tree.
 save('preparing_isolated_cuda_13_2_toolchain')
 compiler=WORK/'compiler'
 run([sys.executable,'-m','pip','install','--target',str(compiler),
      *[n+'==13.2.86' for n in ('nvidia-cuda-nvcc','nvidia-cuda-runtime','nvidia-cuda-crt','nvidia-nvvm')]],env=env)
 nvcc=next(p for p in compiler.rglob('nvcc') if p.is_file());cuda_home=nvcc.parent.parent
 includes=next(compiler.rglob('cuda_runtime.h')).parent
 if not (cuda_home/'include').exists():(cuda_home/'include').symlink_to(includes,target_is_directory=True)
 if not (cuda_home/'lib64').exists():
  libs=cuda_home/'lib'
  (cuda_home/'lib64').symlink_to(libs if libs.exists() else Path('/usr/local/cuda/lib64'),target_is_directory=True)
 cudart=next(compiler.rglob('libcudart.so.*'));link=cuda_home/'lib64/libcudart.so'
 if not link.exists():link.symlink_to(cudart)
 for tool in ('cuobjdump','nvdisasm'):
  target=cuda_home/'bin'/tool;original=Path('/usr/local/cuda/bin')/tool
  if not target.exists() and original.exists():target.symlink_to(original)
 env.update(CUDA_HOME=str(cuda_home),PATH=str(nvcc.parent)+':'+env['PATH'],CPATH='/usr/local/cuda/include:/usr/local/cuda/include/cccl')
 (STATE/'TOOLCHAIN.json').write_text(json.dumps({'cuda_home':str(cuda_home),'nvcc':str(nvcc),'packages_version':'13.2.86'},indent=2))
 save('building_pinned_flashmla')
 wheels=WORK/'wheels';wheels.mkdir(exist_ok=True)
 run([sys.executable,'-m','pip','wheel','--no-build-isolation','--no-deps','--wheel-dir',str(wheels),str(source)],env=env)
 wheel=next(wheels.glob('flash_mla-*.whl'));run([sys.executable,'-m','pip','install','--no-deps','--target',str(WORK/'site'),str(wheel)],env=env)
 env['PYTHONPATH']=str(WORK/'site');run([sys.executable,str(STATE/'deepinfer_probe_inside.py'),'--kernel-call'],env=env)
except Exception as exc:
 save('dependency_build_or_import_failed',error=type(exc).__name__+': '+str(exc),full_model_inference_attempted=False);traceback.print_exc();raise SystemExit(1)
