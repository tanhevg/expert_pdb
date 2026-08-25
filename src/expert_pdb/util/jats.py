from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any
import re

NS_XLINK = "{http://www.w3.org/1999/xlink}href"
IDENTIFIER_PATTERNS = {
    "doi": re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE),
    "pmid": re.compile(r"\bPMID\s*[:=]?\s*(\d+)\b", re.IGNORECASE),
    "pmcid": re.compile(r"\bPMC\d+\b", re.IGNORECASE),
}

def compact_jats(filename: Path) -> str:
    jats_root = ET.parse(filename).getroot()
    body = jats_root.find('./body')
    abstract = jats_root.find('.//abstract')
    short_article = ET.Element('short_article')
    if abstract is not None:
        short_article.append(abstract)
    assert body is not None
    short_article.append(body)
    ret = ET.tostring(short_article, 'unicode', method='xml')
    return ret


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


def jats_to_json(package_dir: Path) -> dict[str, Any]:
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
