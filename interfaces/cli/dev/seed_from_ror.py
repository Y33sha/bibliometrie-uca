# STATUS: recurring (dev)
"""Génère le seed d'un établissement à partir de ROR : l'établissement, ses structures filles, leurs formes de noms et le périmètre qui les réunit.

Usage :
    uv run python -m interfaces.cli.dev.seed_from_ror 04vfs2w97 --code lorraine --output instances/lorraine/seed.sql

La racine est une université. Une fille ROR devient un laboratoire (`facility`), une école (`education`) ou un CHU (`healthcare`). Les filles d'un autre type sont écartées et listées. Le nom d'une structure est le nom affiché par ROR, ou son premier libellé de plusieurs mots quand le nom affiché tient en un mot. Les formes de noms viennent des libellés, alias et acronymes ROR. Une forme d'un seul mot exige une frontière de mot et, pour une fille, la présence de la racine dans l'adresse. L'identifiant OpenAlex de la racine est lu dans OpenAlex d'après son ROR. La collection HAL de chaque structure est déduite des dépôts HAL (`fetch_hal_collection`). Les RNSR et les identifiants WoS, ScanR et theses.fr restent à renseigner.
"""

import argparse
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from domain.config import (
    BRAND_HUE_KEY,
    DEFAULT_BRAND_HUE,
    DEFAULT_INSTITUTION_COUNTRY,
    INSTITUTION_COUNTRY_KEY,
    PERIMETER_EXTRACTION_KEY,
    PERIMETER_PERSONS_KEY,
    SITE_TITLE_KEY,
)
from domain.countries import normalize_country_code
from domain.normalize import normalize_text
from domain.structures.identifiers import normalize_ror_id
from domain.structures.name_forms import is_short_form
from domain.structures.structure import StructureType
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str
from infrastructure.db import tables
from interfaces.cli.dev.generate_seed import (
    INSTITUTION_SEED,
    SeedSection,
    exported_columns,
    write_seed,
)
from pipeline.http.circuit_breaker import source_circuit_breaker
from pipeline.http.http_retry import http_request_with_retry
from pipeline.http.polite_pool import get_polite_pool_email_optional
from pipeline.ingestion.api_params import API_BASE_URLS, request_budget
from pipeline.ingestion.credentials import get_openalex_api_key

ROR_API = "https://api.ror.org/v2/organizations"

_CHILD_TYPES = {
    "facility": StructureType.LABO,
    "education": StructureType.ECOLE,
    "healthcare": StructureType.CHU,
}

# Une forme de deux caractères (« UL ») désigne trop de choses pour identifier une structure dans une adresse.
MIN_FORM_LENGTH = 3

# Code d'unité de recherche (« UMR 7039 », « EA4432 »), écarté comme nom de structure.
_UNIT_CODE = re.compile(r"^(?:UMR|UMRS|UR|EA|UPR|FRE|UMS|USR|UAR|IRL)(?:\s|\d)", re.IGNORECASE)

# Collection HAL d'une structure : part minimale de ses dépôts contenus dans la collection, et indice de Jaccard minimal entre les dépôts de la structure et ceux de la collection.
MIN_COLLECTION_COVERAGE = 0.5
MIN_COLLECTION_JACCARD = 0.15
# Collections examinées : les plus fréquentes parmi les dépôts de la structure.
HAL_COLLECTION_CANDIDATES = 25

# Le périmètre de l'établissement sert au moissonnage et à la création des personnes.
_PERIMETER_DESCRIPTIONS = {
    PERIMETER_EXTRACTION_KEY: "Périmètre pour déterminer les structures à interroger lors de l'extraction",
    PERIMETER_PERSONS_KEY: "Périmètre pour la création des personnes",
}
_SITE_TITLE_DESCRIPTION = (
    "Titre de l'application. Vide : « Bibliométrie » suivi du nom de l'établissement."
)
_BRAND_HUE_DESCRIPTION = "Teinte de l'interface : angle OKLCH en degrés, de 0 à 359."
_INSTITUTION_COUNTRY_DESCRIPTION = "Pays de l'établissement, code ISO 3166-1. Une publication co-affiliée à un autre pays est une collaboration internationale."


