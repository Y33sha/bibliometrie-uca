"""Adresses brutes des publications d'un périmètre (une personne, ou les membres d'un laboratoire pendant leur présence), lues dans les sources des classements sur la famille « publications »."""

from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from domain.types import JsonValue
from infrastructure.read_models._common import page_count
from infrastructure.read_models.addresses.models import (
    ScopedAddressesResponse,
    ScopedAddressOut,
    ScopedAddressStructure,
    ScopedAddressStructureSeries,
    ScopedAddressSummary,
    ScopedAddressYear,
)
from infrastructure.sql_fragments import is_ranking_record, is_raw_address


@dataclass(frozen=True, slots=True)
class AddressScope:
    """Périmètre des contributions : requête SQL qui renvoie leurs identifiants (colonne `id`), et ses paramètres."""

    contributions: str
    binds: dict[str, JsonValue] = field(default_factory=dict)


def person_scope(person_id: int) -> AddressScope:
    """Renvoie le périmètre des contributions de la personne."""
    return AddressScope(
        "SELECT id FROM contributions WHERE person_id = :scope_person_id",
        {"scope_person_id": person_id},
    )


def lab_members_scope(structure_id: int) -> AddressScope:
    """Renvoie le périmètre des contributions des personnes à période de présence dans la structure, sur les publications parues pendant la période. Une date à l'année ou au mois vaut jusqu'au dernier jour de l'année ou du mois : une publication de l'année du départ, datée à l'année, est exclue."""
    return AddressScope(
        # `LATERAL` et `OFFSET 0` : une recherche indexée des contributions par membre, plutôt qu'un parcours de toutes les contributions.
        """SELECT DISTINCT member.id
        FROM hr_periods hp
        CROSS JOIN LATERAL (
            SELECT g.id
            FROM contributions g
            JOIN publications p ON p.id = g.publication_id
            WHERE g.person_id = hp.person_id
              AND p.publication_date >= hp.start_date
              AND (hp.end_date IS NULL
                   OR p.publication_date
                      + ('1 ' || p.publication_date_precision::text)::interval
                      - interval '1 day' <= hp.end_date)
            OFFSET 0
        ) member
        WHERE hp.structure_id = :scope_structure_id""",
        {"scope_structure_id": structure_id},
    )


def _cte(scope: AddressScope) -> str:
    """Renvoie la CTE `scoped_address_publications` : triplets (publication, adresse brute, année) des contributions sources des contributions du périmètre, issues des sources lues par les classements, sur les publications de la famille « publications ». Le périmètre est calculé d'abord (`MATERIALIZED`) : le planificateur sous-estime sa taille."""
    return f"""
        WITH scope_contributions AS MATERIALIZED ({scope.contributions}),
        scoped_address_publications AS (
            SELECT DISTINCT g.publication_id, sca.address_id, p.publication_year
            FROM scope_contributions sg
            JOIN contributions g ON g.id = sg.id
            JOIN publications p ON p.id = g.publication_id
            JOIN aligned_source_contributions m ON m.contribution_id = g.id
            JOIN source_contributions sc ON sc.id = m.source_contribution_id
            JOIN source_records sr ON sr.id = sc.source_record_id
            JOIN source_contribution_addresses sca
              ON sca.source_contribution_id = m.source_contribution_id
            JOIN addresses a ON a.id = sca.address_id
            WHERE {is_raw_address("a")} AND {is_ranking_record("sr", "p")}
        )
    """


def scoped_addresses(
    conn: Connection, scope: AddressScope, *, page: int, per_page: int
) -> ScopedAddressesResponse:
    """Renvoie les adresses brutes des publications du périmètre, les plus fréquentes d'abord, avec leurs structures hors rattachements rejetés."""
    cte = _cte(scope)
    total = conn.execute(
        text(f"{cte} SELECT COUNT(DISTINCT address_id) FROM scoped_address_publications"),
        scope.binds,
    ).scalar_one()
    # Une page au-delà de la dernière ramène sur la dernière, plutôt que sur une liste vide.
    page = min(page, page_count(total, per_page) or 1)
    rows = conn.execute(
        text(f"""
            {cte}
            SELECT a.id, a.raw_text, COUNT(DISTINCT sap.publication_id) AS publication_count,
                   (SELECT jsonb_agg(jsonb_build_object(
                        'id', s.id, 'acronym', s.acronym, 'name', s.name))
                    FROM address_structures ast
                    JOIN structures s ON s.id = ast.structure_id
                    WHERE ast.address_id = a.id
                      AND ast.is_confirmed IS DISTINCT FROM FALSE
                   ) AS structures
            FROM scoped_address_publications sap
            JOIN addresses a ON a.id = sap.address_id
            GROUP BY a.id
            ORDER BY publication_count DESC, a.raw_text
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {**scope.binds, "pg_limit": per_page, "pg_offset": (page - 1) * per_page},
    ).all()
    return ScopedAddressesResponse(
        total=total,
        page=page,
        per_page=per_page,
        addresses=[
            ScopedAddressOut(
                id=r.id,
                raw_text=r.raw_text,
                publication_count=r.publication_count,
                structures=(
                    [
                        ScopedAddressStructure(id=s["id"], acronym=s["acronym"], name=s["name"])
                        for s in r.structures
                    ]
                    if r.structures
                    else None
                ),
            )
            for r in rows
        ],
    )


def scoped_address_summary(conn: Connection, scope: AddressScope) -> ScopedAddressSummary:
    """Compte, par année, les publications avec adresse du périmètre, puis, par structure, celles dont une adresse brute est rattachée à la structure. Les publications sans année sont ignorées."""
    # Un seul parcours du périmètre : `GROUPING SETS` compte les publications par année (`is_total`), puis par année et par structure. La jointure externe garde dans les totaux les publications sans structure reconnue.
    rows = conn.execute(
        text(f"""
            {_cte(scope)}
            SELECT GROUPING(s.id) = 1 AS is_total, s.id, s.acronym, s.name,
                   sap.publication_year, COUNT(DISTINCT sap.publication_id) AS publications
            FROM scoped_address_publications sap
            LEFT JOIN address_structures ast
              ON ast.address_id = sap.address_id AND ast.is_confirmed IS DISTINCT FROM FALSE
            LEFT JOIN structures s ON s.id = ast.structure_id
            WHERE sap.publication_year IS NOT NULL
            GROUP BY GROUPING SETS (
                (sap.publication_year),
                (sap.publication_year, s.id, s.acronym, s.name)
            )
        """),
        scope.binds,
    ).all()
    counts = {r.publication_year: r.publications for r in rows if r.is_total}
    years = list(range(min(counts), max(counts) + 1)) if counts else []
    structures: dict[int, ScopedAddressStructureSeries] = {}
    for r in rows:
        if r.is_total or r.id is None:
            continue
        series = structures.get(r.id)
        if series is None:
            series = structures[r.id] = ScopedAddressStructureSeries(
                id=r.id, acronym=r.acronym, name=r.name, publications=[0] * len(years)
            )
        series.publications[r.publication_year - years[0]] = r.publications
    return ScopedAddressSummary(
        years=[
            ScopedAddressYear(year=y, publications_with_address=counts.get(y, 0)) for y in years
        ],
        structures=sorted(structures.values(), key=lambda s: (-sum(s.publications), s.name)),
    )
