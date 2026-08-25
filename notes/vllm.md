# Overview
VLLM is another LLM runner, with similar functionality as Ollama. It was proposed by Gemini AI when I complained to it that ollama is slow.  https://vllm.ai/; https://docs.vllm.ai/en/stable/api/vllm/#vllm.LLM.generate; https://docs.vllm.ai/en/latest/serving/offline_inference/.

# Installation
Installing VLLM is turned out to be not that simple. It comes as a python package with lots of dependencies, including torch, cuda, huggingface/transofrmers and others. VLLM is in active development. One issue is that it relies on the most recent versions of torch and cuda, and these versions are not supported by the EBI cluster. I ended up with two workarounds.

## Using singularity/docker

```
srun -t 120 --mem 64g singularity pull ~/nobackup/singularity-containers/vllm/vllm-openai_v0.27.1.sif  docker://vllm/vllm-openai:v0.27.1
```
This takes about 30 minutes, and generates a sif file of about 7.5G. Note the huge memory requirement, it is necessary

To run:
```
singulairty run --nv \
  --env VLLM_ENABLE_CUDA_COMPATIBILITY=1 \
  --env LD_LIBRARY_PATH="/usr/local/cuda/compat/lib.real:/usr/local/cuda/compat/lib:$LD_LIBRARY_PATH" \
  --bind /homes/evgeny/nobackup/huggingface:/root/.cache/huggingface \
  ~/nobackup/singularity-containers/vllm/vllm-openai_v0.27.1.sif \
  --model Qwen/Qwen3.5-9B
```
`/homes/evgeny/nobackup/huggingface` is the path for the downloaded huggingface models, for running locally we would set `HF_HOME=/homes/evgeny/nobackup/huggingface`. 

We need cuda compat (both env var and libraries) because the cuda driver installed at EBI is too old for VLLM.

## Local installation

This is even trickier. I ended up creating a conda env with python=3.11. I might have used a fresher python, but I got fed up with reinstalling the env. Then, for cuda compat, I had to `conda install -c conda-forge cuda-compat`. Then, to use vllm version that supports cuda 12, I had to use 

```
~/uv/uv pip install \
    https://github.com/vllm-project/vllm/releases/download/v$0.27.1/vllm-0.27.1+cu129-cp38-abi3-manylinux_2_28_x86_64.whl \
    --extra-index-url https://download.pytorch.org/whl/cu129
```

For some reason this creates an environment that needs a newer libstdc++. sqlite blows up without it. To give it a new libstdc++ I need to pull libraries form a more recent gcc module:

```
export LD_LIBRARY_PATH=/hps/software/spack/opt/spack/linux-rhel9-cascadelake/gcc-11.2.0/gcc-14.2.0-lwfz56aikpunnn56j24sziq4gzrvizji/lib64:${LD_LIBRARY_PATH}
```

The version of `flashinfer` that gets installed has a bug, so I had to manually edit the source and add `from __future__ import annotations` on top of `flashinfer/comm/fd_exchange.py`. 

Once all that is done, export the correct values for `VLLM_ENABLE_CUDA_COMPATIBILITY` and `HF_HOME`, and it should all fly.