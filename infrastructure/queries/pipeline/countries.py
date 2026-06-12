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


def mark_source_authorships_dirty_for_addresses(conn: Connection, address_ids: list[int]) -> int:
    """Marque `countries_dirty` les source_authorships liés à des adresses dont
    `countries` vient de changer (appelé par detect / institution après écriture).

    Le refresh ne recalculera que ces sa (+ les nouveaux, dirty dès leur création
    par normalize). Retourne le nombre de sa nouvellement marqués.
    """
    if not address_ids:
        return 0
    return conn.execute(
        text("""
            UPDATE source_authorships sa
            SET countries_dirty = true
            WHERE NOT sa.countries_dirty
              AND sa.id IN (
                  SELECT saa.source_authorship_id
                  FROM source_authorship_addresses saa
                  WHERE saa.address_id = ANY(:ids)
              )
        """),
        {"ids": address_ids},
    ).rowcount


def refresh_sa_countries(conn: Connection) -> int:
    """Recalcule `source_authorships.countries` pour tous les sa `countries_dirty`.

    `countries` = union des pays des adresses du sa, ou NULL si aucune adresse
    utile — le LEFT JOIN couvre l'orphelin (un sa qui perd ses pays repasse à
    NULL), ce qui rend l'ancienne passe de cleanup inutile. Bornée aux sa dirty
    via l'index partiel → peu de lignes en run nominal, donc une seule requête
    suffit (l'ancien split par source n'évitait le spill que sur le recompute
    complet, désormais inexistant). Idempotent (`IS DISTINCT FROM`) ; le flag est
    purgé en fin de cascade.

    Retourne le nombre de sa mis à jour.
    """
    return conn.execute(
        text("""
            WITH dirty_sa AS (
                SELECT id FROM source_authorships WHERE countries_dirty
            ),
            expanded AS (
                SELECT saa.source_authorship_id AS sa_id, c::text AS country_code
                FROM source_authorship_addresses saa
                JOIN dirty_sa d ON d.id = saa.source_authorship_id
                JOIN addresses a ON a.id = saa.address_id
                CROSS JOIN LATERAL unnest(a.countries) AS c
                WHERE a.countries IS NOT NULL
            ),
            agg AS (
                SELECT sa_id, array_agg(DISTINCT country_code ORDER BY country_code) AS new_countries
                FROM expanded
                GROUP BY sa_id
            )
            UPDATE source_authorships sa
            SET countries = agg.new_countries
            FROM dirty_sa d
            LEFT JOIN agg ON agg.sa_id = d.id
            WHERE sa.id = d.id
              AND sa.countries IS DISTINCT FROM agg.new_countries
        """)
    ).rowcount


def refresh_address_source_countries(conn: Connection) -> int:
    """Recalcule `source_publications.countries` des sp ayant un sa `countries_dirty`.

    `countries` = union des pays des adresses des sa du document (calcul direct
    depuis les adresses), ou NULL si aucune (LEFT JOIN orphelin). Idempotent.
    Retourne le nombre de sp mis à jour.
    """
    return conn.execute(
        text("""
            WITH dirty_sp AS (
                SELECT DISTINCT source_publication_id AS sp_id
                FROM source_authorships
                WHERE countries_dirty AND source_publication_id IS NOT NULL
            ),
            expanded AS (
                SELECT sa.source_publication_id AS sp_id, c::text AS country_code
                FROM source_authorships sa
                JOIN dirty_sp d ON d.sp_id = sa.source_publication_id
                JOIN source_authorship_addresses saa ON saa.source_authorship_id = sa.id
                JOIN addresses a ON a.id = saa.address_id
                CROSS JOIN LATERAL unnest(a.countries) AS c
                WHERE a.countries IS NOT NULL
            ),
            agg AS (
                SELECT sp_id, array_agg(DISTINCT country_code ORDER BY country_code) AS new_countries
                FROM expanded
                GROUP BY sp_id
            )
            UPDATE source_publications sp
            SET countries = agg.new_countries
            FROM dirty_sp d
            LEFT JOIN agg ON agg.sp_id = d.sp_id
            WHERE sp.id = d.sp_id
              AND sp.countries IS DISTINCT FROM agg.new_countries
        """)
    ).rowcount


