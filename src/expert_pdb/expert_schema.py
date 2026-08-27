"""Static Expert field definitions used by the protocol extractor.

The definitions below were transcribed from Supplementary Sheet S2 (version
2026-05-26).  They intentionally do not read the workbook at runtime: the
prompt and the persisted column contract must remain reproducible.
"""

from dataclasses import dataclass
from typing import Any
import json

SCHEMA_VERSION = "expert-2026-05-26"


@dataclass(frozen=True)
class ExpertField:
    """
    One column of Expert Supplementary Sheet S2.
    ~/Documents/nicola_paper_2026/Supplementary Sheet S2_26052026.xlsx.
    """

    identifier: str
    description: str = ""
    importance: str = ""
    what_to_capture: str = ""
    format: str = ""


# Static transcription of the Description, Importance, What to capture, and
# Format rows in Supplementary Sheet S2. Shared identifiers retain the
# first worksheet's wording; host-specific aliases and validation types remain
# defined below.
FIELD_METADATA: dict[str, tuple[str, str, str, str]] = {
    'T1': ('Protein name (designed construct)',
           'Critical',
           'Protein name according to UniProt naming convention, along with construct boundaries and tags. '
           'Exapmle: His-CA2(S2-K260)',
           'text'),
    'T2': ('Gene name (HGNC)', 'Highly Enabling', 'Gene name according to HGNC naming convention e.g. CA2', 'text'),
    'T3': ('Gene species (NCBI)',
           'Optional',
           'Taxonomy according to NCBI (e.g. Homo sapiens for human and Rattus norvegicus for rat)',
           'text'),
    'T4': ('UniProt ID', 'Optional/ highly enabling', 'UniProt identifier e.g. P00918', 'uniprot id'),
    'T5': ('Predicted protein localisation',
           'Highly Enabling',
           'Intracellular, membrane-bound, secreted, periplasmic',
           'text'),
    'T6': ('PDB id', 'Highly Enabling', 'PDB identifier', 'text'),
    'T7': ('PTMs', 'Highly Enabling', 'Mapped post-translational modifications', 'text'),
    'CX1': ('Complex ID',
            'Mandatory for complexes',
            'An id to link different records that belong to the same complex',
            'id'),
    'CX2': ('Complex name',
            'Mandatory for complexes',
            'Descriptive name of the complex (e.g. “RNA polymerase II”). All parts of the complex with the same ID must '
            'have the same complex name. There can be multiple complexes with different IDs with the same name.',
            'text'),
    'CX3': ('Complex formation method',
            'Highly Enabling for Complexes',
            'Polycistronic construct, or multiple vectors co-expressed together, or components purified separately, etc.',
            'text'),
    'C1': ('DNA sequence of coding region including Tag sequences and stop codon',
           'Critical',
           'Nucleotide sequence from start ATG to last coding amino acid and stop codon. Should be the sequence that is '
           'used for expression including any DNA codon optimisation.',
           'sequence'),
    'C2': ('Amino acid sequence including Tag sequences',
           'Critical',
           'Amino acid sequence from start methionine to last amino acid',
           'sequence'),
    'C3': ('Nucleotide sequence transcript',
           'Highly Enabling',
           'Nucleotide sequence from transcription start nucleotide to last nucleotide transcribed',
           'sequence'),
    'C4': ('Vector name', 'Highly Enabling', 'Vector name excluding insert (e.g. pET28)', 'text'),
    'C5': ('Vector sequence', 'Critical', 'Nucleotide sequence of entire expression vector', 'sequence'),
    'C6': ('Annotated sequence',
           'Optional',
           'Vector or insert sequence with annotated features like TSR, UTR, coding region, signal peptides, linkers, '
           'tags, etc.',
           'genebank or equivalient'),
    'E1': ('Host strain or cell line', 'Critical', 'Name of E. coli strain used (e.g. BL21(DE3))', 'text'),
    'E2': ('Culture medium name or source', 'Critical', 'Name and composition of medium used (e.g. TB)', 'buffer'),
    'E3': ('Culture volume', 'Critical', 'ml to L', 'numeric value and units'),
    'E4': ('Culture conditions - temperature post-induction',
           'Critical',
           'Temperature used post-induction (e.g. 18°C)',
           'numeric value'),
    'E5': ('Culture conditions-additives',
           'Optional',
           'Any additional co-factors or chaperones required for expressing and purifying the protein',
           'text'),
    'E6': ('Culture conditions - rpm',
           'Critical',
           'Shaker frequency used during growth, rounds per minute',
           'numeric value and units'),
    'E7': ('Culture conditions - type of growth container',
           'Highly Enabling',
           'Type and volume of growth container, (e.g. 5 ml 96-well block)',
           'text'),
    'E8': ('Growth time', 'Highly Enabling', 'Hours to days', 'numeric value and units'),
    'E9': ('Pellet weight', 'Highly Enabling', 'Wet weight of pellet in g', 'numeric value'),
    'E10': ('Lysis method',
            'Highly Enabling',
            'How cells were lysed for example detergents and freeze-thaw, sonication, high-pressure lysis and volume in '
            'ml',
            'text'),
    'E11': ('Lysis buffer',
            'Highly Enabling',
            'Basic components in buffer system - outlined for standardised format in separate tab',
            'buffer'),
    'E12': ('Total expression determination method',
            'Highly Enabling',
            'Experimental procedure used to obtain the value in field E13 (e.g. manual categorisation based on the band '
            'thickness on the SDS-PAGE gel)',
            'text'),
    'E13': ('Total expression - is the protein expressed and soluble?',
            'Highly Enabling',
            'How much total protein was produced after clarification of a cell lysate after lysis. Estimate: high, '
            'medium, low, none',
            'text'),
    'EB1': ('Culture conditions - temperature pre-induction',
            'Critical',
            'Temperature used pre-induction (e.g. 37°C)',
            'numeric value'),
    'EB2': ('OD600 at induction', 'Highly Enabling', 'e.g. OD600 = 1.0', 'numeric value'),
    'EB3': ('Culture conditions - induction method',
            'Highly Enabling',
            'How is recombinant expression induced IPTG or autoinduction? What concentration of IPTG is used?',
            'text'),
    'P1': ('First-step purification method', 'Critical', 'Type of purification (e.g. Ni-NTA)', 'text'),
    'P2': ('First-step purification buffer',
           'Highly Enabling',
           'Basic components in buffer system - outlined in separate tab for standardised format',
           'buffer'),
    'P3': ('First-step purification binary outcome determination method',
           'Highly Enabling',
           'Experimental procedure used to obtain the value in field P4 (e.g. manual categorisation based on the band '
           'thickness on the SDS-PAGE gel.',
           'text'),
    'P4': ('First-step binary purification outcome - purified or not?',
           'Critical',
           'Has the protein been purified?',
           'yes/no'),
    'P5': ('First-step purification protein is at right size?', 'Highly Enabling', 'Yes or no', 'yes/no'),
    'P6': ('First-step purification yield determination method',
           'Highly Enabling',
           'Experimental procedure used to obtain the value in field P7 (e.g. densitometry estimate with an image '
           'analysis software, based on the band thickness on the SDS-PAGE gel, or densitometry method used, etc.',
           'text'),
    'P7': ('First-step purification yield',
           'Critical',
           'Yield translated to mg/L protein purified from litre of media during expression',
           'numeric value and units'),
    'P8': ('Second-step purification method', 'Highly Enabling', 'Type of purification (e.g. SEC)', 'text'),
    'P9': ('Second-step purification yield determination method',
           'Highly Enabling',
           'Experimental procedure used to obtain the value in field P10. E.g. densitometry estimate with an image '
           'analysis model based on the band thickness on the SDS-PAGE gel, or densitometry method used, etc.',
           'text'),
    'P10': ('Second-step purification yield',
            'Highly Enabling',
            'Yield translated to mg/L protein purified per g of cells',
            'numeric value and units'),
    'P11': ('Third-step purification method', 'Optional', 'Type of purification (e.g. IEX)', 'text'),
    'P12': ('Third-step purification yield determination method',
            'Highly Enabling',
            'Experimental procedure used to obtain the value in field P13 (e.g. densitometry estimate with an image '
            'analysis model based on the band thickness on the SDS-PAGE gel, or densitometry method used, etc.',
            'text'),
    'P13': ('Third-step purification yield',
            'Optional',
            'Yield translated to mg/L protein purified per g of cells',
            'numeric value and units'),
    'P14': ('Tag removal step', 'Optional', 'e.g. treatment with TEV protease', 'text'),
    'P15': ('Final protein buffer',
            'Highly Enabling',
            'Basic components in buffer system - outlined below for standardised format',
            'buffer'),
    'Q1': ('Final batch - purity',
           'Highly Enabling',
           'How pure is the protein as determined by SDS-PAGE - need to comment which purification step purity has been '
           'assessed after',
           'percentage'),
    'Q2': ('Final batch - aggregation status', 'Highly Enabling', 'Monodisperse, broad, multimeric or aggregated', 'text'),
    'Q3': ('Final batch - stability / thermal unfolding',
           'Optional',
           'Thermal unfolding as assessed by DSF or TSA (°C)',
           'text'),
    'Q4': ('Final batch - identity and-or size verified by mass-spec',
           'Highly Enabling',
           'Has size of protein been confirmed by mass spec?',
           'yes/no'),
    'O1': ('Other comments',
           'Optional',
           'Any other information deemed useful by the author to supplement the deposition. Could contain links to FAIR '
           'publications, datasets and protocols. Could be JSON-formatted for ease of machine ingestion.',
           'text'),
    'O2': ('Data record completeness score',
           'Highly Enabling',
           'Score between 1 and 10, 1 being the least complete and 10 being the most complete score. Assigned '
           'collaboratively by the deposition author and the data curator.',
           '1 to 10'),
    'EI1': ('Culture conditions transfection method',
            'Highly Enabling',
            'DNA:transfection reagent ratio and the reagent used. (e.g. 1 part DNA:3 parts transfection reagent)',
            'text'),
    'EI2': ('Virus generation',
            'Optional',
            'Similar to transfection and specify which passage is used (P0, P1, P2 etc.) and volume (ml to L)',
            'text'),
    'EI3': ('Culture conditions - infection method',
            'Optional',
            'What is the multiplicity of infection (MOI)?',
            'numeric value'),
    'EI4': ('Cell density at infection or transfection',
            'Optional',
            'Density of cells when protein production is induced. Number of cells per ml culture volume.',
            'numeric value and units'),
    'EM1': ('Culture conditions - transfection method',
            'Highly Enabling',
            'DNA:transfection reagent ratio and the reagent used (e.g. 1 part DNA:3 parts transfection reagent)',
            'text'),
    'EM2': ('Virus generation (if BacMam)',
            'Optional',
            'Similar to transfection and specifiy which passage is used (P0, P1, P2 etc.) and volume (ml to L)',
            'text'),
    'EM3': ('Culture conditions - BacMam transduction method',
            'Optional',
            'What is the multiplicity of infection (MOI)?',
            'numeric value'),
    'EM4': ('Stable cell line generation', 'Highly Enabling', 'Method of generation of stable cell line', 'text'),
    'EM5': ('Cell density at transfection or infection',
            'Optional',
            'Density of cells when protein production is induced. Number of cells per ml culture volume.',
            'numeric value and units'),
    'CFC1': ('Construct template type',
             'Highly enabling',
             'Linearised plasmid or PCR-fragment, amounts added',
             'text, numeric value and units'),
    'CFL1': ('Host strain/Cell line used for preparation of the cell-free lysate',
             'Critical',
             'Name of E. coli strain or cell line used (e.g. BL21(DE3), RRL, Sf9, Sf21, CHO, HEK293, tobacco)',
             'text'),
    'CFL2': ('Manufacturer of the cell-free lysate',
             'Highly enabling',
             'In-house produced lysate or commercially available',
             'text'),
    'CFL3': ('Lysis method used in the preparation of the cell-free lysate',
             'Highly enabling',
             'e.g. French press, sonication, homogenization, reconstitution of purified components',
             'text'),
    'CFL4': ('Buffer composition',
             'Critical',
             'Buffer used to prepare the cell-free lysate (e.g. glutamate or acetate-based)',
             'buffer'),
    'CFE1': ('Type of reaction used', 'Critical', 'Batch reaction or continuous-exchange reaction', 'text'),
    'CFE2': ('Energy substrates',
             'Highly enabling',
             'e.g. PEP, creatine phosphate, mitochondrial based energy regeneration…',
             'text'),
    'CFE3': ('Nucleotides', 'Highly enabling', 'mM ATP, GTP, CTP, UTP', 'text'),
    'CFE4': ('Magnesium', 'Highly enabling', 'Concentration and type of Mg ion', 'text'),
    'CFE5': ('Potassium', 'Highly enabling', 'Concentration and type of K ion', 'text'),
    'CFE6': ('Amino acids', 'Highly enabling', 'e.g. concentration, canonical, unnatural amino acids', 'text'),
    'CFE7': ('Isotope labeling', 'Highly enabling', 'e.g. 13C, 15N', 'text'),
    'CFE8': ('Chaperones', 'Highly enabling', 'e.g. GroEL/ES', 'text'),
    'CFE9': ('Disulfide isomerases', 'Highly enabling', 'e.g. DsbC, PDI', 'text'),
    'CFE10': ('Additional supplements', 'Highly enabling', 'e.g. MSPs for membrane proteins', 'text'),
    'CFE11': ('Reaction volume', 'Critical', 'µl to ml', 'numeric value and units'),
    'CFE12': ('Reaction temperature', 'Critical', '°C', 'numeric value and units'),
    'CFE13': ('Reaction time', 'Critical', 'hours', 'numeric value and units'),
    'CFE14': ('Redox system', 'Critical', 'e.g. DTT GSSG/GSH', 'text'),
    'CFE15': ('Stabilizer', 'Critical', 'e.g. PEG, protease/RNase inhibitors', 'text')
}


