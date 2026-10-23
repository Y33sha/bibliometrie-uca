"""Recalcule les pays des contributions sources, des enregistrements sources et des publications à partir de `addresses.countries`.

Trois caches dénormalisés, en cascade :
  1. `source_contributions.countries` — pays retenus des adresses de la contribution source, pays de ses organisations ROR sans adresse et de ses structures HAL.
  2. `source_records.countries` — union des `source_contributions.countries` du document.
  3. `publications.countries` — union des `source_records.countries` de même publication_id.

Deux portées partagent l'agrégation : les contributions sources à recalculer (`refresh`, tâche `countries.refresh_publication_countries`), ou les contributions sources d'un lot d'adresses (`CountryRecompute`, appelé par l'API après une saisie manuelle).

Une contribution source est à recalculer quand elle est dans la file `source_contribution_countries_queue`, ou liée à une adresse de la file `address_countries_queue`. `create_dirty_scope` relève les deux files, puis ces contributions sources, dans des tables temporaires que lisent les trois étapes :

- `countries_dirty_scope` : toutes ces contributions sources, avec leur enregistrement source ;
- `countries_recompute_scope` : parmi elles, celles dont les pays peuvent changer, numérotées pour le traitement par tranches. Une contribution source sans adresse, sans ROR sans adresse, sans structure HAL et sans pays garde des pays vides : elle en est absente.
"""

import logging
import time

from sqlalchemy import Connection, text

from infrastructure.db.queues import Queue, delete_processed, snapshot
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, quantity, step
from pipeline.runtime.observability.progress import track_progress, waiting
from pipeline.transformation.countries.resolution import resolve_address_countries

BATCH_SIZE = 50_000
"""Nombre de contributions sources recalculées par requête."""

# Relevés des deux files, que `delete_processed_marks` supprime des files.
_SNAPSHOTS = (
    (Queue.SOURCE_CONTRIBUTION_COUNTRIES, "source_contribution_countries_marks"),
    (Queue.ADDRESS_COUNTRIES, "address_countries_marks"),
)

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

# Recalcul de `source_contributions.countries` sur la CTE amont `scoped_sa(id)`.
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

# Recalcul de `source_records.countries` sur la CTE amont `scoped_sp(source_record_id)` : union des pays des contributions sources.
_SOURCE_RECORD_COUNTRIES_FROM_SCOPE = """,
    agg AS (
        SELECT sc.source_record_id AS source_record_id,
               array_agg(DISTINCT c ORDER BY c) AS new_countries
        FROM source_contributions sc
        JOIN scoped_sp ss ON ss.source_record_id = sc.source_record_id
        CROSS JOIN LATERAL unnest(sc.countries) AS c
        GROUP BY sc.source_record_id
    )
    UPDATE source_records sr
    SET countries = agg.new_countries
    FROM scoped_sp ss
    LEFT JOIN agg ON agg.source_record_id = ss.source_record_id
    WHERE sr.id = ss.source_record_id
      AND sr.countries IS DISTINCT FROM agg.new_countries
"""

# Recalcul de `publications.countries` sur la CTE amont `scoped_publications(publication_id)` : union des `source_records.countries` de la publication ; seules les lignes qui changent sont écrites.
_PUBLICATION_COUNTRIES_FROM_SCOPE = """,
    agg AS (
        SELECT sr.publication_id AS publication_id,
               array_agg(DISTINCT c::text ORDER BY c::text) AS new_countries
        FROM source_records sr
        JOIN scoped_publications scp ON scp.publication_id = sr.publication_id
        CROSS JOIN LATERAL unnest(sr.countries) AS c
        WHERE sr.countries IS NOT NULL
        GROUP BY sr.publication_id
    )
    UPDATE publications p
    SET countries = agg.new_countries
    FROM scoped_publications scp
    LEFT JOIN agg ON agg.publication_id = scp.publication_id
    WHERE p.id = scp.publication_id
      AND p.countries IS DISTINCT FROM agg.new_countries
"""


