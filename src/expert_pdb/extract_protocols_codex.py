"""Extract Expert protein-production records from downloaded PMC JATS packages."""

import argparse
import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import requests

from expert_pdb.download_publications import STATE_FILENAME, configure_logging, read_mapping
from expert_pdb.expert_schema import (
    BUFFER_ROLES,
    HOST_FIELDS,
    SCHEMA_VERSION,
    ExpertField,
    expert_json_schema,
)

log = logging.getLogger(__name__)

EXTRACTION_STATE_FILENAME = "extraction_state.parquet"
PROTOCOLS_FILENAME = "protein_production_protocols.parquet"
CONSTRUCTS_FILENAME = "construct_data.parquet"
HOST_FILENAMES = {host: f"expert_records_{host}.parquet" for host in HOST_FIELDS}
OLLAMA_DEFAULT_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen3:14b"
STATUS_VALUES = {"retrieved", "missing", "supplement", "citation"}
HOST_ALIASES = {
    "e-coli": "e-coli",
    "e coli": "e-coli",
    "ecoli": "e-coli",
    "bacterial": "e-coli",
    "insect": "insect",
    "insect cells": "insect",
    "mammalian": "mammalian",
    "mammalian cells": "mammalian",
    "cell-free": "cell-free",
    "cell free": "cell-free",
    "cellfree": "cell-free",
}

NS_XLINK = "{http://www.w3.org/1999/xlink}href"
IDENTIFIER_PATTERNS = {
    "doi": re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE),
    "pmid": re.compile(r"\bPMID\s*[:=]?\s*(\d+)\b", re.IGNORECASE),
    "pmcid": re.compile(r"\bPMC\d+\b", re.IGNORECASE),
}