def expert_field(identifier: str) -> ExpertField:
    """Build an Expert field with its complete Supplementary Sheet S2 metadata."""
    description, importance, what_to_capture, format = FIELD_METADATA[identifier]
    return ExpertField(identifier, description, importance, what_to_capture, format)


TARGET_FIELDS = (
    expert_field("T1"),
    expert_field("T2"),
    expert_field("T3"),
    expert_field("T4"),
    expert_field("T5"),
    expert_field("T6"),
    expert_field("T7"),
    expert_field("CX1"),
    expert_field("CX2"),
    expert_field("CX3"),
)

CONSTRUCT_FIELDS = (
    expert_field("C1"),
    expert_field("C2"),
    expert_field("C3"),
    expert_field("C4"),
    expert_field("C5"),
    expert_field("C6"),
)

GENERAL_EXPRESSION_FIELDS = (
    expert_field("E1"),
    expert_field("E2"),
    expert_field("E3"),
    expert_field("E4"),
    expert_field("E5"),
    expert_field("E6"),
    expert_field("E7"),
    expert_field("E8"),
    expert_field("E9"),
    expert_field("E10"),
    expert_field("E11"),
    expert_field("E12"),
    expert_field("E13"),
)

PURIFICATION_FIELDS = (
    expert_field("P1"),
    expert_field("P2"),
    expert_field("P3"),
    expert_field("P4"),
    expert_field("P5"),
    expert_field("P6"),
    expert_field("P7"),
    expert_field("P8"),
    expert_field("P9"),
    expert_field("P10"),
    expert_field("P11"),
    expert_field("P12"),
    expert_field("P13"),
    expert_field("P14"),
    expert_field("P15"),
    expert_field("Q1"),
    expert_field("Q2"),
    expert_field("Q3"),
    expert_field("Q4"),
    expert_field("O1"),
    expert_field("O2"),
)

