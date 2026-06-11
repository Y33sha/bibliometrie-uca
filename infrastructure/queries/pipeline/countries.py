"""Query service : recalcul des pays sur les caches dénormalisés.

Trois caches en cascade, alimentés à partir des `addresses.countries`
(seule source de vérité) :

1. `source_authorships.countries` ← agrégat des `addresses.countries`
   liées via `source_authorship_addresses`
2. `source_publications.countries` ← union des `sa.countries` du doc
3. `publications.countries` ← union des `sp.countries` du même
   publication_id

Appelées par l'orchestrateur pipeline
`application/pipeline/countries/refresh_publication_countries.py` pour
le refresh global, et par `application/addresses_countries.py:propagate_countries_to_publications`
(via le repo) pour le refresh ciblé après une modification manuelle.

Fonctions module-level pour compat avec le code existant ;
`PgCountryQueries` est l'adapter qui implémente
`application.ports.countries.CountryQueries`.
"""

import json
from typing import NamedTuple

from sqlalchemy import Connection, text

from application.ports.pipeline.countries import CountryQueries


def refresh_sa_countries_for_source(conn: Connection, source: str) -> int:
    """Recalcule `source_authorships.countries` pour les sa d'une source donnée.

    Pass 1 du refresh global, batchée par source pour éviter le spill
    sur disque (work_mem ~64MB ne suffit pas pour le GROUP BY + DISTINCT
    sur 7M rows en une fois). Chaque source = max ~3M rows (WoS),
    tient en mémoire.

    CTE `expanded` qui dédoublonne `(sa_id, country)` via hash, puis
    GROUP BY pour agréger en array. UPDATE join filtré par
    `sa.source = :source` pour borner le volume.

    Retourne le nombre de sa mises à jour. Idempotent (`IS DISTINCT FROM`).
    """
    return conn.execute(
        text("""
            WITH expanded AS (
                SELECT DISTINCT saa.source_authorship_id AS sa_id, c::text AS country_code
                FROM source_authorship_addresses saa
                JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                JOIN addresses a ON a.id = saa.address_id
                CROSS JOIN LATERAL unnest(a.countries) AS c
                WHERE a.countries IS NOT NULL
                  AND sa.source = :source
            ),
            sa_new AS (
                SELECT sa_id, array_agg(country_code ORDER BY country_code) AS new_countries
                FROM expanded
                GROUP BY sa_id
            )
            UPDATE source_authorships sa
            SET countries = sn.new_countries
            FROM sa_new sn
            WHERE sa.id = sn.sa_id
              AND sa.countries IS DISTINCT FROM sn.new_countries
        """),
        {"source": source},
    ).rowcount


def cleanup_sa_countries_orphans(conn: Connection) -> int:
    """Pass 2 : met à NULL les sa polluées (`countries` non-NULL mais
    aucune adresse utile).

    Borne le scan aux sa avec `countries IS NOT NULL`, sous-ensemble
    étroit — rapide même sans batching.

    Retourne le nombre de sa nettoyées. Idempotent.
    """
    return conn.execute(
        text("""
            UPDATE source_authorships sa
            SET countries = NULL
            WHERE sa.countries IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM source_authorship_addresses saa
                  JOIN addresses a ON a.id = saa.address_id
                  WHERE saa.source_authorship_id = sa.id
                    AND a.countries IS NOT NULL
              )
        """)
    ).rowcount


def refresh_address_source_countries(conn: Connection) -> int:
    """Propage `addresses.countries` vers `source_publications.countries` (OA/WoS/ScanR).

    Pour chaque document non-HAL, collecte les pays des adresses de ses auteurs
    (via `source_authorship_addresses` → `addresses.countries`).
    Retourne le nombre de lignes mises à jour.
    """
    return conn.execute(
        text("""
            UPDATE source_publications sd
            SET countries = sub.doc_countries
            FROM (
                SELECT sa.source_publication_id,
                       array_agg(DISTINCT c::text ORDER BY c::text) AS doc_countries
                FROM source_authorships sa
                JOIN source_authorship_addresses saa ON saa.source_authorship_id = sa.id
                JOIN addresses a ON a.id = saa.address_id,
                LATERAL unnest(a.countries) AS c
                WHERE a.countries IS NOT NULL
                GROUP BY sa.source_publication_id
            ) sub
            WHERE sd.id = sub.source_publication_id
              AND sd.countries IS DISTINCT FROM sub.doc_countries
        """)
    ).rowcount


def refresh_publication_countries(conn: Connection) -> int:
    """Calcule `publications.countries` comme union des `source_publications.countries`.

    Retourne le nombre de lignes mises à jour.
    """
    return conn.execute(
        text("""
            UPDATE publications p
            SET countries = sub.all_countries
            FROM (
                SELECT sd.publication_id AS pub_id,
                       array_agg(DISTINCT c ORDER BY c) AS all_countries
                FROM source_publications sd,
                LATERAL unnest(sd.countries) AS c
                WHERE sd.countries IS NOT NULL
                  AND sd.publication_id IS NOT NULL
                GROUP BY sd.publication_id
            ) sub
            WHERE p.id = sub.pub_id
              AND p.countries IS DISTINCT FROM sub.all_countries
        """)
    ).rowcount