class ExtractionError(ValueError):
    """A model response cannot safely be persisted."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_dir", type=Path, help="Downloader output directory.")
    selected = parser.add_mutually_exclusive_group()
    selected.add_argument("--pdb-ids", nargs="+", metavar="PDB_ID")
    selected.add_argument("--pmc-ids", nargs="+", metavar="PMCID")
    parser.add_argument("--ollama-url", default=OLLAMA_DEFAULT_URL)
    parser.add_argument("--ollama-model", default=OLLAMA_DEFAULT_MODEL)
    parser.add_argument("--force", action="store_true", help="Re-extract successful publications.")
    return parser.parse_args(argv)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _split_ids(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    return {item.strip().lower() for value in values for item in value.split(",") if item.strip()}


def select_publications(target_dir: Path, args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    mapping_path = target_dir / "pdb_pubmed.csv.gz"
    state_path = target_dir / STATE_FILENAME
    if not mapping_path.exists() or not state_path.exists():
        raise ValueError("target_dir must contain pdb_pubmed.csv.gz and download_state.parquet")
    mapping = read_mapping(mapping_path)
    state = pl.read_parquet(state_path)
    required = {"pmid", "pmcid", "download_version", "downloaded"}
    if not required.issubset(state.columns):
        raise ValueError(f"Download state has incompatible columns: {state.columns}")
    linked = mapping.join(
        state.select("pmid", "pmcid", "download_version", "downloaded"), on="pmid", how="inner"
    ).filter(pl.col("downloaded") & pl.col("pmcid").is_not_null())
    requested_pdb_ids = _split_ids(args.pdb_ids)
    requested_pmc_ids = {value.upper() for value in _split_ids(args.pmc_ids)}
    if requested_pdb_ids:
        linked = linked.filter(pl.col("pdb_id").is_in(sorted(requested_pdb_ids)))
    if requested_pmc_ids:
        linked = linked.filter(pl.col("pmcid").str.to_uppercase().is_in(sorted(requested_pmc_ids)))

    selected: dict[str, dict[str, Any]] = {}
    selected_rows = linked.select("pdb_id", "pmcid", "download_version").unique()
    for row in selected_rows.iter_rows(named=True):
        pmcid = str(row["pmcid"]).upper()
        entry = selected.setdefault(
            pmcid,
            {"pmcid": pmcid, "download_version": row["download_version"], "pdb_ids": []},
        )
        pdb_id = str(row["pdb_id"]).lower()
        if pdb_id not in entry["pdb_ids"]:
            entry["pdb_ids"].append(pdb_id)
    for entry in selected.values():
        entry["pdb_ids"].sort()
    return selected


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _element_text(element: ET.Element) -> str:
    return " ".join(" ".join(element.itertext()).split())


def _find_jats_files(package_dir: Path) -> list[Path]:
    found: list[Path] = []
    for path in sorted(package_dir.rglob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        if _local_name(root) == "article":
            found.append(path)
    return found


def _locator(relative_path: Path, section: str, index: int, element: ET.Element) -> str:
    element_id = element.attrib.get("id")
    suffix = f"#{element_id}" if element_id else f"#{section}[{index}]"
    return f"{relative_path.as_posix()}{suffix}"


def _reference_lead(element: ET.Element, label: str) -> dict[str, Any]:
    text = _element_text(element)
    identifiers: dict[str, list[str]] = {}
    for name, pattern in IDENTIFIER_PATTERNS.items():
        matches = pattern.findall(text)
        identifiers[name] = sorted(
            {match if isinstance(match, str) else match[0] for match in matches}
        )
    for pub_id in element.iter():
        if _local_name(pub_id) != "pub-id" or not pub_id.text:
            continue
        kind = pub_id.attrib.get("pub-id-type", "identifier").lower()
        identifiers.setdefault(kind, []).append(pub_id.text.strip())
    return {"label": label, "text": text, "identifiers": identifiers}


def _guess_supplement_file(href: str, label: str, files: list[Path]) -> Path | None:
    exact_name = Path(href).name.lower()
    exact = next((path for path in files if path.name.lower() == exact_name), None)
    if exact is not None:
        return exact
    query = set(re.findall(r"[a-z0-9]+", f"{Path(href).stem} {label}".lower()))
    candidates = [
        path for path in files if path.suffix.lower() in {".pdf", ".zip", ".docx", ".xls", ".xlsx"}
    ]
    scored = [
        (len(query & set(re.findall(r"[a-z0-9]+", path.stem.lower()))), path) for path in candidates
    ]
    best_score, best_path = max(scored, default=(0, None), key=lambda item: item[0])
    return best_path if best_score else None


def parse_jats(package_dir: Path) -> dict[str, Any]:
    """Return textual JATS input and unresolved local leads without parsing them."""
    chunks: list[dict[str, str]] = []
    supplements: list[dict[str, str]] = []
    references: list[dict[str, Any]] = []
    package_files = [path for path in package_dir.rglob("*") if path.is_file()]
    jats_files = _find_jats_files(package_dir)
    for path in jats_files:
        relative_path = path.relative_to(package_dir)
        root = ET.parse(path).getroot()
        section_counts: dict[str, int] = {}
        for element in root.iter():
            name = _local_name(element)
            if name not in {"sec", "p"}:
                continue
            text = _element_text(element)
            if not text:
                continue
            section = element.attrib.get("sec-type", name)
            section_counts[section] = section_counts.get(section, 0) + 1
            chunks.append(
                {
                    "locator": _locator(relative_path, section, section_counts[section], element),
                    "text": text,
                }
            )
        for element in root.iter():
            if _local_name(element) != "supplementary-material":
                continue
            href = element.attrib.get(NS_XLINK, "") or element.attrib.get("href", "")
            guessed = _guess_supplement_file(href, _element_text(element), package_files)
            supplements.append(
                {
                    "label": _element_text(element) or "supplementary material",
                    "href": href,
                    "guessed_file": str(guessed.relative_to(package_dir)) if guessed else href,
                }
            )
        references_in_file = (item for item in root.iter() if _local_name(item) == "ref")
        for index, element in enumerate(references_in_file, 1):
            label_element = next((item for item in element if _local_name(item) == "label"), None)
            label = _element_text(label_element) if label_element is not None else str(index)
            references.append(_reference_lead(element, label))
    return {
        "jats_files": [path.relative_to(package_dir).as_posix() for path in jats_files],
        "chunks": chunks,
        "supplements": supplements,
        "references": references,
    }


def build_prompt(source: dict[str, Any], pmcid: str, pdb_ids: list[str]) -> str:
    contract = {
        "protocol_status": "retrieved|missing|supplement|citation",
        "protocol_chunks": [{"locator": "input locator", "text": "verbatim relevant text"}],
        "constructs": [
            {
                "construct_id": "stable name within this paper",
                "host": "e-coli|insect|mammalian|cell-free|unknown",
                "pdb_ids": ["optional PDB IDs explicitly linked in the article"],
                "fields": {
                    "T1": {
                        "value": "typed value matching the selected host schema",
                        "confidence": 0.0,
                        "evidence_locators": ["input locator"],
                    }
                },
                "surplus_facts": [
                    {
                        "name": "fact name",
                        "value": "fact value",
                        "confidence": 0.0,
                        "evidence_locators": ["input locator"],
                    }
                ],
                "protein_identifiers": {
                    "uniprot_ids": [],
                    "genbank_ids": [],
                    "gene_names": [],
                    "organisms": [],
                    "other_identifiers": [],
                },
                "n_terminal_tags": [],
                "c_terminal_tags": [],
            }
        ],
        "supplementary_leads": [],
        "citation_leads": [],
    }
    return f"""You extract recombinant protein-production protocols from JATS XML only.
