"""Recalcule les pays des contributions sources, des notices et des publications à partir de `addresses.countries`.

Trois caches dénormalisés, en cascade :
  1. `source_contributions.countries` — pays retenus des adresses de la contribution source, pays de ses organisations ROR sans adresse et de ses structures HAL.
  2. `source_records.countries` — union des `source_contributions.countries` du document.
  3. `publications.countries` — union des `source_records.countries` de même publication_id.

Deux portées partagent l'agrégation : les lignes `countries_dirty` (`refresh`, tâche `countries.refresh_publication_countries`), ou les contributions sources d'un lot d'adresses (`CountryRecompute`, appelé par l'API après une saisie manuelle).
"""

import logging
import time

from sqlalchemy import Connection, text

from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.countries.resolution import resolve_address_countries

# CTE des contributions sources à recalculer : marquées `countries_dirty`, ou liées à une adresse marquée `countries_dirty`.
_DIRTY_SOURCE_CONTRIBUTION = """
    WITH dirty_source_contribution AS (
        SELECT id FROM source_contributions WHERE countries_dirty
        UNION
        SELECT saa.source_contribution_id
        FROM source_contribution_addresses saa
        JOIN addresses a ON a.id = saa.address_id
        WHERE a.countries_dirty
    )
"""

# Recalcul de `source_contributions.countries` sur la CTE amont `scoped_sa(id)` ; marque `countries_dirty` les contributions sources modifiées.
_SOURCE_CONTRIBUTION_COUNTRIES_FROM_SCOPE = """,
    contributions AS (
        SELECT saa.source_contribution_id AS source_contribution_id, c::text AS code
        FROM scoped_sa s
        JOIN source_contribution_addresses saa ON saa.source_contribution_id = s.id
        JOIN addresses a ON a.id = saa.address_id
        CROSS JOIN LATERAL unnest(a.countries) AS c
        UNION
        SELECT sar.source_contribution_id, ro.country_code::text
        FROM scoped_sa s
        JOIN source_contribution_rors sar ON sar.source_contribution_id = s.id
        JOIN ror_organizations ro ON ro.ror_id = sar.ror_id
        WHERE sar.address_id IS NULL
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
    UPDATE source_contributions sa
    SET countries = agg.new_countries, countries_dirty = true
    FROM scoped_sa s
    LEFT JOIN agg ON agg.source_contribution_id = s.id
    WHERE sa.id = s.id
      AND sa.countries IS DISTINCT FROM agg.new_countries
"""

# Recalcul de `source_records.countries` sur la CTE amont `scoped_sp(source_record_id)` : union des pays des contributions sources.
_SOURCE_RECORD_COUNTRIES_FROM_SCOPE = """,
    agg AS (
        SELECT sa.source_record_id AS source_record_id,
               array_agg(DISTINCT c ORDER BY c) AS new_countries
        FROM source_contributions sa
        JOIN scoped_sp ss ON ss.source_record_id = sa.source_record_id
        CROSS JOIN LATERAL unnest(sa.countries) AS c
        GROUP BY sa.source_record_id
    )
    UPDATE source_records sp
    SET countries = agg.new_countries
    FROM scoped_sp ss
    LEFT JOIN agg ON agg.source_record_id = ss.source_record_id
    WHERE sp.id = ss.source_record_id
      AND sp.countries IS DISTINCT FROM agg.new_countries
"""

# Recalcul de `publications.countries` sur la CTE amont `scoped_pub(publication_id)` : union des `source_records.countries` de la publication ; seules les lignes qui changent sont écrites.
_PUBLICATION_COUNTRIES_FROM_SCOPE = """,
    agg AS (
        SELECT sp.publication_id AS publication_id,
               array_agg(DISTINCT c::text ORDER BY c::text) AS new_countries
        FROM source_records sp
        JOIN scoped_pub spp ON spp.publication_id = sp.publication_id
        CROSS JOIN LATERAL unnest(sp.countries) AS c
        WHERE sp.countries IS NOT NULL
        GROUP BY sp.publication_id
    )
    UPDATE publications p
    SET countries = agg.new_countries
    FROM scoped_pub spp
    LEFT JOIN agg ON agg.publication_id = spp.publication_id
    WHERE p.id = spp.publication_id
      AND p.countries IS DISTINCT FROM agg.new_countries
"""


