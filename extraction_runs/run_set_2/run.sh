#!/bin/bash

set -e -o pipefail

export OLLAMA_HOST=codon-gpu-008 

ollama run qwen3.5:27b --keepalive 8h ''
extract_protocols ~/nobackup/expert_pdb \
    --pmc-ids PMC5111852,PMC9813973,PMC6057156,PMC5940772,PMC5231405,PMC13224165 \
    --ollama-url http://codon-gpu-008:11434 --ollama-model qwen3.5:27b --force --store-prompts \
    --stats-run-id 10 --stats-df-parquet ~/nobackup/expert_pdb/stats_1.parquet
ollama stop qwen3.5:27b

ollama run qwen3.6:27b --keepalive 8h ''
extract_protocols ~/nobackup/expert_pdb \
    --pmc-ids PMC5111852,PMC9813973,PMC6057156,PMC5940772,PMC5231405,PMC13224165 \
    --ollama-url http://codon-gpu-008:11434 --ollama-model qwen3.6:27b --force --store-prompts \
    --stats-run-id 11 --stats-df-parquet ~/nobackup/expert_pdb/stats_1.parquet
ollama stop qwen3.6:27b