Never infer an unreported value. Emit JSON only, following this exact contract:
{json.dumps(contract, indent=2)}

Schema version: {SCHEMA_VERSION}. For the selected host, return every listed field ID.
Use `value: null`, `confidence: 0`, and an empty evidence list when a field is absent.
Each non-null known field value must use its required type. Buffers must be canonical
strings using roles {", ".join(BUFFER_ROLES)}, for example
`pH 7.5; BUFF HEPES, 50 mM; SALT NaCl, 250 mM`.  Put relevant facts not represented
by the schema in surplus_facts. Give every returned field and surplus fact confidence
from 0 to 1 plus input evidence locators. Do not claim that supplementary files or
references were parsed. A direct JATS protocol is retrieved; otherwise use supplement
or citation only when it is the stated location of protocol details, else missing.

Expert fields by expression host:
{json.dumps(expert_json_schema(), ensure_ascii=False, indent=2)}

Publication: {pmcid}; PDB IDs linked by publication metadata: {", ".join(pdb_ids)}
JATS source material (all locators below are stable source locators):
{json.dumps(source, ensure_ascii=False)}
"""


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExtractionError(f"{field} must be a list")
    return value


def _confidence(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ExtractionError(f"{field} confidence must be a number between 0 and 1")
    return float(value)


def normalize_host(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return HOST_ALIASES.get(value.strip().lower())


def normalize_buffer(value: Any) -> str:
    if isinstance(value, list):
        parts = []
        for part in value:
            if not isinstance(part, dict) or not isinstance(part.get("role"), str):
                raise ExtractionError("buffer components must contain a role")
            role = part["role"].upper()
            if role not in BUFFER_ROLES:
                role = "OTHER"
            name = str(part.get("name", "")).strip()
            amount = str(part.get("amount", "")).strip()
            parts.append(" ".join(piece for piece in (role, name, amount) if piece))
        return "; ".join(parts)
    if not isinstance(value, str):
        raise ExtractionError("buffer must be text or component objects")
    parts = []
    for part in value.split(";"):
        clean = " ".join(part.split()).strip()
        if clean:
            match = re.match(r"^(pH|BUFF|SALT|DET|RED|OTHER)\b", clean, re.IGNORECASE)
            if match:
                role = match.group(1)
                normalized_role = "pH" if role.lower() == "ph" else role.upper()
                clean = normalized_role + clean[match.end() :]
            parts.append(clean)
    if not parts:
        raise ExtractionError("buffer must not be empty")
    return "; ".join(parts)


def _normalize_value(value: Any, field: ExpertField) -> Any:
    value_type = _value_type(field)
    if value_type in {"text", "id"}:
        if not isinstance(value, str) or not value.strip():
            raise ExtractionError(f"{field.identifier} must be non-empty text")
        return value.strip()
    if value_type == "uniprot":
        accession = value.strip().upper() if isinstance(value, str) else ""
        if not re.fullmatch(r"[A-Z0-9]{6,10}(?:-\d+)?", accession):
            raise ExtractionError(f"{field.identifier} must be a UniProt accession")
        return value.strip().upper()
    if value_type == "sequence":
        if not isinstance(value, str):
            raise ExtractionError(f"{field.identifier} must be a sequence string")
        sequence = re.sub(r"\s+", "", value).upper()
        if not sequence or not re.fullmatch(r"[A-Z*.-]+", sequence):
            raise ExtractionError(f"{field.identifier} contains an invalid sequence")
        return sequence
    if value_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"yes", "no"}:
            return value.strip().lower() == "yes"
        raise ExtractionError(f"{field.identifier} must be yes/no")
    if value_type in {"number", "percentage"}:
        if isinstance(value, str):
            value = value.strip().removesuffix("%")
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ExtractionError(f"{field.identifier} must be numeric")
        try:
            number = float(value)
        except ValueError as exc:
            raise ExtractionError(f"{field.identifier} must be numeric") from exc
        if value_type == "percentage" and not 0 <= number <= 100:
            raise ExtractionError(f"{field.identifier} percentage must be between 0 and 100")
        return number
    if value_type == "score":
        valid_score = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and int(value) == value
            and 1 <= int(value) <= 10
        )
        if not valid_score:
            raise ExtractionError(f"{field.identifier} must be an integer from 1 to 10")
        return int(value)
    if value_type == "amount":
        if not isinstance(value, dict) or set(value) - {"value", "unit"}:
            raise ExtractionError(f"{field.identifier} must be an object with value and unit")
        numeric = value.get("value")
        unit = value.get("unit")
        valid_amount = (
            not isinstance(numeric, bool)
            and isinstance(numeric, (int, float))
            and isinstance(unit, str)
            and bool(unit.strip())
        )
        if not valid_amount:
            raise ExtractionError(f"{field.identifier} amount must contain a number and unit")
        return {"value": float(numeric), "unit": unit.strip()}
    if value_type == "buffer":
        return normalize_buffer(value)
    raise ExtractionError(f"Unsupported type {value_type}")


def _normalize_leads(value: Any, field: str) -> list[dict[str, Any]]:
    leads = _require_list(value, field)
    normalized: list[dict[str, Any]] = []
    for lead in leads:
        if isinstance(lead, str):
            normalized.append({"description": lead, "identifiers": {}})
        elif isinstance(lead, dict):
            description = lead.get("description") or lead.get("text") or lead.get("label")
            if not isinstance(description, str):
                raise ExtractionError(f"{field} lead has no description")
            identifiers = lead.get("identifiers", {})
            if not isinstance(identifiers, dict):
                raise ExtractionError(f"{field} identifiers must be an object")
            normalized.append({"description": description, "identifiers": identifiers})
        else:
            raise ExtractionError(f"{field} entries must be objects or strings")
    return normalized


def _validate_evidence_locators(value: Any, known_locators: set[str], field: str) -> None:
    if not isinstance(value, list) or not all(isinstance(locator, str) for locator in value):
        raise ExtractionError(f"{field} evidence_locators must be a list of strings")
    unknown = set(value) - known_locators
    if unknown:
        raise ExtractionError(f"{field} uses unknown evidence locators: {sorted(unknown)}")


def validate_model_output(payload: Any, known_locators: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExtractionError("Model JSON must be an object")
    required = {
        "protocol_status",
        "protocol_chunks",
        "constructs",
        "supplementary_leads",
        "citation_leads",
    }
    missing = required - payload.keys()
    if missing:
        raise ExtractionError(f"Model JSON is missing {sorted(missing)}")
    status = payload["protocol_status"]
    if status not in STATUS_VALUES:
        raise ExtractionError("protocol_status is invalid")
    chunks = _require_list(payload["protocol_chunks"], "protocol_chunks")
    normalized_chunks = []
    for chunk in chunks:
        valid_chunk = (
            isinstance(chunk, dict)
            and isinstance(chunk.get("locator"), str)
            and isinstance(chunk.get("text"), str)
        )
        if not valid_chunk:
            raise ExtractionError("protocol chunks require locator and text")
        if known_locators is not None and chunk["locator"] not in known_locators:
            raise ExtractionError(f"protocol chunk uses unknown locator: {chunk['locator']}")
        normalized_chunks.append({"locator": chunk["locator"], "text": chunk["text"]})
    if status == "retrieved" and not normalized_chunks:
        raise ExtractionError("retrieved status requires protocol chunks")
    constructs = _require_list(payload["constructs"], "constructs")
    normalized_constructs = []
    for index, construct in enumerate(constructs, 1):
        if not isinstance(construct, dict):
            raise ExtractionError("constructs entries must be objects")
        construct_id = construct.get("construct_id", f"construct-{index}")
        if not isinstance(construct_id, str) or not construct_id.strip():
            raise ExtractionError("construct_id must be text")
        fields = construct.get("fields", {})
        if not isinstance(fields, dict):
            raise ExtractionError("construct fields must be an object")
        if known_locators is not None:
            for field_id, field_value in fields.items():
                if not isinstance(field_value, dict):
                    raise ExtractionError(f"{field_id} must be an object")
                _validate_evidence_locators(
                    field_value.get("evidence_locators", []), known_locators, field_id
                )
            for fact in _require_list(construct.get("surplus_facts", []), "surplus_facts"):
                if not isinstance(fact, dict):
                    raise ExtractionError("surplus facts entries must be objects")
                _validate_evidence_locators(
                    fact.get("evidence_locators", []), known_locators, "surplus fact"
                )
        normalized_constructs.append(
            {
                "construct_id": construct_id.strip(),
                "host": normalize_host(construct.get("host")),
                "pdb_ids": [
                    str(item).lower()
                    for item in _require_list(construct.get("pdb_ids", []), "pdb_ids")
                ],
                "fields": fields,
                "surplus_facts": _require_list(construct.get("surplus_facts", []), "surplus_facts"),
                "protein_identifiers": construct.get("protein_identifiers", {}),
                "n_terminal_tags": _require_list(
                    construct.get("n_terminal_tags", []), "n_terminal_tags"
                ),
                "c_terminal_tags": _require_list(
                    construct.get("c_terminal_tags", []), "c_terminal_tags"
                ),
            }
        )
    return {
        "protocol_status": status,
        "protocol_chunks": normalized_chunks,
        "constructs": normalized_constructs,
        "supplementary_leads": _normalize_leads(
            payload["supplementary_leads"], "supplementary_leads"
        ),
        "citation_leads": _normalize_leads(payload["citation_leads"], "citation_leads"),
    }


def _ollama_json(base_url: str, model: str, prompt: str) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/generate"
    request_body = {
        "model": model, 
        "prompt": prompt, 
        "stream": False, 
        "format": "json",
        "options": {"num_ctx": 81920},
        "keep_alive": -1
    }
    response = requests.post(url, json=request_body, timeout=300)
    response.raise_for_status()
    body = response.json()
    generated = body.get("response")
    if not isinstance(generated, str):
        raise ExtractionError("Ollama response has no JSON response string")
    try:
        return json.loads(generated)
    except json.JSONDecodeError as exc:
        raise ExtractionError("Ollama returned malformed JSON") from exc


def preflight_ollama(base_url: str) -> None:
    response = requests.get(base_url.rstrip("/") + "/api/tags", timeout=15)
    response.raise_for_status()


def _amount_dtype() -> pl.DataType:
    return pl.Struct({"value": pl.Float64, "unit": pl.String})


def _value_type(field: ExpertField) -> str:
    """Map Supplementary Sheet S2's format labels to extractor value types."""
    return {
        "uniprot id": "uniprot",
        "sequence": "sequence",
        "buffer": "buffer",
        "yes/no": "boolean",
        "numeric value": "number",
        "numeric value and units": "amount",
        "percentage": "percentage",
        "1 to 10": "score",
    }.get(field.format, "text")


