"""Static Expert field definitions used by the protocol extractor.

The definitions below were transcribed from Supplementary Sheet S2 (version
2026-05-26).  They intentionally do not read the workbook at runtime: the
prompt and the persisted column contract must remain reproducible.
"""

from dataclasses import dataclass

SCHEMA_VERSION = "expert-2026-05-26"


@dataclass(frozen=True)
class ExpertField:
    identifier: str
    alias: str
    value_type: str


TARGET_FIELDS = (
    ExpertField("T1", "protein_name", "text"),
    ExpertField("T2", "gene_name", "text"),
    ExpertField("T3", "gene_species", "text"),
    ExpertField("T4", "uniprot_id", "uniprot"),
    ExpertField("T5", "predicted_protein_localisation", "text"),
    ExpertField("T6", "pdb_id", "text"),
    ExpertField("T7", "post_translational_modifications", "text"),
    ExpertField("CX1", "complex_id", "id"),
    ExpertField("CX2", "complex_name", "text"),
    ExpertField("CX3", "complex_formation_method", "text"),
)

CONSTRUCT_FIELDS = (
    ExpertField("C1", "coding_dna_sequence", "sequence"),
    ExpertField("C2", "amino_acid_sequence", "sequence"),
    ExpertField("C3", "transcript_sequence", "sequence"),
    ExpertField("C4", "vector_name", "text"),
    ExpertField("C5", "vector_sequence", "sequence"),
    ExpertField("C6", "annotated_sequence", "text"),
)

GENERAL_EXPRESSION_FIELDS = (
    ExpertField("E1", "host_strain_or_cell_line", "text"),
    ExpertField("E2", "culture_medium", "text"),
    ExpertField("E3", "culture_volume", "amount"),
    ExpertField("E4", "post_induction_temperature", "number"),
    ExpertField("E5", "culture_additives", "text"),
    ExpertField("E6", "culture_rpm", "amount"),
    ExpertField("E7", "growth_container", "text"),
    ExpertField("E8", "growth_time", "amount"),
    ExpertField("E9", "pellet_weight", "number"),
    ExpertField("E10", "lysis_method", "text"),
    ExpertField("E11", "lysis_buffer", "buffer"),
    ExpertField("E12", "expression_determination_method", "text"),
    ExpertField("E13", "expression_solubility", "text"),
)

PURIFICATION_FIELDS = (
    ExpertField("P1", "first_purification_method", "text"),
    ExpertField("P2", "first_purification_buffer", "buffer"),
    ExpertField("P3", "first_purification_outcome_method", "text"),
    ExpertField("P4", "first_purification_succeeded", "boolean"),
    ExpertField("P5", "first_purification_right_size", "boolean"),
    ExpertField("P6", "first_purification_yield_method", "text"),
    ExpertField("P7", "first_purification_yield", "amount"),
    ExpertField("P8", "second_purification_method", "text"),
    ExpertField("P9", "second_purification_yield_method", "text"),
    ExpertField("P10", "second_purification_yield", "amount"),
    ExpertField("P11", "third_purification_method", "text"),
    ExpertField("P12", "third_purification_yield_method", "text"),
    ExpertField("P13", "third_purification_yield", "amount"),
    ExpertField("P14", "tag_removal_step", "text"),
    ExpertField("P15", "final_protein_buffer", "buffer"),
    ExpertField("Q1", "final_batch_purity", "percentage"),
    ExpertField("Q2", "final_batch_aggregation_status", "text"),
    ExpertField("Q3", "final_batch_stability", "text"),
    ExpertField("Q4", "identity_confirmed_by_mass_spec", "boolean"),
    ExpertField("O1", "other_comments", "text"),
    ExpertField("O2", "data_record_completeness_score", "score"),
)

HOST_FIELDS: dict[str, tuple[ExpertField, ...]] = {
    "e-coli": (
        *TARGET_FIELDS,
        *CONSTRUCT_FIELDS,
        *GENERAL_EXPRESSION_FIELDS,
        ExpertField("EB1", "pre_induction_temperature", "number"),
        ExpertField("EB2", "od600_at_induction", "number"),
        ExpertField("EB3", "induction_method", "text"),
        *PURIFICATION_FIELDS,
    ),
    "insect": (
        *TARGET_FIELDS,
        *CONSTRUCT_FIELDS,
        *GENERAL_EXPRESSION_FIELDS,
        ExpertField("EI1", "transfection_method", "text"),
        ExpertField("EI2", "virus_generation", "text"),
        ExpertField("EI3", "infection_method", "text"),
        ExpertField("EI4", "cell_density_at_infection", "number"),
        *PURIFICATION_FIELDS,
    ),
    "mammalian": (
        *TARGET_FIELDS,
        *CONSTRUCT_FIELDS,
        *GENERAL_EXPRESSION_FIELDS,
        ExpertField("EM1", "transfection_method", "text"),
        ExpertField("EM2", "virus_generation", "text"),
        ExpertField("EM3", "bacmam_transduction_method", "text"),
        ExpertField("EM4", "stable_cell_line_generation", "text"),
        ExpertField("EM5", "cell_density_at_transfection", "number"),
        *PURIFICATION_FIELDS,
    ),
    "cell-free": (
        *TARGET_FIELDS,
        ExpertField("C1", "coding_dna_sequence", "sequence"),
        ExpertField("C2", "amino_acid_sequence", "sequence"),
        ExpertField("C3", "transcript_sequence", "sequence"),
        ExpertField("C4", "vector_name", "text"),
        ExpertField("CFC1", "construct_template_type", "text"),
        ExpertField("CFL1", "lysate_host_strain_or_cell_line", "text"),
        ExpertField("CFL2", "lysate_manufacturer", "text"),
        ExpertField("CFL3", "lysate_preparation_method", "text"),
        ExpertField("CFL4", "lysate_buffer", "buffer"),
        ExpertField("CFE1", "reaction_type", "text"),
        ExpertField("CFE2", "energy_substrates", "text"),
        ExpertField("CFE3", "nucleotides", "text"),
        ExpertField("CFE4", "magnesium", "text"),
        ExpertField("CFE5", "potassium", "text"),
        ExpertField("CFE6", "amino_acids", "text"),
        ExpertField("CFE7", "isotope_labeling", "text"),
        ExpertField("CFE8", "chaperones", "text"),
        ExpertField("CFE9", "disulfide_isomerases", "text"),
        ExpertField("CFE10", "additional_supplements", "text"),
        ExpertField("CFE11", "reaction_volume", "amount"),
        ExpertField("CFE12", "reaction_temperature", "number"),
        ExpertField("CFE13", "reaction_time", "amount"),
        ExpertField("CFE14", "redox_system", "text"),
        ExpertField("CFE15", "stabilizer", "text"),
        *PURIFICATION_FIELDS,
    ),
}

BUFFER_ROLES = ("pH", "BUFF", "SALT", "DET", "RED", "OTHER")


def prompt_schema() -> str:
    """Return a stable prompt fragment; it is independent of external files."""
    host_lines = []
    for host, fields in HOST_FIELDS.items():
        rendered = ", ".join(
            f"{field.identifier} ({field.alias}: {field.value_type})" for field in fields
        )
        host_lines.append(f"- {host}: {rendered}")
    return "\n".join(host_lines)
