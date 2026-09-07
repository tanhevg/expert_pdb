import json

import pytest

from expert_pdb.expert_schema import HOST_FIELDS, expert_json_schema


def test_prompt_schema_describes_host_specific_protein_records():
    schema = json.loads(expert_json_schema())

    assert json.loads(json.dumps(schema)) == schema
    protein_schemas = schema["properties"]["proteins"]["items"]["oneOf"]
    assert {item["properties"]["expression_host"]["const"] for item in protein_schemas} == set(
        HOST_FIELDS
    )
    hosts = [p["properties"]["expression_host"]["const"] for p in protein_schemas]
    assert set(hosts) == set(['bacterial', 'insect', 'mammalian', 'cell-free'])
    for protein_schema in protein_schemas:
        host = protein_schema["properties"]["expression_host"]["const"]
        for field in HOST_FIELDS[host]:
            assert field.identifier in protein_schema["properties"]
            
