import logging
import re
import subprocess
import tempfile

import requests

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
DEFAULT_TIMEOUT_SECONDS = 30

_PROTEIN_ACCESSION_PATTERN = re.compile(r"^[A-Za-z0-9_]+(?:\.\d+)?$")
_NUCLEOTIDE_PATTERN = re.compile(r"^[ACGTRYSWKMBDHVN]+$")


def get_cds_for_protein_accession(accession: str) -> str:
    """Return the nucleotide coding sequence for an NCBI protein accession.

    Entrez resolves the protein record and follows its ``coded_by`` annotation
    when ``fasta_cds_na`` is requested. The returned sequence includes the stop
    codon when it is present in the referenced CDS.

    Args:
        accession: An NCBI protein accession, optionally including its version.

    Raises:
        ValueError: If the accession is invalid or Entrez does not return exactly
            one valid nucleotide sequence.
        requests.HTTPError: If the Entrez request fails.
    """
    normalized_accession = accession.strip()
    if not normalized_accession or not _PROTEIN_ACCESSION_PATTERN.fullmatch(
        normalized_accession
    ):
        raise ValueError(f"Invalid protein accession: {accession!r}")

    response = requests.get(
        NCBI_EFETCH_URL,
        params={
            "db": "protein",
            "id": normalized_accession,
            "rettype": "fasta_cds_na",
            "retmode": "text",
            "tool": "expert_pdb",
        },
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _parse_single_fasta_sequence(response.text, normalized_accession)


def _parse_single_fasta_sequence(payload: str, accession: str) -> str:
    records = [record for record in payload.strip().split(">") if record.strip()]
    if len(records) != 1:
        raise ValueError(
            f"Entrez returned {len(records)} CDS records for protein accession {accession!r}"
        )

    lines = records[0].splitlines()
    if not lines:
        raise ValueError(f"Entrez returned no CDS for protein accession {accession!r}")
    sequence = "".join(line.strip() for line in lines[1:]).upper()
    if not sequence or not _NUCLEOTIDE_PATTERN.fullmatch(sequence):
        raise ValueError(
            f"Entrez returned an invalid CDS for protein accession {accession!r}"
        )
    return sequence


def python(code: str):
    """Execute Python code.

    Args:
        code: Python source code to execute.

    Returns:
        A dict containing the process return code (int), standard output (str), and
        standard error (str).
    """

    with tempfile.NamedTemporaryFile('w', delete_on_close=False) as f:
        f.write(code)
        f.close()
        if log.isEnabledFor(logging.DEBUG):
            log.debug(f"Written code\n{code}\nto file {f.name}")
        python_command = ['python3', f.name]
        python_err = python_out = ''
        python_ret = -1
        proc = subprocess.Popen(
            python_command,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8'
        )
        try:
            python_ret = proc.wait()        
        finally:
            python_err = ''.join(proc.stderr)
            python_out = ''.join(proc.stdout)
        ret = {
            'return_code': str(python_ret), 
            'stdout': python_out, 
            'stderr': python_err
        }
        log.debug(f"Returning\n{ret}")
        if python_ret != 0:
            return f"Python subprocess returned code {python_ret}.\n{python_err}"
        return python_out + python_err


OLLAMA_AGENTIC_TOOLS = {
    "python": python,
    "get_cds_for_protein_accession": get_cds_for_protein_accession,
}
