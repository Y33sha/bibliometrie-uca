"""Recalcul des pays des contributions sources et des enregistrements sources à partir de `addresses.countries`.

Deux caches dénormalisés, en cascade :
  1. `source_contributions.countries` — pays retenus des adresses de la contribution source, à défaut pays de ses organisations ROR sans adresse ; pays de ses structures HAL.
  2. `source_records.countries` — union des `source_contributions.countries` de l'enregistrement source.

La consolidation des publications calcule `publications.countries`. Deux portées partagent l'agrégation :

- les contributions sources à recalculer (`refresh`, tâche `affiliations.refresh_source_record_countries`). Les publications des enregistrements sources modifiés entrent dans la file `publications_queue`.
- les contributions sources d'un lot d'adresses (`CountryRecompute`, appelé par l'API après une saisie manuelle). Les publications sont recalculées aussitôt.

Une contribution source est à recalculer quand elle est dans la file `source_contribution_countries_queue`, ou liée à une adresse de la file `address_countries_queue`. `create_dirty_scope` relève les deux files, puis ces contributions sources, dans des tables temporaires lues par les trois étapes :

- `countries_dirty_scope` : toutes ces contributions sources, avec leur enregistrement source ;
- `countries_recompute_scope` : parmi elles, celles dont les pays peuvent changer, numérotées pour le traitement par tranches. Une contribution source sans pays, sans adresse, sans ROR sans adresse et sans structure HAL est absente de cette table : ses pays restent vides.
"""

import logging
import time
from typing import NamedTuple

from sqlalchemy import Connection, text

from infrastructure.db.queues import Queue, delete_processed, enqueue_sql, snapshot
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, quantity
from pipeline.runtime.observability.progress import track_progress, waiting
from pipeline.transformation.countries.resolution import resolve_address_countries
from pipeline.transformation.publications import lifecycle

BATCH_SIZE = 50_000
"""Nombre de contributions sources recalculées par requête."""

_SNAPSHOTS = (
    (Queue.SOURCE_CONTRIBUTION_COUNTRIES, "source_contribution_countries_marks"),
    (Queue.ADDRESS_COUNTRIES, "address_countries_marks"),
)
"""Files et tables de leur relevé. `delete_processed_marks` supprime des files les marquages relevés."""

_CREATE_DIRTY_SCOPE = """
    CREATE TEMP TABLE countries_dirty_scope AS
    SELECT sc.id, sc.source_record_id, sc.countries IS NOT NULL AS has_countries
    FROM source_contribution_countries_marks m
    JOIN source_contributions sc ON sc.id = m.id
    UNION
    SELECT sc.id, sc.source_record_id, sc.countries IS NOT NULL
    FROM address_countries_marks m
    JOIN source_contribution_addresses sca ON sca.address_id = m.id
    JOIN source_contributions sc ON sc.id = sca.source_contribution_id
"""

_CREATE_RECOMPUTE_SCOPE = """
    CREATE TEMP TABLE countries_recompute_scope AS
    SELECT row_number() OVER (ORDER BY d.id) AS rank, d.id
    FROM countries_dirty_scope d
    WHERE d.has_countries
       OR EXISTS (SELECT 1 FROM source_contribution_addresses x
                  WHERE x.source_contribution_id = d.id)
       OR EXISTS (SELECT 1 FROM source_contribution_rors x
                  WHERE x.source_contribution_id = d.id AND x.address_id IS NULL)
       OR EXISTS (SELECT 1 FROM source_contribution_hal_structures x
                  WHERE x.source_contribution_id = d.id)
"""

_SOURCE_CONTRIBUTION_COUNTRIES_FROM_SCOPE = """,
    contributions AS (
        SELECT sca.source_contribution_id AS source_contribution_id, c::text AS code
        FROM scoped_sa s
        JOIN source_contribution_addresses sca ON sca.source_contribution_id = s.id
        JOIN addresses a ON a.id = sca.address_id
        CROSS JOIN LATERAL unnest(a.countries) AS c
        UNION
        SELECT scr.source_contribution_id, ro.country_code::text
        FROM scoped_sa s
        JOIN source_contribution_rors scr ON scr.source_contribution_id = s.id
        JOIN ror_organizations ro ON ro.ror_id = scr.ror_id
        WHERE scr.address_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM source_contribution_addresses sca
              JOIN addresses a ON a.id = sca.address_id
              WHERE sca.source_contribution_id = s.id AND cardinality(a.countries) > 0
          )
        UNION
        SELECT h.source_contribution_id, hs.country_code::text
        FROM scoped_sa s
        JOIN source_contribution_hal_structures h ON h.source_contribution_id = s.id
        LEFT JOIN hal_structure_aliases al ON al.alias_id = h.hal_structure_id
        JOIN hal_structures hs ON hs.hal_structure_id = coalesce(al.hal_structure_id, h.hal_structure_id)
        WHERE hs.country_code IS NOT NULL
    ),
    agg AS (
        SELECT source_contribution_id, array_agg(code ORDER BY code) AS new_countries
        FROM contributions
        GROUP BY source_contribution_id
    )
    UPDATE source_contributions sc
    SET countries = agg.new_countries
    FROM scoped_sa s
    LEFT JOIN agg ON agg.source_contribution_id = s.id
    WHERE sc.id = s.id
      AND sc.countries IS DISTINCT FROM agg.new_countries
"""
"""Recalcul de `source_contributions.countries` sur la CTE amont `scoped_sa(id)`."""