def _field_dtype(field: ExpertField) -> pl.DataType:
    return {
        "boolean": pl.Boolean,
        "number": pl.Float64,
        "percentage": pl.Float64,
        "score": pl.Int8,
        "amount": _amount_dtype(),
    }.get(_value_type(field), pl.String)


def _expert_schema(host: str) -> dict[str, pl.DataType]:
    schema: dict[str, pl.DataType] = {
        "expert_schema_version": pl.String,
        "pmcid": pl.String,
        "pdb_id": pl.String,
        "construct_id": pl.String,
        "pdb_linkage": pl.String,
        "linkage_confidence": pl.Float64,
        "field_provenance": pl.List(
            pl.Struct({"field_id": pl.String, "locators": pl.List(pl.String)})
        ),
        "surplus_facts": pl.List(
            pl.Struct(
                {
                    "name": pl.String,
                    "value": pl.String,
                    "confidence": pl.Float64,
                    "evidence_locators": pl.List(pl.String),
                }
            )
        ),
    }
    for field in HOST_FIELDS[host]:
        dtype = _field_dtype(field)
        schema[field.identifier] = dtype
        schema[f"{field.identifier}_confidence"] = pl.Float64
    return schema


PROTOCOL_SCHEMA: dict[str, pl.DataType] = {
    "pdb_id": pl.String,
    "pmcid": pl.String,
    "source_file": pl.String,
    "source_format": pl.String,
    "protocol_text": pl.String,
    "status": pl.String,
    "evidence_locators": pl.List(pl.String),
    "deferred_source_info": pl.String,
}
CONSTRUCT_SCHEMA: dict[str, pl.DataType] = {
    "pdb_id": pl.String,
    "pmcid": pl.String,
    "construct_id": pl.String,
    "pdb_linkage": pl.String,
    "protein_name": pl.String,
    "gene_names": pl.List(pl.String),
    "organisms": pl.List(pl.String),
    "uniprot_ids": pl.List(pl.String),
    "genbank_ids": pl.List(pl.String),
    "other_identifiers": pl.List(pl.String),
    "n_terminal_tags": pl.List(pl.String),
    "c_terminal_tags": pl.List(pl.String),
    "confidence": pl.Float64,
    "evidence_locators": pl.List(pl.String),
}
STATE_SCHEMA: dict[str, pl.DataType] = {
    "pmcid": pl.String,
    "download_version": pl.String,
    "status": pl.String,
    "run_id": pl.String,
    "error": pl.String,
    "updated_at": pl.String,
}