HOST_FIELDS: dict[str, tuple[ExpertField, ...]] = {
    "bacterial": (
        *TARGET_FIELDS,
        *CONSTRUCT_FIELDS,
        *GENERAL_EXPRESSION_FIELDS,
        expert_field("EB1"),
        expert_field("EB2"),
        expert_field("EB3"),
        *PURIFICATION_FIELDS,
    ),
    "insect": (
        *TARGET_FIELDS,
        *CONSTRUCT_FIELDS,
        *GENERAL_EXPRESSION_FIELDS,
        expert_field("EI1"),
        expert_field("EI2"),
        expert_field("EI3"),
        expert_field("EI4"),
        *PURIFICATION_FIELDS,
    ),
    "mammalian": (
        *TARGET_FIELDS,
        *CONSTRUCT_FIELDS,
        *GENERAL_EXPRESSION_FIELDS,
        expert_field("EM1"),
        expert_field("EM2"),
        expert_field("EM3"),
        expert_field("EM4"),
        expert_field("EM5"),
        *PURIFICATION_FIELDS,
    ),
    "cell-free": (
        *TARGET_FIELDS,
        expert_field("C1"),
        expert_field("C2"),
        expert_field("C3"),
        expert_field("C4"),
        expert_field("CFC1"),
        expert_field("CFL1"),
        expert_field("CFL2"),
        expert_field("CFL3"),
        expert_field("CFL4"),
        expert_field("CFE1"),
        expert_field("CFE2"),
        expert_field("CFE3"),
        expert_field("CFE4"),
        expert_field("CFE5"),
        expert_field("CFE6"),
        expert_field("CFE7"),
        expert_field("CFE8"),
        expert_field("CFE9"),
        expert_field("CFE10"),
        expert_field("CFE11"),
        expert_field("CFE12"),
        expert_field("CFE13"),
        expert_field("CFE14"),
        expert_field("CFE15"),
        *PURIFICATION_FIELDS,
    ),
}