@dataclass(frozen=True)
class RorOrganization:
    """Fiche ROR réduite aux champs retenus par le seed."""

    ror_id: str
    name: str
    types: tuple[str, ...]
    acronyms: tuple[str, ...]
    labels: tuple[str, ...]
    child_ids: tuple[str, ...]
    country_code: str | None = None

    @property
    def acronym(self) -> str | None:
        return self.acronyms[0] if self.acronyms else None


@dataclass(frozen=True)
class InstitutionSeed:
    """Sections du seed d'établissement, et filles ROR écartées faute de type de structure."""

    sections: list[SeedSection]
    skipped: list[RorOrganization]


def parse_organization(record: Mapping[str, JsonValue]) -> RorOrganization:
    """Réduit une fiche ROR (API v2) à son identifiant, ses noms, ses types, ses filles et le pays de sa première localisation.

    Quand le nom affiché tient en un mot (« CRAN »), le nom est le premier libellé de plusieurs mots, et le nom affiché sert d'acronyme.
    """
    names = [as_mapping(n) for n in as_sequence(record.get("names"))]

    def values(kind: str) -> tuple[str, ...]:
        return tuple(
            value
            for n in names
            if kind in as_sequence(n.get("types")) and (value := as_str(n.get("value")))
        )

    display = values("ror_display")[0] if values("ror_display") else ""
    labels = values("ror_display") + values("label") + values("alias")
    full_name = None
    if " " not in display.strip():
        full_name = next((n for n in labels if " " in n and not _UNIT_CODE.match(n)), None)
    acronyms = values("acronym") or ((display,) if full_name else ())
    relationships = [as_mapping(r) for r in as_sequence(record.get("relationships"))]
    locations = [as_mapping(loc) for loc in as_sequence(record.get("locations"))]
    country_code = (
        normalize_country_code(
            as_str(as_mapping(locations[0].get("geonames_details")).get("country_code"))
        )
        if locations
        else None
    )
    return RorOrganization(
        ror_id=_ror_short_id(as_str(record.get("id")) or ""),
        name=full_name or display,
        types=tuple(t for t in as_sequence(record.get("types")) if isinstance(t, str)),
        acronyms=acronyms,
        labels=labels,
        child_ids=tuple(
            _ror_short_id(as_str(r.get("id")) or "")
            for r in relationships
            if r.get("type") == "child"
        ),
        country_code=country_code,
    )


def _ror_short_id(ror_url: str) -> str:
    return normalize_ror_id(ror_url) or ror_url


def child_structure_type(org: RorOrganization) -> StructureType | None:
    """Renvoie le type de structure d'une fille ROR, d'après le premier de ses types ROR associé à un type de structure."""
    return next((_CHILD_TYPES[t] for t in org.types if t in _CHILD_TYPES), None)


def name_forms(
    org: RorOrganization, *, context_id: int | None
) -> dict[str, tuple[bool, list[int] | None]]:
    """Renvoie les formes de noms normalisées d'une structure : `{forme: (frontière de mot, contexte requis)}`.

    Une forme d'un seul mot exige une frontière de mot. Sans chiffre (acronyme, « Silva », « DynAMic »), elle exige aussi la présence de `context_id` dans l'adresse quand il est fourni. Un code d'unité (« umr7503 ») désigne une seule unité et se passe de contexte.
    """
    context = [context_id] if context_id is not None else None
    forms: dict[str, tuple[bool, list[int] | None]] = {}
    for text in (*org.labels, *org.acronyms):
        form = normalize_text(text)
        if len(form) < MIN_FORM_LENGTH:
            continue
        if " " in form:
            forms[form] = (is_short_form(form), None)
        else:
            forms[form] = (True, None if any(c.isdigit() for c in form) else context)
    return forms


def _structure_code(org: RorOrganization, taken: set[str]) -> str:
    """Renvoie le code unique de la structure : acronyme ou nom normalisé, suffixé de l'identifiant ROR en cas de doublon."""
    base = normalize_text(org.acronym or org.name).replace(" ", "_")[:40] or org.ror_id
    code = base if base not in taken else f"{base}_{org.ror_id}"
    taken.add(code)
    return code


