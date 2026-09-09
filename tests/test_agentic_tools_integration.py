import hashlib

import pytest

from expert_pdb.util.agentic_tools import get_cds_for_protein_accession


@pytest.mark.integration
def test_get_cds_for_protein_accession_agg09411_1():
    sequence = get_cds_for_protein_accession("AGG09411.1")

    assert len(sequence) == 897
    assert sequence.startswith("ATG")
    assert sequence.endswith("TAA")
    assert hashlib.sha256(sequence.encode()).hexdigest() == (
        "a2029e97940d8a044dd269f96ea66be3e875ef6e0d088578f19405e55ec869b9"
    )
