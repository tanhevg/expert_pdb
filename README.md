# TODO
Use PubMed Central Article Dataset on Amazon S3 instead of Europe PMC
https://pmc-oa-opendata.s3.amazonaws.com/README.txt
https://docs.aws.amazon.com/boto3/latest/guide/s3-example-download-file.html

# Expert PDB

`expert-pdb` retrieves open-access publications that are linked to Protein Data Bank
entries. By default it processes only the depositor-linked primary citation, then
downloads Europe PMC JATS XML, an OA PDF when PMC supplies one, and the available
supplementary-material archive.

It never attempts to bypass a paywall or obtain text from a publisher site.

## Setup

```sh
micromamba create -n expert-pdb -c conda-forge python=3.12 pip
micromamba run -n expert-pdb python -m pip install -e '.[dev]'
```

## Usage

Run the downloader module with an output directory. It downloads the PDB-to-PubMed
mapping on the first run, resolves PubMed IDs to PMC IDs, then downloads the latest
open PMC package for every matching publication:

```sh
micromamba run -n expert-pdb python -m expert_pdb.download_publications data/runs/example
```

To process particular PDB entries, pass one or more identifiers. Comma-separated
identifiers are also accepted:

```sh
micromamba run -n expert-pdb python -m expert_pdb.download_publications \
  data/runs/selected --pdb-ids 1abc 2def,3ghi
```

For a random sample of publications, use `--num-publications`:

```sh
micromamba run -n expert-pdb python -m expert_pdb.download_publications \
  data/runs/sample --num-publications 100
```

The target directory contains `download_state.parquet`, the cached mapping file, and
downloaded packages under `publications/`. Re-run the same command with the same
target directory to resume unfinished PMC-ID resolution and downloads.

## Protocol extraction

With Ollama already running and the selected model pulled, extract JATS-based protein
production protocols from a downloader output directory:

```sh
micromamba run -n expert-pdb python -m expert_pdb.extract_protocols data/runs/example
```

The extractor uses `qwen3:14b` at `http://localhost:11434` by default. Override these
for a remote Ollama server or another local model:

```sh
micromamba run -n expert-pdb python -m expert_pdb.extract_protocols \
  data/runs/example --pdb-ids 1abc,2def \
  --ollama-url http://ollama.example:11434 --ollama-model qwen3:14b
```

Use `--pmc-ids` to select publications directly. Successful PMC/package versions are
skipped on later runs; pass `--force` to replace that publication's derived rows. The
output directory receives host-specific Expert Parquets, protocol and construct
Parquets, `extraction_state.parquet`, and raw model JSON under `llm_runs/`.