BUFFER_ROLES = ("pH", "BUFF", "SALT", "DET", "RED", "OTHER")


def _json_schema_type(field: ExpertField) -> dict[str, Any]:
    """Return the JSON Schema type corresponding to a Supplementary Sheet format."""
    if field.format == "yes/no":
        return {"type": "boolean"}
    if field.format in {"numeric value", "percentage", "1 to 10"}:
        return {"type": "number"}
    if field.format == "numeric value and units":
        return {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "unit": {"type": "string"},
            },
            "required": ["value", "unit"],
            "additionalProperties": False,
        }
    return {"type": "string"}

def _json_schema_descritpion(field: ExpertField) -> str:
    return f"{field.description.strip('. \t\n')}. {field.what_to_capture.strip('. \t\n')}."


def expert_json_schema(extra_fields:dict[str, Any]) -> dict[str, Any]:
    """Return the static Supplementary Sheet S2 protein-record JSON Schema."""
    host_schemas = []
    for host, fields in HOST_FIELDS.items():
        properties: dict[str, Any] = {
            "expression_host": {"const": host},
        }
        for field in fields:
            properties[field.identifier] = {
                **_json_schema_type(field),
                "description": _json_schema_descritpion(field),
            }
            if field.format == 'buffer':
                properties[field.identifier]['description'] += ' Formatted as buffer string.'
        properties |= extra_fields
        host_schemas.append(
            {
                "type": "object",
                "properties": properties,
                "required": ["expression_host"],
                "additionalProperties": True,
            }
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "proteins": {
                "type": "array",
                "items": {"oneOf": host_schemas},
            }
        },
        "required": ["proteins"],
        "additionalProperties": False,
    }


if __name__ == '__main__':
    print(json.dumps(expert_json_schema(), indent=4, ensure_ascii=False))
