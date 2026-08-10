#!/bin/env bash

#SBATCH --time=5-
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --mem=16G
#SBATCH -J "download_pdb_publications"
#SBATCH -o "/homes/evgeny/nobackup/log/%x_%j.out"
#SBATCH -e "/homes/evgeny/nobackup/log/%x_%j.err"

set -e -o pipefail

. ~/.bashrc
cd ~/code/expert_pdb
/hps/software/users/chembl/evgeny/micromamba/envs/expert-pdb/bin/python src/expert_pdb/download_publications.py ~/nobackup/expert_pdb/ 
