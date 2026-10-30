"""Structures du référentiel HAL (`ref/structure`), référentiel externe des structures.

Chaque période d'une structure a sa fiche, avec ses dates de validité ; l'ancienne passe au statut `OLD`. Une fiche en double est fondue dans une structure conservée, qui la liste dans ses alias.
"""

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from domain.countries import normalize_country_code
from domain.structures.identifiers import RorId
from domain.types import JsonValue, as_sequence, as_str


class HalStructureStatus(StrEnum):
    """Statut d'une structure dans le référentiel HAL."""

    VALID = "VALID"
    OLD = "OLD"
    INCOMING = "INCOMING"


# Champs de `ref/structure` lus par `parse_hal_structure`.
HAL_STRUCTURE_FIELDS = (
    "docid",
    "name_s",
    "acronym_s",
    "type_s",
    "country_s",
    "valid_s",
    "ror_s",
    "startDate_s",
    "endDate_s",
    "parentDocid_i",
    "aliasDocid_i",
)


@dataclass(frozen=True, slots=True)
class HalStructure:
    hal_structure_id: int
    name: str
    acronym: str | None
    structure_type: str
    country_code: str | None
    status: HalStructureStatus
    ror_id: RorId | None
    start_date: datetime.date | None
    end_date: datetime.date | None
    parent_ids: tuple[int, ...]
    alias_ids: tuple[int, ...]


def _date(value: JsonValue) -> datetime.date | None:
    text = as_str(value)
    try:
        return datetime.date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def _ids(value: JsonValue) -> tuple[int, ...]:
    return tuple(sorted({int(str(v)) for v in as_sequence(value) if str(v).isdigit()}))


def parse_hal_structure(doc: Mapping[str, JsonValue]) -> HalStructure | None:
    """Lit la structure d'un document de `ref/structure`, `None` sans identifiant, nom, type ou statut reconnu. Le premier ROR valide est retenu."""
    docid, name, structure_type = (
        as_str(doc.get("docid")),
        as_str(doc.get("name_s")),
        as_str(doc.get("type_s")),
    )
    try:
        status = HalStructureStatus(as_str(doc.get("valid_s")) or "")
    except ValueError:
        return None
    if not (docid and docid.isdigit() and name and structure_type):
        return None
    hal_structure_id = int(docid)
    rors = [r for v in as_sequence(doc.get("ror_s")) if (r := RorId.try_parse(as_str(v)))]
    return HalStructure(
        hal_structure_id=hal_structure_id,
        name=name,
        acronym=as_str(doc.get("acronym_s")) or None,
        structure_type=structure_type,
        country_code=normalize_country_code(as_str(doc.get("country_s"))),
        status=status,
        ror_id=rors[0] if rors else None,
        start_date=_date(doc.get("startDate_s")),
        end_date=_date(doc.get("endDate_s")),
        parent_ids=tuple(i for i in _ids(doc.get("parentDocid_i")) if i != hal_structure_id),
        alias_ids=tuple(i for i in _ids(doc.get("aliasDocid_i")) if i != hal_structure_id),
    )