_SOURCE_RECORD_COUNTRIES_AGG = """,
    agg AS (
        SELECT sc.source_record_id AS source_record_id,
               array_agg(DISTINCT c ORDER BY c) AS new_countries
        FROM source_contributions sc
        JOIN scoped_sp ss ON ss.source_record_id = sc.source_record_id
        CROSS JOIN LATERAL unnest(sc.countries) AS c
        GROUP BY sc.source_record_id
    )"""
"""Union des pays des contributions sources de chaque enregistrement source de la CTE amont `scoped_sp(source_record_id)`."""

_SOURCE_RECORD_COUNTRIES_UPDATE = """
    UPDATE source_records sr
    SET countries = agg.new_countries
    FROM scoped_sp ss
    LEFT JOIN agg ON agg.source_record_id = ss.source_record_id
    WHERE sr.id = ss.source_record_id
      AND sr.countries IS DISTINCT FROM agg.new_countries
"""
"""Écriture de `source_records.countries` d'après la CTE `agg`. Seules les lignes qui changent sont écrites."""


def create_dirty_scope(conn: Connection) -> int:
    """Relève les deux files, puis crée `countries_dirty_scope` et `countries_recompute_scope`. Renvoie le nombre de contributions sources à recalculer."""
    for queue, table in _SNAPSHOTS:
        snapshot(conn, queue, table)
    conn.execute(text(_CREATE_DIRTY_SCOPE))
    conn.execute(text(_CREATE_RECOMPUTE_SCOPE))
    conn.execute(text("ALTER TABLE countries_recompute_scope ADD PRIMARY KEY (rank)"))
    conn.execute(text("ANALYZE countries_dirty_scope"))
    conn.execute(text("ANALYZE countries_recompute_scope"))
    return int(conn.execute(text("SELECT count(*) FROM countries_recompute_scope")).scalar_one())


def delete_processed_marks(conn: Connection) -> None:
    """Supprime des deux files les marquages relevés par `create_dirty_scope`."""
    for queue, table in _SNAPSHOTS:
        delete_processed(conn, queue, table)


def drop_dirty_scope(conn: Connection) -> None:
    """Supprime les tables temporaires de `create_dirty_scope`."""
    tables = ", ".join(table for _, table in _SNAPSHOTS)
    conn.execute(text(f"DROP TABLE countries_dirty_scope, countries_recompute_scope, {tables}"))


def refresh_source_contribution_countries(
    conn: Connection, *, ranks: tuple[int, int] | None = None
) -> int:
    """Recalcule `source_contributions.countries` des contributions sources de `countries_recompute_scope`. Renvoie le nombre de contributions sources modifiées.

    Args:
        ranks: tranche de la numérotation à recalculer, bornes incluses.
    """
    if ranks is None:
        scope = "WITH scoped_sa AS (SELECT id FROM countries_recompute_scope)"
        params = {}
    else:
        scope = """
            WITH scoped_sa AS (
                SELECT id FROM countries_recompute_scope WHERE rank BETWEEN :lo AND :hi
            )"""
        params = {"lo": ranks[0], "hi": ranks[1]}
    return conn.execute(text(scope + _SOURCE_CONTRIBUTION_COUNTRIES_FROM_SCOPE), params).rowcount


class SourceRecordCountriesRefresh(NamedTuple):
    """Bilan du recalcul des pays des enregistrements sources."""

    source_records: int
    """Enregistrements sources aux pays modifiés."""
    publications: int
    """Publications de ces enregistrements sources, mises en file de consolidation."""


def refresh_source_record_countries(conn: Connection) -> SourceRecordCountriesRefresh:
    """Recalcule `source_records.countries` des enregistrements sources de `countries_dirty_scope`, et met en file de consolidation les publications des enregistrements sources modifiés."""
    row = conn.execute(
        text(
            f"""
            WITH scoped_sp AS (
                SELECT DISTINCT source_record_id FROM countries_dirty_scope
                WHERE source_record_id IS NOT NULL
            ){_SOURCE_RECORD_COUNTRIES_AGG},
            updated AS ({_SOURCE_RECORD_COUNTRIES_UPDATE} RETURNING sr.publication_id),
            marked AS ({enqueue_sql(Queue.PUBLICATIONS, "SELECT publication_id FROM updated WHERE publication_id IS NOT NULL")})
            SELECT count(*) AS source_records, count(DISTINCT publication_id) AS publications
            FROM updated
            """  # noqa: S608
        )
    ).one()
    return SourceRecordCountriesRefresh(row.source_records, row.publications)


