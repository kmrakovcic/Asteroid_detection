#!/bin/bash

#SBATCH --job-name=EvalD
#SBATCH --mail-type=END,FAIL
#SBATCH --account=escience
#SBATCH --output=/mmfs1/home/kmrakovc/Results/Asteroids/evaluating.txt
#SBATCH --partition=gpu-rtx6k
#SBATCH --cpus-per-task=10
#SBATCH --gres=gpu:2
#SBATCH --time=24:00:00

source ~/activate.sh
python3 mag_len_hist.py \
--model_path ../DATA/Trained_model_18796700.keras \
--tf_dataset_path ../DATA/test1.tfrecord \
--collection u/kmrakovc/single_frame_injection_01
