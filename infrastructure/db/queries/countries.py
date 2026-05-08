"""Query service : recalcul des pays des publications.

Trois étapes (write-only) appelées par l'orchestrateur pipeline
`application/pipeline/countries/refresh_publication_countries.py` :

1. HAL  : `source_structures.country` → `source_publications.countries`
2. OA/WoS/ScanR : `addresses.countries` → `source_publications.countries`
3. Union de tous les `source_publications.countries` → `publications.countries`

Fonctions module-level pour compat avec le code existant ;
`PgCountryQueries` est l'adapter qui implémente `application.ports.countries.CountryQueries`.

Note migration SQLA : `suggest_addresses_countries_batch` est consommée
par `interfaces/cli/pipeline/suggest_address_countries.py` migré en SA Core
sync (Connection SA). Les 3 fonctions `refresh_*_countries` restent en
psycopg ``cur`` pour cette session — relèvent du Lot 3.B (queries
pipeline) du chantier sqlalchemy-core-adoption.
"""

from typing import Any

from sqlalchemy import Connection, text


def refresh_hal_source_countries(cur: Any) -> int:
    """Propage `source_structures.country` vers `source_publications.countries` (HAL).

    Pour chaque document HAL, collecte les pays des structures de ses auteurs
    (via `source_authorships.source_struct_ids` → `source_structures.country`).
    Retourne le nombre de lignes mises à jour.
    """
    cur.execute("""
        UPDATE source_publications sd
        SET countries = sub.doc_countries
        FROM (
            SELECT sa.source_publication_id,
                   array_agg(DISTINCT ss.country ORDER BY ss.country) AS doc_countries
            FROM source_authorships sa,
                 LATERAL unnest(sa.source_struct_ids) AS ssid(val)
            JOIN source_structures ss ON ss.id = ssid.val
            WHERE sa.source = 'hal'
              AND ss.country IS NOT NULL
            GROUP BY sa.source_publication_id
        ) sub
        WHERE sd.id = sub.source_publication_id
          AND sd.source = 'hal'
          AND sd.countries IS DISTINCT FROM sub.doc_countries
    """)
    return cur.rowcount


def refresh_address_source_countries(cur: Any) -> int:
    """Propage `addresses.countries` vers `source_publications.countries` (OA/WoS/ScanR).

    Pour chaque document non-HAL, collecte les pays des adresses de ses auteurs
    (via `source_authorship_addresses` → `addresses.countries`).
    Retourne le nombre de lignes mises à jour.
    """
    cur.execute("""
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
    return cur.rowcount


def refresh_publication_countries(cur: Any) -> int:
    """Calcule `publications.countries` comme union des `source_publications.countries`.

    Retourne le nombre de lignes mises à jour.
    """
    cur.execute("""
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
    return cur.rowcount


def suggest_addresses_countries_batch(
    conn: Connection, *, batch_size: int, target_column: str = "suggested_countries"
) -> tuple[int, int]:
    """Suggère un pays pour les adresses sans pays via substring match.

    Pour chaque adresse cible (sans `countries` et sans `suggested_countries`,
    `normalized_text` ≥ 5 chars), cherche les adresses du pool (avec `countries`)
    dont le `normalized_text` la contient comme sous-chaîne. Le ou les pays
    les plus fréquents parmi ces matches deviennent la suggestion.

    Tout est fait en une seule requête SQL bulk (CTE + UPDATE + window function)
    qui exploite l'index trigramme `idx_addresses_normalized_text_trgm`
    (cf migration 020). CTE complexe : reste en SQL brut via ``text()`` (cf.
    règles du chantier sqlalchemy-core-adoption).

    Les cibles sans match reçoivent un array vide (et non NULL) — c'est ce
    marquage qui permet à la passe suivante de les sauter via le filtre
    `WHERE suggested_countries IS NULL`.

    Args:
        batch_size: nombre d'adresses cibles traitées en un coup.
        target_column: `suggested_countries` (défaut) ou `countries` (mode
            `--direct` du CLI : écrase directement la colonne canonique).

    Retourne (n_processed, n_with_suggestion).
    """
    if target_column not in ("suggested_countries", "countries"):
        raise ValueError(f"target_column invalide : {target_column!r}")

    result = conn.execute(
        text(f"""
            WITH targets AS (
                SELECT id, normalized_text
                FROM addresses
                WHERE countries IS NULL
                  AND suggested_countries IS NULL
                  AND length(normalized_text) >= 5
                ORDER BY pub_count DESC, id
                LIMIT :batch_size
            ),
            matches AS (
                SELECT t.id AS target_id, c, count(*) AS cnt
                FROM targets t
                JOIN addresses a2
                    ON a2.normalized_text LIKE '%' || t.normalized_text || '%'
                CROSS JOIN LATERAL unnest(a2.countries) AS c
                WHERE a2.countries IS NOT NULL
                GROUP BY t.id, c
            ),
            ranked AS (
                SELECT target_id, c, cnt,
                       max(cnt) OVER (PARTITION BY target_id) AS max_cnt
                FROM matches
            ),
            top_per_target AS (
                SELECT target_id,
                       array_agg(DISTINCT trim(c) ORDER BY trim(c)) AS suggested
                FROM ranked
                WHERE cnt = max_cnt
                GROUP BY target_id
            )
            UPDATE addresses a
            SET {target_column} = COALESCE(tp.suggested, ARRAY[]::char(2)[])
            FROM targets t
            LEFT JOIN top_per_target tp ON tp.target_id = t.id
            WHERE a.id = t.id
            RETURNING (tp.suggested IS NOT NULL) AS had_match
        """),
        {"batch_size": batch_size},
    )
    rows = result.all()
    n_processed = len(rows)
    n_with_suggestion = sum(1 for r in rows if r.had_match)
    return n_processed, n_with_suggestion


class PgCountryQueries:
    """Adapter PostgreSQL implémentant `application.ports.countries.CountryQueries`."""

    def refresh_hal_source_countries(self, cur: Any) -> int:
        return refresh_hal_source_countries(cur)

    def refresh_address_source_countries(self, cur: Any) -> int:
        return refresh_address_source_countries(cur)

    def refresh_publication_countries(self, cur: Any) -> int:
        return refresh_publication_countries(cur)
