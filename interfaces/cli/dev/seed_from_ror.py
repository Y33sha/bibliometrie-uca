# STATUS: recurring (dev)
"""Génère le seed d'un établissement à partir de ROR : l'établissement, ses structures filles, leurs formes de noms et le périmètre qui les réunit.

Usage :
    python -m interfaces.cli.dev.seed_from_ror 04vfs2w97 --code lorraine --output instances/lorraine/seed.sql

La racine est une université. Une fille ROR devient un laboratoire (`facility`), une école (`education`) ou un CHU (`healthcare`). Les filles d'un autre type sont écartées et listées. Les formes de noms viennent des libellés, alias et acronymes ROR. Un acronyme exige une frontière de mot et, pour une fille, la présence de la racine dans l'adresse. L'identifiant OpenAlex de la racine est lu dans OpenAlex d'après son ROR. Les collections HAL, les RNSR et les identifiants WoS, ScanR et theses.fr restent à renseigner.
"""

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from domain.normalize import normalize_text
from domain.structures.identifiers import normalize_ror_id
from domain.structures.name_forms import is_short_form
from domain.structures.structure import StructureType
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from infrastructure.db import tables
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import get_openalex_api_key, get_polite_pool_email_optional
from infrastructure.sources.http_retry import http_request_with_retry
from interfaces.cli.dev.generate_seed import (
    INSTITUTION_SEED,
    SeedSection,
    exported_columns,
    write_seed,
)

ROR_API = "https://api.ror.org/v2/organizations"

_CHILD_TYPES = {
    "facility": StructureType.LABO,
    "education": StructureType.ECOLE,
    "healthcare": StructureType.CHU,
}

# Une forme de deux caractères (« UL ») désigne trop de choses pour identifier une structure dans une adresse.
MIN_FORM_LENGTH = 3

_EXTRACTION_DESCRIPTION = (
    "Périmètre pour déterminer les structures à interroger lors de l'extraction"
)


@dataclass(frozen=True)
class RorOrganization:
    """Ce que le seed retient d'une fiche ROR."""

    ror_id: str
    name: str
    types: tuple[str, ...]
    acronyms: tuple[str, ...]
    labels: tuple[str, ...]
    child_ids: tuple[str, ...]

    @property
    def acronym(self) -> str | None:
        return self.acronyms[0] if self.acronyms else None


@dataclass(frozen=True)
class InstitutionSeed:
    """Sections du seed d'établissement, et filles ROR écartées faute de type de structure."""

    sections: list[SeedSection]
    skipped: list[RorOrganization]


def parse_organization(record: Mapping[str, JsonValue]) -> RorOrganization:
    """Fiche ROR (API v2) réduite à son identifiant, ses noms, ses types et ses filles."""
    names = [as_mapping(n) for n in as_sequence(record.get("names"))]

    def values(kind: str) -> tuple[str, ...]:
        return tuple(
            value
            for n in names
            if kind in as_sequence(n.get("types")) and (value := as_str(n.get("value")))
        )

    display = values("ror_display")
    relationships = [as_mapping(r) for r in as_sequence(record.get("relationships"))]
    return RorOrganization(
        ror_id=_ror_short_id(as_str(record.get("id")) or ""),
        name=display[0] if display else "",
        types=tuple(t for t in as_sequence(record.get("types")) if isinstance(t, str)),
        acronyms=values("acronym"),
        labels=values("ror_display") + values("label") + values("alias"),
        child_ids=tuple(
            _ror_short_id(as_str(r.get("id")) or "")
            for r in relationships
            if r.get("type") == "child"
        ),
    )


def _ror_short_id(ror_url: str) -> str:
    return normalize_ror_id(ror_url) or ror_url


def child_structure_type(org: RorOrganization) -> StructureType | None:
    """Type de structure d'une fille ROR, d'après le premier de ses types ROR qui en a un."""
    return next((_CHILD_TYPES[t] for t in org.types if t in _CHILD_TYPES), None)


def name_forms(
    org: RorOrganization, *, context_id: int | None
) -> dict[str, tuple[bool, list[int] | None]]:
    """Formes de noms normalisées d'une structure : `{forme: (frontière de mot, contexte requis)}`.

    Un acronyme exige une frontière de mot, et la présence de `context_id` dans l'adresse quand il est fourni.
    """
    forms: dict[str, tuple[bool, list[int] | None]] = {}
    for label in org.labels:
        form = normalize_text(label)
        if len(form) >= MIN_FORM_LENGTH:
            forms.setdefault(form, (is_short_form(form), None))
    for acronym in org.acronyms:
        form = normalize_text(acronym)
        if len(form) >= MIN_FORM_LENGTH:
            forms[form] = (True, [context_id] if context_id is not None else None)
    return forms


def _structure_code(org: RorOrganization, taken: set[str]) -> str:
    """Code unique de la structure : acronyme ou nom normalisé, suffixé de l'identifiant ROR en cas de doublon."""
    base = normalize_text(org.acronym or org.name).replace(" ", "_")[:40] or org.ror_id
    code = base if base not in taken else f"{base}_{org.ror_id}"
    taken.add(code)
    return code


