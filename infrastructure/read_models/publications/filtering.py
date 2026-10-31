"""Conditions de filtrage des publications, partagées par la liste, son export, ses facettes et les statistiques.

Toutes ces lectures assemblent leur WHERE par `publication_filter_where` : elles comptent donc le même ensemble de publications sous les mêmes filtres.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text

from infrastructure.read_models.filters import (
    PUBLICATION_IS_IN_PERIMETER,
    WhereClause,
    access_clause,
    apc_clause,
    assemble_where,
    author_clause,
    author_position_clause,
    country_clause,
    doc_type_clause,
    doi_agency_clause,
    excluded_doc_type_clause,
    hal_status_clause,
    in_perimeter_person_clause,
    lab_clause,
    language_clause,
    license_clause,
    monograph_id_clause,
    no_lab_clause,
    oa_clause,
    partner_clause,
    person_clause,
    publisher_id_clause,
    search_clause,
    serial_id_clause,
    source_clause,
    subject_clause,
    year_clause,
)
from infrastructure.read_models.perimeters.queries import get_persons_structure_ids_list
from infrastructure.read_models.publications.models import PublicationFilters

# Dimension dont une facette écarte le filtre. `person` désigne le filtre par auteur (`author_id`).
FilterDimension = Literal[
    "year",
    "lab",
    "doc_type",
    "access",
    "oa_status",
    "license",
    "doi_agency",
    "source",
    "apc",
    "publisher",
    "serial",
    "country",
    "language",
    "hal_status",
    "in_perimeter",
    "author_position",
    "subject",
    "person",
    "partner",
]


@dataclass(frozen=True, slots=True)
class FilterContext:
    """Valeurs lues en base, nécessaires à certaines conditions."""

    perimeter_structure_ids: list[int]
    """Structures du périmètre des personnes, pour le filtre APC."""
    lab_hal_collection: str | None
    """Collection HAL du laboratoire quand un seul est sélectionné ; le statut HAL se lit au regard de cette collection."""


def lab_hal_collection(conn: Connection, lab_ids: list[int]) -> str | None:
    """Renvoie la collection HAL du laboratoire quand un seul est sélectionné."""
    if len(lab_ids) != 1:
        return None
    row = conn.execute(
        text("SELECT hal_collection FROM structures WHERE id = :sid"), {"sid": lab_ids[0]}
    ).one_or_none()
    return row.hal_collection if row else None


def filter_context(conn: Connection, filters: PublicationFilters) -> FilterContext:
    """Lit une fois par requête les valeurs nécessaires aux conditions."""
    return FilterContext(
        perimeter_structure_ids=get_persons_structure_ids_list(conn),
        lab_hal_collection=lab_hal_collection(conn, filters.lab_ids),
    )


def _scope_clause(filters: PublicationFilters, skip: FilterDimension | None) -> WhereClause | None:
    """Renvoie la condition de l'ensemble de départ : les publications de la personne, sinon celles des laboratoires sélectionnés, sinon celles du périmètre.

    Les laboratoires sélectionnés délimitent l'ensemble par le filtre laboratoire. Une facette qui écarte ce filtre part donc du périmètre.
    """
    if filters.person_id:
        return person_clause(filters.person_id)
    if filters.lab_ids and skip != "lab":
        return None
    return WhereClause(PUBLICATION_IS_IN_PERIMETER, {})


def _lab_filter_clause(filters: PublicationFilters) -> WhereClause | None:
    if filters.lab_ids:
        return lab_clause(filters.lab_ids)
    if filters.lab_none:
        return no_lab_clause()
    return None


def publication_filter_where(
    filters: PublicationFilters,
    context: FilterContext,
    skip: FilterDimension | None = None,
) -> tuple[str, dict[str, object]]:
    """Renvoie le WHERE des publications `p` sous les filtres, et ses paramètres liés.

    `skip` écarte le filtre d'une dimension, pour la facette de cette dimension. Le statut HAL s'applique seulement avec un seul laboratoire sélectionné.
    """
    f = filters
    by_dimension: dict[FilterDimension, WhereClause | None] = {
        "year": year_clause(f.years),
        "lab": _lab_filter_clause(f),
        "doc_type": doc_type_clause(f.doc_types),
        "access": access_clause(f.access),
        "oa_status": oa_clause(f.oa_status),
        "license": license_clause(f.license),
        "doi_agency": doi_agency_clause(f.doi_agency),
        "source": source_clause(f.source_values),
        "apc": apc_clause(f.has_apc, context.perimeter_structure_ids),
        "publisher": publisher_id_clause(f.publisher_id),
        "serial": serial_id_clause(f.serial_id),
        "country": country_clause(f.country_values),
        "language": language_clause(f.language_codes),
        "hal_status": (
            hal_status_clause(f.hal_status_values, context.lab_hal_collection)
            if len(f.lab_ids) == 1
            else None
        ),
        "in_perimeter": in_perimeter_person_clause(f.in_perimeter, f.person_id),
        "author_position": author_position_clause(f.person_id, f.lab_ids, f.author_position),
        "subject": subject_clause(f.subject_ids),
        "person": author_clause(f.author_id),
        "partner": partner_clause(f.partner_rors),
    }
    clauses: list[WhereClause | None] = [
        _scope_clause(f, skip),
        excluded_doc_type_clause(f.excluded_types),
        monograph_id_clause(f.monograph_id),
        search_clause(f.search),
        *(clause for dimension, clause in by_dimension.items() if dimension != skip),
    ]
    return assemble_where(clauses)