def refresh_source_contribution_countries(
    conn: Connection, *, id_range: tuple[int, int] | None = None
) -> int:
    """Recalcule `source_contributions.countries` des contributions sources de `_DIRTY_SOURCE_CONTRIBUTION`. Retourne le nombre de contributions sources modifiées.

    `id_range` (bornes incluses) recalcule toutes les contributions sources de l'intervalle qui ont une adresse, un ROR sans adresse ou une structure HAL.
    """
    if id_range is None:
        scope = (
            _DIRTY_SOURCE_CONTRIBUTION + ", scoped_sa AS (SELECT id FROM dirty_source_contribution)"
        )
        params = {}
    else:
        scope = """
            WITH scoped_sa AS (
                SELECT source_contribution_id AS id FROM source_contribution_addresses
                WHERE source_contribution_id BETWEEN :lo AND :hi
                UNION
                SELECT source_contribution_id FROM source_contribution_rors
                WHERE source_contribution_id BETWEEN :lo AND :hi AND address_id IS NULL
                UNION
                SELECT source_contribution_id FROM source_contribution_hal_structures
                WHERE source_contribution_id BETWEEN :lo AND :hi
            )"""
        params = {"lo": id_range[0], "hi": id_range[1]}
    return conn.execute(text(scope + _SOURCE_CONTRIBUTION_COUNTRIES_FROM_SCOPE), params).rowcount


def refresh_source_record_countries(conn: Connection) -> int:
    """Recalcule `source_records.countries` des documents de `_DIRTY_SOURCE_CONTRIBUTION`. Retourne le nombre de lignes modifiées."""
    return conn.execute(
        text(
            _DIRTY_SOURCE_CONTRIBUTION
            + """,
            scoped_sp AS (
                SELECT DISTINCT sa.source_record_id AS source_record_id
                FROM source_contributions sa
                JOIN dirty_source_contribution d ON d.id = sa.id
                WHERE sa.source_record_id IS NOT NULL
            )
            """
            + _SOURCE_RECORD_COUNTRIES_FROM_SCOPE
        )
    ).rowcount


def refresh_publication_countries(conn: Connection) -> int:
    """Recalcule `publications.countries` des publications de `_DIRTY_SOURCE_CONTRIBUTION`. Retourne le nombre de lignes modifiées."""
    return conn.execute(
        text(
            _DIRTY_SOURCE_CONTRIBUTION
            + """,
            scoped_pub AS (
                SELECT DISTINCT sp.publication_id AS publication_id
                FROM source_records sp
                JOIN source_contributions sa ON sa.source_record_id = sp.id
                JOIN dirty_source_contribution d ON d.id = sa.id
                WHERE sp.publication_id IS NOT NULL
            )
            """
            + _PUBLICATION_COUNTRIES_FROM_SCOPE
        )
    ).rowcount


def clear_countries_dirty(conn: Connection) -> None:
    """Purge les flags `countries_dirty` (`source_contributions` et `addresses`) en fin de cascade."""
    conn.execute(
        text("UPDATE source_contributions SET countries_dirty = false WHERE countries_dirty")
    )
    conn.execute(text("UPDATE addresses SET countries_dirty = false WHERE countries_dirty"))


def refresh(conn: Connection, logger: logging.Logger) -> int:
    """Recalcule les caches pays (source_contributions → source_records → publications), scopé aux `countries_dirty`, puis purge les flags. Retourne le nombre de publications mises à jour. Chaque étape a sa ligne de journal, avec son nombre de lignes et sa durée."""
    etape(logger, "Rafraîchissement des pays associés aux publications")
    steps = (
        ("signature", "signatures", refresh_source_contribution_countries),
        ("notice", "notices", refresh_source_record_countries),
        ("publication", "publications", refresh_publication_countries),
    )
    updated = 0
    for singular, plural, step in steps:
        t0 = time.perf_counter()
        with attente(f"{BRANCHE}{plural} : en cours", logger) as ligne:
            updated = step(conn)
            ligne.conclut(
                f"{BRANCHE}{accord(updated, f'{singular} mise à jour', f'{plural} mises à jour')}"
                f" en {time.perf_counter() - t0:.1f} s"
            )
    t0 = time.perf_counter()
    with attente(
        f"{DERNIERE_BRANCHE}effacement des marqueurs de recalcul : en cours", logger
    ) as ligne:
        clear_countries_dirty(conn)
        ligne.conclut(
            f"{DERNIERE_BRANCHE}marqueurs de recalcul effacés en {time.perf_counter() - t0:.1f} s"
        )
    return updated


class CountryRecompute:
    """Résolution des pays d'un lot d'adresses et recalcul ciblé de leurs caches (port injecté par l'API)."""

    def resolve_address_countries(
        self, conn: Connection, address_ids: list[int] | None = None
    ) -> int:
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
                    SELECT DISTINCT sa.source_record_id AS source_record_id
                    FROM source_contribution_addresses saa
                    JOIN source_contributions sa ON sa.id = saa.source_contribution_id
                    WHERE saa.address_id = ANY(:ids)
                      AND sa.source_record_id IS NOT NULL
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
                WITH scoped_pub AS (
                    SELECT DISTINCT sd.publication_id AS publication_id
                    FROM source_contribution_addresses saa
                    JOIN source_contributions sa ON sa.id = saa.source_contribution_id
                    JOIN source_records sd ON sd.id = sa.source_record_id
                    WHERE saa.address_id = ANY(:ids) AND sd.publication_id IS NOT NULL
                )
                """
                + _PUBLICATION_COUNTRIES_FROM_SCOPE
            ),
            {"ids": address_ids},
        ).rowcount