def _rows(table_name: str, dicts: list[dict[str, JsonValue]]) -> list[tuple[JsonValue, ...]]:
    columns = exported_columns(tables.metadata.tables[table_name])
    return [tuple(row[column] for column in columns) for row in dicts]


def build_institution_seed(
    root: RorOrganization,
    children: list[RorOrganization],
    openalex_ids: list[str],
    perimeter_code: str,
) -> InstitutionSeed:
    """Structures, tutelles, périmètre, formes de noms et configuration du seed d'un établissement."""
    taken: set[str] = set()
    structures: list[dict[str, JsonValue]] = []
    tutelles: list[dict[str, JsonValue]] = []
    forms: list[dict[str, JsonValue]] = []
    skipped: list[RorOrganization] = []

    def add_structure(
        org: RorOrganization, structure_type: StructureType, api_ids: JsonValue
    ) -> int:
        structure_id = len(structures) + 1
        structures.append(
            {
                "id": structure_id,
                "code": _structure_code(org, taken),
                "name": org.name,
                "acronym": org.acronym,
                "structure_type": structure_type.value,
                "ror_id": org.ror_id,
                "rnsr_id": None,
                "hal_collection": None,
                "api_ids": api_ids,
            }
        )
        return structure_id

    def add_forms(org: RorOrganization, structure_id: int, context_id: int | None) -> None:
        for form, (word_boundary, context) in name_forms(org, context_id=context_id).items():
            forms.append(
                {
                    "id": len(forms) + 1,
                    "structure_id": structure_id,
                    "form_text": form,
                    "is_word_boundary": word_boundary,
                    "requires_context_of": context,
                    "is_excluding": False,
                }
            )

    root_api_ids: JsonValue = {"openalex": list(openalex_ids)} if openalex_ids else None
    root_id = add_structure(root, StructureType.UNIVERSITE, root_api_ids)
    add_forms(root, root_id, None)

    for child in children:
        structure_type = child_structure_type(child)
        if structure_type is None:
            skipped.append(child)
            continue
        child_id = add_structure(child, structure_type, None)
        tutelles.append({"id": len(tutelles) + 1, "parent_id": root_id, "child_id": child_id})
        add_forms(child, child_id, root_id)

    perimeters: list[dict[str, JsonValue]] = [
        {
            "id": 1,
            "code": perimeter_code,
            "name": root.acronym or root.name,
            "root_structure_ids": [root_id],
        }
    ]
    config: list[dict[str, JsonValue]] = [
        {
            "key": "perimeter_extraction",
            "value": perimeter_code,
            "description": _EXTRACTION_DESCRIPTION,
        }
    ]

    rows_by_table = {
        "structures": structures,
        "structure_tutelles": tutelles,
        "perimeters": perimeters,
        "structure_name_forms": forms,
        "config": config,
    }
    sections = [
        SeedSection(
            spec["table"],
            _rows(spec["table"].name, rows_by_table[spec["table"].name]),
            spec.get("where"),
        )
        for spec in INSTITUTION_SEED.tables
    ]
    return InstitutionSeed(sections=sections, skipped=skipped)


def fetch_ror(ror_id: str) -> RorOrganization:
    return parse_organization(
        as_mapping(http_request_with_retry("GET", f"{ROR_API}/{ror_id}", label=f"ROR {ror_id}"))
    )


def fetch_openalex_ids(ror_id: str) -> list[str]:
    """Identifiant OpenAlex de l'institution désignée par `ror_id`."""
    params: dict[str, str | int | float | bool | None] = {"select": "id"}
    if api_key := get_openalex_api_key():
        params["api_key"] = api_key
    elif email := get_polite_pool_email_optional():
        params["mailto"] = email
    data = as_mapping(
        http_request_with_retry(
            "GET",
            f"{API_BASE_URLS['openalex_institutions']}/ror:{ror_id}",
            params=params,
            label=f"OpenAlex ror:{ror_id}",
        )
    )
    openalex_url = as_str(data.get("id"))
    return [openalex_url.rsplit("/", 1)[-1]] if openalex_url else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère le seed d'un établissement depuis ROR")
    parser.add_argument("ror_id", help="Identifiant ROR de l'établissement (ex. 04vfs2w97)")
    parser.add_argument("--code", required=True, help="Code du périmètre de l'établissement")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ror_id = normalize_ror_id(args.ror_id)
    if ror_id is None:
        raise SystemExit(f"Identifiant ROR invalide : {args.ror_id}")
    root = fetch_ror(ror_id)
    children = [fetch_ror(child_id) for child_id in root.child_ids]
    seed = build_institution_seed(root, children, fetch_openalex_ids(ror_id), args.code)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_seed(INSTITUTION_SEED.description, args.output, seed.sections)
    for org in seed.skipped:
        print(f"  fille écartée : {org.name} ({org.ror_id}, types {', '.join(org.types)})")


if __name__ == "__main__":
    main()
