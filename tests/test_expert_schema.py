import json

import pytest

from expert_pdb.expert_schema import HOST_FIELDS, expert_json_schema


@pytest.mark.skip
def test_prompt_schema_describes_host_specific_protein_records():
    schema = expert_json_schema()

    assert json.loads(json.dumps(schema)) == schema
    protein_schemas = schema["properties"]["proteins"]["items"]["oneOf"]
    assert {item["properties"]["expression_host"]["const"] for item in protein_schemas} == set(
        HOST_FIELDS
    )
    for protein_schema in protein_schemas:
        host = protein_schema["properties"]["expression_host"]["const"]
        for field in HOST_FIELDS[host]:
            property_schema = protein_schema["properties"][field.identifier]
            assert property_schema["description"] == (
                f"{field.description} {field.what_to_capture}"
            )