def _refresh_source_contributions_in_batches(
    conn: Connection, total: int, logger: logging.Logger
) -> int:
    """Recalcule les `total` contributions sources de `countries_recompute_scope` par tranches de `BATCH_SIZE`, avec une barre de progression. Renvoie le nombre de contributions sources modifiées."""
    updated = 0
    with track_progress(total, f"{BRANCH}contributions sources", logger, erase=True) as progress:
        for lo in range(1, total + 1, BATCH_SIZE):
            hi = min(lo + BATCH_SIZE - 1, total)
            updated += refresh_source_contribution_countries(conn, ranks=(lo, hi))
            progress.advance(hi - lo + 1)
    return updated


def refresh(conn: Connection, logger: logging.Logger) -> int:
    """Recalcule les pays des contributions sources à recalculer, puis de leurs enregistrements sources, met en file de consolidation les publications des enregistrements sources modifiés, et supprime les marquages traités. Renvoie le nombre de publications mises en file. Chaque recalcul a sa ligne de journal, avec son nombre de lignes et sa durée."""
    with waiting(f"{BRANCH}contributions sources à recalculer : en cours", logger) as line:
        total = create_dirty_scope(conn)
        line.conclude(
            f"{BRANCH}{quantity(total, 'contribution source à recalculer', 'contributions sources à recalculer')}"
        )
    t0 = time.perf_counter()
    updated = _refresh_source_contributions_in_batches(conn, total, logger)
    logger.info(
        "%s%s en %.1f s",
        BRANCH,
        quantity(updated, "contribution source mise à jour", "contributions sources mises à jour"),
        time.perf_counter() - t0,
    )
    t0 = time.perf_counter()
    with waiting(f"{LAST_BRANCH}enregistrements sources : en cours", logger) as line:
        counts = refresh_source_record_countries(conn)
        records = quantity(
            counts.source_records,
            "enregistrement source mis à jour",
            "enregistrements sources mis à jour",
        )
        publications = quantity(
            counts.publications, "publication à recalculer", "publications à recalculer"
        )
        line.conclude(f"{LAST_BRANCH}{records} en {time.perf_counter() - t0:.1f} s, {publications}")
    delete_processed_marks(conn)
    drop_dirty_scope(conn)
    return counts.publications


class CountryRecompute:
    """Résolution des pays d'un lot d'adresses et recalcul ciblé de leurs caches (port injecté par l'API)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def resolve_address_countries(self, address_ids: list[int]) -> int:
        return resolve_address_countries(self._conn, address_ids)

    def refresh_source_records_countries_for_addresses(self, address_ids: list[int]) -> int:
        """Recalcule `source_contributions.countries` des contributions sources liées à l'une des `address_ids`, puis `source_records.countries` de leurs enregistrements sources. Idempotent. Renvoie le nombre d'enregistrements sources mis à jour."""
        if not address_ids:
            return 0
        self._conn.execute(
            text(
                """
                WITH scoped_sa AS (
                    SELECT DISTINCT source_contribution_id AS id
                    FROM source_contribution_addresses
                    WHERE address_id = ANY(:ids)
                )"""
                + _SOURCE_CONTRIBUTION_COUNTRIES_FROM_SCOPE
            ),
            {"ids": address_ids},
        )
        return self._conn.execute(
            text(
                """
                WITH scoped_sp AS (
                    SELECT DISTINCT sc.source_record_id AS source_record_id
                    FROM source_contribution_addresses sca
                    JOIN source_contributions sc ON sc.id = sca.source_contribution_id
                    WHERE sca.address_id = ANY(:ids)
                      AND sc.source_record_id IS NOT NULL
                )
                """
                + _SOURCE_RECORD_COUNTRIES_AGG
                + _SOURCE_RECORD_COUNTRIES_UPDATE
            ),
            {"ids": address_ids},
        ).rowcount

    def refresh_publications_for_addresses(self, address_ids: list[int]) -> int:
        """Recalcule les métadonnées consolidées des publications rattachées à l'une des `address_ids`. Renvoie le nombre de publications recalculées."""
        if not address_ids:
            return 0
        publication_ids = list(
            self._conn.execute(
                text("""
                    SELECT DISTINCT sr.publication_id
                    FROM source_contribution_addresses sca
                    JOIN source_contributions sc ON sc.id = sca.source_contribution_id
                    JOIN source_records sr ON sr.id = sc.source_record_id
                    WHERE sca.address_id = ANY(:ids) AND sr.publication_id IS NOT NULL
                    ORDER BY sr.publication_id
                """),
                {"ids": address_ids},
            ).scalars()
        )
        lifecycle.refresh(self._conn, publication_ids)
        return len(publication_ids)