def refresh_publication_countries(conn: Connection) -> int:
    """Recalcule `publications.countries` des publications dont un sp a un sa `countries_dirty`.

    `countries` = union des `source_publications.countries` de la publication, ou
    NULL si aucune (LEFT JOIN orphelin). Idempotent. Retourne le nombre de
    publications mises à jour.
    """
    return conn.execute(
        text("""
            WITH dirty_pub AS (
                SELECT DISTINCT sp.publication_id AS pub_id
                FROM source_publications sp
                JOIN source_authorships sa ON sa.source_publication_id = sp.id
                WHERE sa.countries_dirty AND sp.publication_id IS NOT NULL
            ),
            expanded AS (
                SELECT sp.publication_id AS pub_id, c::text AS country_code
                FROM source_publications sp
                JOIN dirty_pub d ON d.pub_id = sp.publication_id
                CROSS JOIN LATERAL unnest(sp.countries) AS c
                WHERE sp.countries IS NOT NULL
            ),
            agg AS (
                SELECT pub_id, array_agg(DISTINCT country_code ORDER BY country_code) AS all_countries
                FROM expanded
                GROUP BY pub_id
            )
            UPDATE publications p
            SET countries = agg.all_countries
            FROM dirty_pub d
            LEFT JOIN agg ON agg.pub_id = d.pub_id
            WHERE p.id = d.pub_id
              AND p.countries IS DISTINCT FROM agg.all_countries
        """)
    ).rowcount


def clear_source_authorships_dirty(conn: Connection) -> int:
    """Remet `countries_dirty` à false sur tous les sa traités (fin de cascade)."""
    return conn.execute(
        text("UPDATE source_authorships SET countries_dirty = false WHERE countries_dirty")
    ).rowcount


class AddressCountryStatus(NamedTuple):
    """Bilan de l'état pays des adresses (restreint à `pub_count > 0`)."""

    total: int
    with_country: int
    with_suggestion: int
    none: int


def count_address_country_status(conn: Connection) -> AddressCountryStatus:
    """Bilan global de la résolution des pays sur les adresses utiles (`pub_count > 0`).

    Logué au début et à la fin de la phase countries, pas après chaque passe.
    """
    row = conn.execute(
        text("""
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE countries IS NOT NULL) AS with_country,
                count(*) FILTER (
                    WHERE countries IS NULL AND cardinality(suggested_countries) > 0
                ) AS with_suggestion,
                count(*) FILTER (
                    WHERE countries IS NULL
                      AND (suggested_countries IS NULL OR cardinality(suggested_countries) = 0)
                ) AS none
            FROM addresses
            WHERE pub_count > 0
        """)
    ).one()
    return AddressCountryStatus(row.total, row.with_country, row.with_suggestion, row.none)


class SuggestEligibleCounts(NamedTuple):
    """Compteurs des adresses sans pays, pour le log de la passe suggest."""

    eligible: int  # pas encore tentées (suggested_countries IS NULL) — toujours traitées
    has_suggestion: int
    empty_attempted: int  # tentées sans match (`= []`) — retraitées en mode retry_empty
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


def fetch_suggest_targets_chunk(
    conn: Connection, *, after_id: int, limit: int, retry_empty: bool = False
) -> list[tuple[int, str]]:
    """Tranche `(id, normalized_text)` des adresses sans pays à suggérer (keyset par id).

    `retry_empty=True` (mode full) : nouvelles **+ vides** (`suggested_countries IS
    NULL OR cardinality = 0`) — on réessaie les échecs au cas où le pool aurait
    grossi, sans toucher aux suggestions positives (qui changent rarement et
    coûtent cher à recalculer). Sinon (incrémental) : seulement les nouvelles
    (`suggested_countries IS NULL`). Liste vide = terminé.
    """
    suggested_filter = (
        "AND (suggested_countries IS NULL OR cardinality(suggested_countries) = 0)"
        if retry_empty
        else "AND suggested_countries IS NULL"
    )
    rows = conn.execute(
        text(f"""
            SELECT id, normalized_text
            FROM addresses
            WHERE countries IS NULL
              {suggested_filter}
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
    Idempotent : seules les lignes dont la valeur change sont écrites
    (`IS DISTINCT FROM`), pas de churn d'index sur un recalcul à l'identique.
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
              AND a.{target_column} IS DISTINCT FROM d.cty
        """),
        {"payload": payload},
    )


class PgCountryQueries(CountryQueries):
    """Adapter PostgreSQL implémentant `application.ports.countries.CountryQueries`."""

    def refresh_sa_countries(self, conn: Connection) -> int:
        return refresh_sa_countries(conn)

    def refresh_address_source_countries(self, conn: Connection) -> int:
        return refresh_address_source_countries(conn)

    def refresh_publication_countries(self, conn: Connection) -> int:
        return refresh_publication_countries(conn)

    def clear_source_authorships_dirty(self, conn: Connection) -> int:
        return clear_source_authorships_dirty(conn)
