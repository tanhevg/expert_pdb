#!/bin/env bash

#SBATCH --time=08:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=32G
#SBATCH --gres=gpu:a100
#SBATCH -J "ollama"
#SBATCH -o "/homes/evgeny/nobackup/log/%x_%j.out"
#SBATCH -e "/homes/evgeny/nobackup/log/%x_%j.err"

set -e -o pipefail

. ~/.bashrc
OLLAMA_HOST="${HOSTNAME}" OLLAMA_NUM_PARALLEL=1 ollama serve > ~/log/ollama.log 2>&1
