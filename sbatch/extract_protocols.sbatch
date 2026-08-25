#!/bin/env bash

#SBATCH --time=1-
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=32G
#SBATCH --gres=gpu:a100
#SBATCH -J "expert_pdb_protocols"
#SBATCH -o "/homes/evgeny/nobackup/log/%x_%j.out"
#SBATCH -e "/homes/evgeny/nobackup/log/%x_%j.err"

set -e -o pipefail
. ~/.bashrc

cd ~/code/expert_pdb
micromamba activate expert-pdb
OLLAMA_NUM_PARALLEL=1 nohup ollama serve >~/log/ollama.log 2>&1 &
extract_protocols ~/nobackup/expert_pdb --ollama-model qwen3.6:27b --force
