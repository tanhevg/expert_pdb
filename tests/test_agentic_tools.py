import pytest

from expert_pdb.util import agentic_tools


class FakeResponse:
    def __init__(self, text: str):
        self.text = text
        self.raise_for_status_called = False

    def raise_for_status(self) -> None:
        self.raise_for_status_called = True


def test_get_cds_for_protein_accession_fetches_and_parses_entrez_record(monkeypatch):
    response = FakeResponse(
        ">lcl|NM_000546.6_cds_NP_000537.3_1 [protein_id=NP_000537.3]\n"
        "ATGGAG\n"
        "GAGTAA\n"
    )

    def fake_get(url: str, *, params: dict[str, str], timeout: float) -> FakeResponse:
        assert url == agentic_tools.NCBI_EFETCH_URL
        assert params == {
            "db": "protein",
            "id": "NP_000537.3",
            "rettype": "fasta_cds_na",
            "retmode": "text",
            "tool": "expert_pdb",
        }
        assert timeout == 30
        return response

    monkeypatch.setattr(agentic_tools.requests, "get", fake_get)

    assert agentic_tools.get_cds_for_protein_accession(" NP_000537.3 ") == "ATGGAGGAGTAA"
    assert response.raise_for_status_called


@pytest.mark.parametrize("accession", ["", "NP 000537.3", "NP_000537.3&db=nuccore"])
def test_get_cds_for_protein_accession_rejects_invalid_accession(accession):
    with pytest.raises(ValueError, match="Invalid protein accession"):
        agentic_tools.get_cds_for_protein_accession(accession)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("", "returned 0 CDS records"),
        (">first\nATG\n>second\nATG\n", "returned 2 CDS records"),
        (">record\nNOT-A-SEQUENCE\n", "returned an invalid CDS"),
    ],
)
def test_get_cds_for_protein_accession_rejects_invalid_entrez_response(
    monkeypatch, payload, message
):
    monkeypatch.setattr(
        agentic_tools.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    with pytest.raises(ValueError, match=message):
        agentic_tools.get_cds_for_protein_accession("NP_000537.3")


def test_get_cds_for_protein_accession_is_registered_as_agentic_tool():
    assert (
        agentic_tools.OLLAMA_AGENTIC_TOOLS["get_cds_for_protein_accession"]
        is agentic_tools.get_cds_for_protein_accession
    )
