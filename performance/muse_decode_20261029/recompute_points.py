#!/usr/bin/env python3
"""Independently reconstruct plotted decode coordinates and SD from numeric exports."""
import argparse,csv,gzip,math,statistics
from collections import defaultdict
from pathlib import Path

KEYS=('precision','workload','input_label','speculative','concurrency')
def read(path):
 opener=gzip.open if path.suffix=='.gz' else open
 with opener(path,'rt',newline='') as f:return list(csv.DictReader(f))
def point_key(row):return tuple(row[k] for k in KEYS)
def round_key(row):return (row['job'],*point_key(row),row['repeat'])
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--out',type=Path);a=p.parse_args()
 rounds=[r for r in read(a.data/'decode_rounds.csv') if r['valid'].lower()=='true'];groups=defaultdict(list);speeds=defaultdict(list);windows=defaultdict(list)
 for r in rounds:groups[point_key(r)].append(r)
 for r in read(a.data/'decode_request_speeds.csv.gz'):speeds[round_key(r)].append(float(r['decode_tokens_s_user']))
 for r in read(a.data/'decode_windows.csv.gz'):windows[round_key(r)].append(r)
 result=[]
 for published in read(a.data/'decode_points.csv'):
  rs=groups[point_key(published)];samples=[];counts=[];seconds=[];round_x=[];round_y=[];gpus=8 if published['precision']=='nvfp4' else 16
  for r in rs:
   key=round_key(r);sample=speeds[key];assert sample,key;samples.extend(sample);ws=windows[key];assert ws,key
   tokens=sum(int(w['actual_output_tokens']) for w in ws);duration=sum(float(w['decode_seconds']) for w in ws)
   assert tokens==int(r['actual_output_tokens']);assert math.isclose(duration,float(r['decode_seconds']),rel_tol=1e-10)
   counts.append(tokens);seconds.append(duration);round_x.append(statistics.median(sample));round_y.append(tokens/duration/gpus)
  computed={'decode_p50':statistics.median(samples),'tokens_s_gpu':sum(counts)/sum(seconds)/gpus,'decode_sd':statistics.stdev(round_x),'throughput_sd':statistics.stdev(round_y)}
  assert len(rs)==int(published['repeats'])
  for field,value in computed.items():assert math.isclose(value,float(published[field]),rel_tol=1e-9,abs_tol=1e-10),(point_key(published),field,value,published[field])
  result.append({**{k:published[k] for k in KEYS},'repeats':len(rs),**computed})
 if a.out:
  with a.out.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
 print(f'Verified all {len(result)} plotted decode points, both axes and both SD error bars.')
if __name__=='__main__':main()
