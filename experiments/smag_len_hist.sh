#!/bin/bash

#SBATCH --job-name=EvalD
#SBATCH --account=escience
#SBATCH --output=/mmfs1/home/kmrakovc/Results/Asteroids/evaluating.txt
#SBATCH --partition=gpu-rtx6k
#SBATCH --cpus-per-task=10
#SBATCH --gres=gpu:2
#SBATCH --time=72:00:00

source ~/activate.sh
module load cuda/12.3.2
python3 mag_len_hist.py --model_path ../DATA/Trained_model_18796700.keras