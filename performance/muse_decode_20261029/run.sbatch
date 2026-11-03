#!/bin/bash
#SBATCH --account=xgen-mm
#SBATCH --partition=ml.p5en.48xlarge
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=96
#SBATCH --gpus-per-node=h200:8
#SBATCH --mem=0
#SBATCH --exclusive
#SBATCH --time=2-00:00:00
set -euo pipefail
DECODE_STATE="$1"
for attempt in $(seq 1 60); do
 if test -f "$DECODE_STATE/READY.json"; then
  exec /fsx/home/zhiyuan/AgentCompass/.venv/bin/python -u /fsx/home/zhiyuan/.private/muse_decode_perf_20261029/control.py --state "$DECODE_STATE"
 fi
 sleep 30
done
echo 'Decode controller readiness deadline exceeded' >&2
exit 1