def _frame(rows: list[dict[str, Any]], schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=schema, strict=False) if rows else pl.DataFrame(schema=schema)


def _upsert(
    path: Path, pmcid: str, rows: list[dict[str, Any]], schema: dict[str, pl.DataType]
) -> None:
    new = _frame(rows, schema)
    if path.exists():
        old = pl.read_parquet(path).filter(pl.col("pmcid") != pmcid)
        new = pl.concat([old, new], how="diagonal_relaxed")
    new.write_parquet(path)


def _as_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _normalize_surplus(value: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for fact in value:
        if not isinstance(fact, dict) or not isinstance(fact.get("name"), str):
            raise ExtractionError("surplus facts require a name")
        confidence = _confidence(fact.get("confidence"), "surplus fact")
        locators = _as_strings(fact.get("evidence_locators", []))
        raw_value = fact.get("value")
        normalized.append(
            {
                "name": fact["name"].strip(),
                "value": (
                    raw_value
                    if isinstance(raw_value, str)
                    else json.dumps(raw_value, sort_keys=True)
                ),
                "confidence": confidence,
                "evidence_locators": locators,
            }
        )
    return normalized


def _expert_row(
    host: str, construct: dict[str, Any], pmcid: str, pdb_id: str, linkage: str
) -> dict[str, Any]:
    fields = {field.identifier: field for field in HOST_FIELDS[host]}
    row: dict[str, Any] = {
        "expert_schema_version": SCHEMA_VERSION,
        "pmcid": pmcid,
        "pdb_id": pdb_id,
        "construct_id": construct["construct_id"],
        "pdb_linkage": linkage,
        "linkage_confidence": 1.0 if linkage == "explicit" else 0.5,
        "field_provenance": [],
        "surplus_facts": _normalize_surplus(construct["surplus_facts"]),
    }
    for identifier, supplied in construct["fields"].items():
        if identifier not in fields:
            row["surplus_facts"].append(
                {
                    "name": identifier,
                    "value": json.dumps(supplied),
                    "confidence": 0.0,
                    "evidence_locators": [],
                }
            )
            continue
        if not isinstance(supplied, dict):
            raise ExtractionError(
                f"{identifier} must contain value, confidence, and evidence_locators"
            )
        if set(supplied) - {"value", "confidence", "evidence_locators"} or "value" not in supplied:
            raise ExtractionError(f"{identifier} has unsupported keys")
        field = fields[identifier]
        confidence = _confidence(supplied.get("confidence"), identifier)
        locators = _as_strings(supplied.get("evidence_locators", []))
        if supplied["value"] is None:
            if confidence != 0.0 or locators:
                raise ExtractionError(
                    f"{identifier} missing values require zero confidence and no evidence"
                )
            row[f"{identifier}_confidence"] = confidence
            continue
        normalized_value = _normalize_value(supplied["value"], field)
        row[identifier] = normalized_value
        row[f"{identifier}_confidence"] = confidence
        row["field_provenance"].append({"field_id": identifier, "locators": locators})
    return row


def _construct_row(
    construct: dict[str, Any], pmcid: str, pdb_id: str, linkage: str
) -> dict[str, Any]:
    identifiers = construct["protein_identifiers"]
    if not isinstance(identifiers, dict):
        raise ExtractionError("protein_identifiers must be an object")
    fields = construct["fields"]
    target_field = fields.get("T1") if isinstance(fields.get("T1"), dict) else {}
    protein_name = target_field.get("value")
    confidence = target_field.get("confidence", 0.0)
    evidence = target_field.get("evidence_locators", [])
    return {
        "pdb_id": pdb_id,
        "pmcid": pmcid,
        "construct_id": construct["construct_id"],
        "pdb_linkage": linkage,
        "protein_name": protein_name if isinstance(protein_name, str) else None,
        "gene_names": _as_strings(identifiers.get("gene_names", [])),
        "organisms": _as_strings(identifiers.get("organisms", [])),
        "uniprot_ids": _as_strings(identifiers.get("uniprot_ids", [])),
        "genbank_ids": _as_strings(identifiers.get("genbank_ids", [])),
        "other_identifiers": _as_strings(identifiers.get("other_identifiers", [])),
        "n_terminal_tags": _as_strings(construct["n_terminal_tags"]),
        "c_terminal_tags": _as_strings(construct["c_terminal_tags"]),
        "confidence": _confidence(confidence, "construct") if confidence != 0.0 else 0.0,
        "evidence_locators": _as_strings(evidence),
    }


def _deferred_info(result: dict[str, Any], source: dict[str, Any]) -> str:
    messages = []
    for lead in result["supplementary_leads"]:
        messages.append(f"Supplementary material: {lead['description']}")
    if result["protocol_status"] == "supplement":
        for supplement in source["supplements"]:
            messages.append(
                f"Supplementary material: {supplement['label']} {supplement['guessed_file']}"
            )
    for lead in result["citation_leads"]:
        identifiers = lead["identifiers"]
        rendered_ids = ", ".join(
            f"{name}={','.join(str(item) for item in values)}"
            for name, values in identifiers.items()
        )
        message = f"Reference: {lead['description']}"
        messages.append(message + (f", {rendered_ids}" if rendered_ids else ""))
    if result["protocol_status"] == "citation":
        for reference in source["references"]:
            identifiers = reference["identifiers"]
            rendered_ids = ", ".join(
                f"{name}={','.join(str(item) for item in values)}"
                for name, values in identifiers.items()
                if values
            )
            message = f"Reference {reference['label']}: {reference['text']}"
            messages.append(message + (f", {rendered_ids}" if rendered_ids else ""))
    return " | ".join(messages)


def _canonical_status(result: dict[str, Any]) -> str:
    if result["protocol_status"] == "retrieved" and result["protocol_chunks"]:
        return "retrieved"
    if result["protocol_status"] == "supplement" and result["supplementary_leads"]:
        return "supplement"
    if result["protocol_status"] == "citation" and result["citation_leads"]:
        return "citation"
    return "missing"


def _synthetic_missing() -> dict[str, Any]:
    return {
        "protocol_status": "missing",
        "protocol_chunks": [],
        "constructs": [],
        "supplementary_leads": [],
        "citation_leads": [],
    }


def process_publication(
    target_dir: Path, publication: dict[str, Any], base_url: str, model: str, run_dir: Path
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    pmcid = publication["pmcid"]
    package_dir = target_dir / "publications" / str(publication["download_version"])
    source = (
        parse_jats(package_dir)
        if package_dir.exists()
        else {"jats_files": [], "chunks": [], "supplements": [], "references": []}
    )
    raw_response: dict[str, Any] | None = None
    if source["jats_files"]:
        prompt = build_prompt(source, pmcid, publication["pdb_ids"])
        raw_response = _ollama_json(base_url, model, prompt)
        known_locators = {chunk["locator"] for chunk in source["chunks"]}
        result = validate_model_output(raw_response, known_locators)
    else:
        result = _synthetic_missing()
    status = _canonical_status(result)
    protocol_text = "\n\n".join(chunk["text"] for chunk in result["protocol_chunks"])
    source_file = ",".join(source["jats_files"]) if source["jats_files"] else ""
    protocol_rows = [
        {
            "pdb_id": pdb_id,
            "pmcid": pmcid,
            "source_file": source_file,
            "source_format": "JATS" if source_file else "",
            "protocol_text": protocol_text,
            "status": status,
            "evidence_locators": [chunk["locator"] for chunk in result["protocol_chunks"]],
            "deferred_source_info": _deferred_info(result, source),
        }
        for pdb_id in publication["pdb_ids"]
    ]
    rows: dict[str, list[dict[str, Any]]] = {host: [] for host in HOST_FIELDS}
    rows["protocols"] = protocol_rows
    rows["constructs"] = []
    for construct in result["constructs"]:
        explicit = sorted(set(construct["pdb_ids"]) & set(publication["pdb_ids"]))
        pdb_ids = explicit or publication["pdb_ids"]
        linkage = "explicit" if explicit else "publication_inferred"
        for pdb_id in pdb_ids:
            rows["constructs"].append(_construct_row(construct, pmcid, pdb_id, linkage))
            if construct["host"] is not None:
                rows[construct["host"]].append(
                    _expert_row(construct["host"], construct, pmcid, pdb_id, linkage)
                )
    record = {
        "metadata": {
            "pmcid": pmcid,
            "pdb_ids": publication["pdb_ids"],
            "download_version": publication["download_version"],
            "schema_version": SCHEMA_VERSION,
            "model": model,
            "created_at": _now(),
        },
        # "source": source,
        "ollama_response": raw_response,
        "normalized_result": result,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{pmcid}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return rows, record


def _load_state(path: Path) -> pl.DataFrame:
    return pl.read_parquet(path) if path.exists() else _frame([], STATE_SCHEMA)


def _successful(state: pl.DataFrame, pmcid: str, version: str) -> bool:
    return (
        state.filter(
            (pl.col("pmcid") == pmcid)
            & (pl.col("download_version") == version)
            & (pl.col("status") == "success")
        ).height
        > 0
    )


def _update_state(path: Path, entry: dict[str, Any]) -> None:
    existing = _load_state(path)
    filtered = existing.filter(pl.col("pmcid") != entry["pmcid"])
    pl.concat([filtered, _frame([entry], STATE_SCHEMA)], how="diagonal_relaxed").write_parquet(path)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    try:
        publications = select_publications(args.target_dir, args)
    except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
        log.error("Could not select downloaded publications: %s", exc)
        return 1
    if not publications:
        log.error("No downloaded publications matched the selection.")
        return 1
    try:
        preflight_ollama(args.ollama_url)
    except requests.RequestException as exc:
        log.error("Ollama is unavailable at %s: %s", args.ollama_url, exc)
        return 1

    state_path = args.target_dir / EXTRACTION_STATE_FILENAME
    state = _load_state(state_path)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    run_dir = args.target_dir / "llm_runs" / run_id
    failed = False
    for pmcid, publication in sorted(publications.items()):
        version = str(publication["download_version"])
        if not args.force and _successful(state, pmcid, version):
            log.info("Skipping already successful %s (%s)", pmcid, version)
            continue
        try:
            rows, _ = process_publication(
                args.target_dir, publication, args.ollama_url, args.ollama_model, run_dir
            )
            for host, filename in HOST_FILENAMES.items():
                _upsert(args.target_dir / filename, pmcid, rows[host], _expert_schema(host))
            _upsert(args.target_dir / PROTOCOLS_FILENAME, pmcid, rows["protocols"], PROTOCOL_SCHEMA)
            _upsert(
                args.target_dir / CONSTRUCTS_FILENAME, pmcid, rows["constructs"], CONSTRUCT_SCHEMA
            )
            _update_state(
                state_path,
                {
                    "pmcid": pmcid,
                    "download_version": version,
                    "status": "success",
                    "run_id": run_id,
                    "error": None,
                    "updated_at": _now(),
                },
            )
            state = _load_state(state_path)
        except Exception as exc:
            failed = True
            log.error("Could not extract %s: %s", pmcid, exc, exc_info=exc)
            _update_state(
                state_path,
                {
                    "pmcid": pmcid,
                    "download_version": version,
                    "status": "failed",
                    "run_id": run_id,
                    "error": str(exc),
                    "updated_at": _now(),
                },
            )
            state = _load_state(state_path)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