def _rows(table_name: str, dicts: list[dict[str, JsonValue]]) -> list[tuple[JsonValue, ...]]:
    # `metadata.tables` indexe les tables par `schéma.nom`.
    table = next(t for t in tables.metadata.tables.values() if t.name == table_name)
    columns = exported_columns(table)
    return [tuple(row[column] for column in columns) for row in dicts]


def build_institution_seed(
    root: RorOrganization,
    children: list[RorOrganization],
    openalex_ids: list[str],
    perimeter_code: str,
    hal_collections: Mapping[str, str] | None = None,
) -> InstitutionSeed:
    """Construit les structures, tutelles, périmètre, formes de noms et configuration du seed d'un établissement.

    Args:
        hal_collections: collection HAL par identifiant ROR.
    """
    hal_collections = hal_collections or {}
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
                "hal_collection": hal_collections.get(org.ror_id),
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
        {"key": key, "value": perimeter_code, "description": description}
        for key, description in _PERIMETER_DESCRIPTIONS.items()
    ]
    config.append({"key": SITE_TITLE_KEY, "value": "", "description": _SITE_TITLE_DESCRIPTION})
    config.append(
        {"key": BRAND_HUE_KEY, "value": DEFAULT_BRAND_HUE, "description": _BRAND_HUE_DESCRIPTION}
    )
    config.append(
        {
            "key": INSTITUTION_COUNTRY_KEY,
            "value": root.country_code or DEFAULT_INSTITUTION_COUNTRY,
            "description": _INSTITUTION_COUNTRY_DESCRIPTION,
        }
    )

    rows_by_table = {
        "structures": structures,
        "structure_parents": tutelles,
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
    """Renvoie l'identifiant OpenAlex de l'institution désignée par `ror_id`."""
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


def choose_collection(
    structure_docs: int, candidates: Sequence[tuple[str, int]], size_of: Callable[[str], int]
) -> str | None:
    """Choisit la collection HAL aux dépôts les plus proches de ceux d'une structure, au sens de l'indice de Jaccard.

    Args:
        candidates: `(code, dépôts de la structure dans la collection)`.
        size_of: nombre de dépôts d'une collection, appelé seulement pour les collections couvrant assez la structure.
    """
    best: tuple[float, str] | None = None
    for code, shared in candidates:
        if shared < MIN_COLLECTION_COVERAGE * structure_docs:
            continue
        jaccard = shared / (structure_docs + size_of(code) - shared)
        if jaccard >= MIN_COLLECTION_JACCARD and (best is None or jaccard > best[0]):
            best = (jaccard, code)
    return best[1] if best else None


def acronym_collection_accepted(collection_docs: int, institution_docs: int) -> bool:
    """Renvoie vrai quand la collection existe et que la plupart de ses dépôts appartiennent à l'établissement."""
    return collection_docs > 0 and institution_docs >= MIN_COLLECTION_COVERAGE * collection_docs


def _hal_get(url: str, params: Mapping[str, str | int], label: str) -> Mapping[str, JsonValue]:
    return as_mapping(
        http_request_with_retry("GET", url, params={**params, "wt": "json"}, label=label)
    )


def _hal_count(query: str) -> int:
    data = _hal_get(API_BASE_URLS["hal"], {"q": query, "rows": 0}, f"HAL {query}")
    return as_int(as_mapping(data.get("response")).get("numFound")) or 0


def fetch_hal_structure_ids(ror_id: str) -> list[str]:
    """Renvoie les structures du référentiel HAL, valides ou anciennes, désignées par `ror_id`. Le référentiel écrit le ROR en URL ou en identifiant seul."""
    data = _hal_get(
        API_BASE_URLS["hal_structures"],
        {"q": f'ror_s:("https://ror.org/{ror_id}" OR "{ror_id}")', "fl": "docid", "rows": 100},
        f"HAL structures ror:{ror_id}",
    )
    docs = as_sequence(as_mapping(data.get("response")).get("docs"))
    return [str(as_mapping(d).get("docid")) for d in docs]


def structures_query(structure_ids: Collection[str]) -> str:
    """Renvoie la requête HAL des dépôts d'une des structures `structure_ids`."""
    return f"structId_i:({' OR '.join(structure_ids)})"


def collection_of_structures(structure_ids: Collection[str]) -> str | None:
    """Renvoie la collection HAL choisie par `choose_collection` parmi les plus fréquentes des dépôts des structures HAL `structure_ids`."""
    query = structures_query(structure_ids)
    data = _hal_get(
        API_BASE_URLS["hal"],
        {
            "q": query,
            "rows": 0,
            "facet": "true",
            "facet.field": "collCode_s",
            "facet.limit": HAL_COLLECTION_CANDIDATES,
            "facet.mincount": 1,
        },
        f"HAL collections de {query}",
    )
    structure_docs = as_int(as_mapping(data.get("response")).get("numFound")) or 0
    facets = as_sequence(
        as_mapping(as_mapping(data.get("facet_counts")).get("facet_fields")).get("collCode_s")
    )
    candidates = [
        (str(code), as_int(count) or 0)
        for code, count in zip(facets[::2], facets[1::2], strict=True)
    ]
    return choose_collection(
        structure_docs, candidates, lambda code: _hal_count(f'collCode_s:"{code}"')
    )


def fetch_hal_collection(org: RorOrganization, institution_query: str | None) -> str | None:
    """Renvoie la collection HAL d'une fille de l'établissement.

    Les dépôts des structures HAL de même ROR désignent la collection (`collection_of_structures`). Sans structure HAL de ce ROR, le sigle de `org` sert de code de collection, à condition que `acronym_collection_accepted` le valide d'après les dépôts de l'établissement (`institution_query`).
    """
    structure_ids = fetch_hal_structure_ids(org.ror_id)
    if structure_ids:
        return collection_of_structures(structure_ids)
    if institution_query is None or org.acronym is None:
        return None
    code = org.acronym.upper()
    collection_docs = _hal_count(f'collCode_s:"{code}"')
    if collection_docs == 0:
        return None
    institution_docs = _hal_count(f'collCode_s:"{code}" AND {institution_query}')
    return code if acronym_collection_accepted(collection_docs, institution_docs) else None


def fetch_hal_collections(root: RorOrganization, children: list[RorOrganization]) -> dict[str, str]:
    """Renvoie la collection HAL par identifiant ROR, pour l'établissement et ses filles pourvues d'un type de structure."""
    collections: dict[str, str] = {}
    root_structure_ids = fetch_hal_structure_ids(root.ror_id)
    institution_query = None
    if root_structure_ids:
        institution_query = structures_query(root_structure_ids)
        if code := collection_of_structures(root_structure_ids):
            collections[root.ror_id] = code
    for child in children:
        if child_structure_type(child) is None:
            continue
        if code := fetch_hal_collection(child, institution_query):
            collections[child.ror_id] = code
    return collections


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère le seed d'un établissement depuis ROR")
    parser.add_argument("ror_id", help="Identifiant ROR de l'établissement (ex. 04vfs2w97)")
    parser.add_argument("--code", required=True, help="Code du périmètre de l'établissement")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ror_id = normalize_ror_id(args.ror_id)
    if ror_id is None:
        raise SystemExit(f"Identifiant ROR invalide : {args.ror_id}")
    with source_circuit_breaker("ror"):
        root = fetch_ror(ror_id)
        children = [fetch_ror(child_id) for child_id in root.child_ids]
    with source_circuit_breaker("hal", max_per_second=request_budget("hal")):
        hal_collections = fetch_hal_collections(root, children)
    with source_circuit_breaker("openalex", max_per_second=request_budget("openalex")):
        openalex_ids = fetch_openalex_ids(ror_id)
    seed = build_institution_seed(root, children, openalex_ids, args.code, hal_collections)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_seed(INSTITUTION_SEED.description, args.output, seed.sections)
    for org in seed.skipped:
        print(f"  fille écartée : {org.name} ({org.ror_id}, types {', '.join(org.types)})")
    for org in [root, *children]:
        if org not in seed.skipped and org.ror_id not in hal_collections:
            print(f"  sans collection HAL : {org.name} ({org.ror_id})")


if __name__ == "__main__":
    main()
