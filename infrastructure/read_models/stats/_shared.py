"""Helpers partagés par les agrégats stats : périmètre de base, assemblage des filtres."""

from application.ports.read_models.stats_queries import StatsFilters
from infrastructure.read_models.filters import (
    PUBLICATION_IS_IN_PERIMETER,
    WhereClause,
    apc_clause,
    doc_type_clause,
    lab_clause,
    license_clause,
    oa_clause,
    partner_clause,
    year_clause,
)

# Périmètre commun aux agrégats stats : les publications du périmètre. Le type de document est un filtre comme un autre (`doc_type_clause`).
STATS_BASE = PUBLICATION_IS_IN_PERIMETER


def stats_filter_clauses(
    *,
    perimeter_structure_ids: list[int],
    filters: StatsFilters,
    skip: str = "",
) -> list[WhereClause | None]:
    """Clauses de filtrage communes aux agrégats stats (années, labos, accès, licence, APC, types, éditeur, revue, organisation partenaire). À assembler avec `assemble_where`.

    `skip` omet une dimension (`year` / `lab` / `oa` / `license` / `apc` / `doc_type`) pour les facettes croisées, qui écartent leur propre filtre. Les filtres éditeur, revue et organisation partenaire s'appliquent toujours (la barre ne les facette jamais — ils passent par la recherche serveur).
    """
    out: list[WhereClause | None] = []
    if skip != "year":
        out.append(year_clause(filters.years))
    if skip != "lab":
        out.append(lab_clause(filters.lab_ids))
    if skip != "oa":
        out.append(oa_clause(filters.oa_status))
    if skip != "license":
        out.append(license_clause(filters.license))
    if skip != "apc":
        out.append(apc_clause(filters.has_apc, perimeter_structure_ids))
    if skip != "doc_type":
        out.append(doc_type_clause(filters.doc_types))
    if filters.publisher_ids:
        out.append(
            WhereClause(
                "p.publisher_id = ANY(:flt_publisher_ids)",
                {"flt_publisher_ids": filters.publisher_ids},
            )
        )
    if filters.serial_ids:
        out.append(
            WhereClause(
                "p.serial_id = ANY(:flt_serial_ids)", {"flt_serial_ids": filters.serial_ids}
            )
        )
    out.append(partner_clause(filters.partner_rors))
    return out
