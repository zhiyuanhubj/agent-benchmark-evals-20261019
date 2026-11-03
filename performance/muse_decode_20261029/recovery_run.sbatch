#!/bin/bash
#SBATCH --account=xgen-mm
#SBATCH --partition=ml.p5en.48xlarge
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=96
#SBATCH --gpus-per-node=h200:8
#SBATCH --mem=0
#SBATCH --exclusive
#SBATCH --requeue
#SBATCH --time=12:00:00
set -euo pipefail
exec /fsx/home/zhiyuan/AgentCompass/.venv/bin/python -u /fsx/home/zhiyuan/.private/muse_decode_perf_20261029/recovery_entry.py --state "$1"