def create_dirty_scope(conn: Connection) -> int:
    """Relève les deux files, puis crée `countries_dirty_scope` et `countries_recompute_scope`. Retourne le nombre de contributions sources à recalculer."""
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
    """Recalcule `source_contributions.countries` des contributions sources de `countries_recompute_scope`. Retourne le nombre de contributions sources modifiées.

    `ranks` (bornes incluses) limite le recalcul à une tranche de la numérotation.
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


def refresh_source_record_countries(conn: Connection) -> int:
    """Recalcule `source_records.countries` des documents de `countries_dirty_scope`. Retourne le nombre de lignes modifiées."""
    return conn.execute(
        text(
            """
            WITH scoped_sp AS (
                SELECT DISTINCT source_record_id FROM countries_dirty_scope
                WHERE source_record_id IS NOT NULL
            )
            """
            + _SOURCE_RECORD_COUNTRIES_FROM_SCOPE
        )
    ).rowcount


def refresh_publication_countries(conn: Connection) -> int:
    """Recalcule `publications.countries` des publications des documents de `countries_dirty_scope`. Retourne le nombre de lignes modifiées."""
    return conn.execute(
        text(
            """
            WITH scoped_publications AS (
                SELECT DISTINCT sr.publication_id AS publication_id
                FROM (SELECT DISTINCT source_record_id FROM countries_dirty_scope) d
                JOIN source_records sr ON sr.id = d.source_record_id
                WHERE sr.publication_id IS NOT NULL
            )
            """
            + _PUBLICATION_COUNTRIES_FROM_SCOPE
        )
    ).rowcount


def _refresh_source_contributions_in_batches(
    conn: Connection, total: int, logger: logging.Logger
) -> int:
    """Recalcule les `total` contributions sources de `countries_recompute_scope` par tranches de `BATCH_SIZE`, avec une barre de progression. Retourne le nombre de contributions sources modifiées."""
    updated = 0
    with track_progress(total, f"{BRANCH}contributions sources", logger, erase=True) as progress:
        for lo in range(1, total + 1, BATCH_SIZE):
            hi = min(lo + BATCH_SIZE - 1, total)
            updated += refresh_source_contribution_countries(conn, ranks=(lo, hi))
            progress.advance(hi - lo + 1)
    return updated


def refresh(conn: Connection, logger: logging.Logger) -> int:
    """Recalcule les caches pays (source_contributions → source_records → publications) des contributions sources à recalculer, puis supprime les marquages traités. Retourne le nombre de publications mises à jour. Chaque étape a sa ligne de journal, avec son nombre de lignes et sa durée."""
    step(logger, "Rafraîchissement des pays associés aux publications")
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
    for singular, plural, refresh_step in (
        ("enregistrement source", "enregistrements sources", refresh_source_record_countries),
        ("publication", "publications", refresh_publication_countries),
    ):
        t0 = time.perf_counter()
        with waiting(f"{BRANCH}{plural} : en cours", logger) as line:
            updated = refresh_step(conn)
            line.conclude(
                f"{BRANCH}{quantity(updated, f'{singular} mise à jour', f'{plural} mises à jour')}"
                f" en {time.perf_counter() - t0:.1f} s"
            )
    t0 = time.perf_counter()
    with waiting(f"{LAST_BRANCH}suppression des marquages traités : en cours", logger) as line:
        delete_processed_marks(conn)
        line.conclude(
            f"{LAST_BRANCH}marquages traités supprimés en {time.perf_counter() - t0:.1f} s"
        )
    drop_dirty_scope(conn)
    return updated


class CountryRecompute:
    """Résolution des pays d'un lot d'adresses et recalcul ciblé de leurs caches (port injecté par l'API)."""

    def resolve_address_countries(self, conn: Connection, address_ids: list[int]) -> int:
        return resolve_address_countries(conn, address_ids)

    def refresh_source_records_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
        """Recalcule `source_contributions.countries` des contributions sources liées à l'une des `address_ids`, puis `source_records.countries` de leurs documents. Idempotent. Retourne le nombre de documents mis à jour."""
        if not address_ids:
            return 0
        conn.execute(
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
        return conn.execute(
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
                + _SOURCE_RECORD_COUNTRIES_FROM_SCOPE
            ),
            {"ids": address_ids},
        ).rowcount

    def refresh_publications_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
        """Recalcule `publications.countries` (union des `source_records.countries`) pour les publications rattachées à l'une des `address_ids`. Idempotent. Retourne le nombre de publications mises à jour."""
        if not address_ids:
            return 0
        return conn.execute(
            text(
                """
                WITH scoped_publications AS (
                    SELECT DISTINCT sr.publication_id AS publication_id
                    FROM source_contribution_addresses sca
                    JOIN source_contributions sc ON sc.id = sca.source_contribution_id
                    JOIN source_records sr ON sr.id = sc.source_record_id
                    WHERE sca.address_id = ANY(:ids) AND sr.publication_id IS NOT NULL
                )
                """
                + _PUBLICATION_COUNTRIES_FROM_SCOPE
            ),
            {"ids": address_ids},
        ).rowcount
