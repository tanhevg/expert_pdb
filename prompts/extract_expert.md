# AI extraction of Expert protein-production protocols

## Summary

Add a local-AI protein production protocol extraction stage after publication download. It will create one record per expressed construct, map all available information to the four Expert templates, preserve unmapped facts, and retain source evidence and cited-but-unretrieved protocol references. This information will be used further down the line for fine-tuning the LLM.

## Implementation changes

- Add an `extract_protocols` CLI that reads downloaded PMC packages and writes results under the specified output directory. Optional CLI arguments should allow specifying a list of PDB IDs or list of PMC ids for publications; by default all publications should be processed.
- Use Ollama’s local JSON API with configurable endpoint and model, defaulting to `qwen3:14b` running locally. Allow specifying a different model and running ollama on another host/port. Assume Ollama is started in advance and the configured model is pulled before extraction.
- Use `pdb_pubmed.csv.gz` and `download_state.parquet` in the output dir for mapping between publication PMCID and protein structure PDB id.
- Derive versioned field schemas from Expert metadata: `~/Documents/nicola_paper_2026/Supplementary Sheet S2_26052026.xlsx`. Use the tabs for E. coli, insect, mammalian, and cell-free hosts, as well as buffer representation. Convert these into a hard-coded LLM prompt. Don't write code to formulate the prompt based on the Excel file. Ask the LLM to tell how confident it is in all the fields. Make sure the field types are correct.
- Extract any extra relevant information about the protein production protocol from the publication, that is not captured in the Expert metadata, and record the surplus fields marking them as such.Ask the LLM to tell how confident it is in all the fields.
- Use JATS XML files to extract the protocols. If the protocol details cannot be found there, but instead there is a citation of a supplementary material or another paper, make a note of that. If it is a supplementary material, make an intelligent guess about what file that is, and make a note. If it is a reference, make a note of any identifiers included in the reference (DOI, PMID, PMCID, ...). Do not try to parse the supplement or fetch the reference. There will be a separate CLI to do the parsing.
- Capture as many details as possible about the IDs of the protein that is being produced. Most likely the publication and supplements will not have the construct sequence, and it will have to be reconstructed from the PDB and the gene name, organism, uniprot id, genebank id, etc. There will be another CLI that reads the protein sequences from PDB, prepends/ appends any tags and puts together the construct sequence. Record as much information for it as possible.
- The LLM will be finetuned later, by a separate CLI. Capture the text chunks with protocol details, their location in the publication, the decision about whether the publication contains protocol details, does not contain, or contain in a reference/supplement.
- Produce the following outputs:
  - `expert_records_<host>.parquet` - four dataframes per expression system (host in { e-coli, insect, mammalian,  cell-free}) with Expert fields, plus link to PDB id and publication PMCID
  - `protein_production_protocols.parquet` - the dataframe that lists documents that are confirmed to contain protein production protocol details. Should contain PDB ID, PMCID of the publication, file name and format (JATS, PDF, ...) and protocol text and status (retrieved, missing, supplement, citation) and some human-readable info for citation, like "supplementary methods /path/to/file" or "Reference 42: Smith et al, Science 2024, pmcid=XXX". The CLI that deals with references and supplements will later update this dataframe.
  - `construct_data.parquet` - the dataframe that will be used to put together the construct sequences. Should contain the PDB id, PMC ID, any other ids that can be parsed from the publication (uniprot, geneband, gen name, ...), any tags that could be parsed from the text (N-term and C-term).
  - Create a new subdirectory in the output dir for each LLM run. For each parsed publication, store the json output of the LLM in that directory. This json file should contain all the information, including Expert fields, surplus fields, protein ids, text chunk with protocol details, information about relevant references and supplements, confidence scores. This json will then be used by other CLIs to locate the PDF files for parsing, download and extract other references.
- If the `.parquet` files for the dataframes already exist, read them first and update them; do not override.

## Test plan

- Mock Ollama responses to test schema mapping, construct splitting, field validation, buffer normalization, and surplus-fact retention.
- Use fixture JATS XML and supplement files to verify source precedence, stable evidence locators, missing-field handling, and citation/reference flags.
- Test multi-construct/complex papers, every expression-system template, malformed model JSON, unavailable Ollama server, resumable runs, and Parquet output schemas.


