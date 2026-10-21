#!/bin/bash
#SBATCH --account=xgen-mm
#SBATCH --partition=ml.p5en.48xlarge
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=96
#SBATCH --gpus-per-node=h200:8
#SBATCH --mem=0
#SBATCH --exclusive
#SBATCH --time=7-00:00:00
#SBATCH --output=/fsx/home/zhiyuan/bench/tb21_v1_four_models_20261012/logs/allocation-%j.log
set -euo pipefail
hostname
# Remain available for the allocation's actual lifetime, including backfill.
# Slurm enforces the granted time limit and terminates this process at expiry.
sleep infinity
