#!/bin/bash
#SBATCH --account=xgen-mm
#SBATCH --partition=ml.p5en.48xlarge
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=96
#SBATCH --gpus-per-node=h200:8
#SBATCH --mem=0
#SBATCH --exclusive
#SBATCH --time=02:00:00
#SBATCH --time-min=01:00:00
set -uo pipefail
/fsx/home/zhiyuan/AgentCompass/.venv/bin/python -u /fsx/home/zhiyuan/.private/muse_decode_perf_20261029/deepinfer_probe_entry.py --state "$1"
task_rc=$?
/fsx/home/zhiyuan/AgentCompass/.venv/bin/python -u /fsx/home/zhiyuan/.private/muse_decode_perf_20261029/retain_allocation.py --state "$1" --returncode "$task_rc"
exit "$task_rc"
