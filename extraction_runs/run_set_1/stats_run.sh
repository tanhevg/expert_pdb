#!/bin/bash

OLLAMA_HOST=codon-gpu-014 ollama run qwen3.5:9b --keepalive 8h ''
extract_protocols ~/nobackup/expert_pdb \
    --pmc-ids PMC5111852,PMC9813973,PMC6057156,PMC5940772,PMC5231405,PMC13224165 \
    --ollama-url http://codon-gpu-014:11434 --ollama-model qwen3.5:9b --force \
    --stats-run-id 3 --stats-df-parquet ~/nobackup/expert_pdb/stats_1.parquet
OLLAMA_HOST=codon-gpu-014 ollama stop qwen3.5:9b

OLLAMA_HOST=codon-gpu-014 ollama run qwen3.5:27b --keepalive 8h ''
extract_protocols ~/nobackup/expert_pdb \
    --pmc-ids PMC5111852,PMC9813973,PMC6057156,PMC5940772,PMC5231405,PMC13224165 \
    --ollama-url http://codon-gpu-014:11434 --ollama-model qwen3.5:27b --force \
    --stats-run-id 4 --stats-df-parquet ~/nobackup/expert_pdb/stats_1.parquet
OLLAMA_HOST=codon-gpu-014 ollama stop qwen3.5:27b