class SuggestEligibleCounts(NamedTuple):
    """Compteurs des adresses sans pays, pour le log de la passe suggest."""

    eligible: int
    has_suggestion: int
    empty_attempted: int
    too_short: int


def count_suggest_eligible(conn: Connection) -> SuggestEligibleCounts:
    """Compteurs des adresses sans pays (éligibles, déjà suggérées, tentées sans match, trop courtes)."""
    row = conn.execute(
        text("""
            SELECT
                COUNT(*) FILTER (
                    WHERE suggested_countries IS NULL AND length(normalized_text) >= 5
                ) AS eligible,
                COUNT(*) FILTER (WHERE cardinality(suggested_countries) > 0) AS has_suggestion,
                COUNT(*) FILTER (
                    WHERE suggested_countries IS NOT NULL AND cardinality(suggested_countries) = 0
                ) AS empty_attempted,
                COUNT(*) FILTER (WHERE length(normalized_text) < 5) AS too_short
            FROM addresses
            WHERE countries IS NULL
        """)
    ).one()
    return SuggestEligibleCounts(
        row.eligible, row.has_suggestion, row.empty_attempted, row.too_short
    )


def reset_suggested_countries(conn: Connection, *, only_empty: bool) -> int:
    """Remet `suggested_countries` à NULL et retourne le rowcount.

    `only_empty=True` (mode full du pipeline) ne réinitialise que les suggestions
    vides (`= []`, adresses déjà tentées sans match) pour rejouer une évolution
    des heuristiques sans perdre les suggestions positives existantes.
    """
    sql = (
        "UPDATE addresses SET suggested_countries = NULL "
        "WHERE countries IS NULL AND suggested_countries IS NOT NULL"
    )
    if only_empty:
        sql += " AND cardinality(suggested_countries) = 0"
    return conn.execute(text(sql)).rowcount


def fetch_suggest_targets_chunk(
    conn: Connection, *, after_id: int, limit: int
) -> list[tuple[int, str]]:
    """Tranche `(id, normalized_text)` des adresses sans pays à suggérer (keyset par id).

    Éligibles : `countries IS NULL`, pas encore tentées (`suggested_countries IS
    NULL`), `normalized_text` ≥ 5 caractères. Liste vide = terminé.
    """
    rows = conn.execute(
        text("""
            SELECT id, normalized_text
            FROM addresses
            WHERE countries IS NULL
              AND suggested_countries IS NULL
              AND length(normalized_text) >= 5
              AND id > :after
            ORDER BY id
            LIMIT :limit
        """),
        {"after": after_id, "limit": limit},
    ).all()
    return [(r.id, r.normalized_text) for r in rows]


def load_country_pool(conn: Connection) -> list[tuple[str, list[str]]]:
    """Charge le pool : `(normalized_text, countries)` des adresses *avec* pays.

    Tenu en mémoire et rescanné à chaque batch de cibles par `CountrySuggester`.
    """
    rows = conn.execute(
        text("SELECT normalized_text, countries FROM addresses WHERE countries IS NOT NULL")
    ).all()
    return [(r.normalized_text, r.countries) for r in rows]


def write_suggested_countries(
    conn: Connection,
    rows: list[tuple[int, list[str]]],
    *,
    target_column: str = "suggested_countries",
) -> None:
    """Écrit en bloc la suggestion de chaque cible (`[]` = tentée sans match).

    `target_column` : `suggested_countries` (défaut) ou `countries` (mode
    `--direct` : écrase la colonne canonique). Bulk via `jsonb_array_elements`.
    """
    if target_column not in ("suggested_countries", "countries"):
        raise ValueError(f"target_column invalide : {target_column!r}")
    if not rows:
        return
    payload = json.dumps([{"id": addr_id, "c": countries} for addr_id, countries in rows])
    conn.execute(
        text(f"""
            UPDATE addresses a
            SET {target_column} = d.cty
            FROM (
                SELECT (e->>'id')::int AS id,
                       ARRAY(SELECT jsonb_array_elements_text(e->'c'))::char(2)[] AS cty
                FROM jsonb_array_elements(CAST(:payload AS jsonb)) e
            ) d
            WHERE a.id = d.id
        """),
        {"payload": payload},
    )


class PgCountryQueries(CountryQueries):
    """Adapter PostgreSQL implémentant `application.ports.countries.CountryQueries`."""

    def refresh_sa_countries_for_source(self, conn: Connection, source: str) -> int:
        return refresh_sa_countries_for_source(conn, source)

    def cleanup_sa_countries_orphans(self, conn: Connection) -> int:
        return cleanup_sa_countries_orphans(conn)

    def refresh_address_source_countries(self, conn: Connection) -> int:
        return refresh_address_source_countries(conn)

    def refresh_publication_countries(self, conn: Connection) -> int:
        return refresh_publication_countries(conn)
