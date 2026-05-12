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

from sqlalchemy import Connection, text


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

    Cas du backfill historique via `source_structures` (circuit
    supprimé depuis). Borne le scan aux sa avec `countries IS NOT NULL`,
    sous-ensemble étroit — rapide même sans batching.

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
    (cf migration 020). CTE complexe : reste en SQL brut via ``text()``.

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

    def refresh_sa_countries_for_source(self, conn: Connection, source: str) -> int:
        return refresh_sa_countries_for_source(conn, source)

    def cleanup_sa_countries_orphans(self, conn: Connection) -> int:
        return cleanup_sa_countries_orphans(conn)

    def refresh_address_source_countries(self, conn: Connection) -> int:
        return refresh_address_source_countries(conn)

    def refresh_publication_countries(self, conn: Connection) -> int:
        return refresh_publication_countries(conn)
