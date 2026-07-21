"""Query service SQL de la phase `countries` : résoudre les pays d'une adresse, puis les propager aux caches dénormalisés.

**Résolution** — pose `addresses.countries` (seule source de vérité) par détection et suggestion. Détection : les formes de `place_name_forms` (`load_country_forms`, `load_place_forms`) confrontées aux adresses sans pays (`fetch_addresses_missing_country_normalized`), écriture via `write_countries`. Suggestion : les adresses déjà résolues forment un pool (`load_country_pool`) rapproché des cibles restantes (`fetch_suggest_targets_chunk`) pour alimenter `addresses.suggested_countries`. `count_address_country_status` et `count_suggest_eligible` en donnent le bilan.

**Propagation** — recalcule deux caches depuis `addresses.countries` :

1. `source_publications.countries` ← union des pays des adresses des `source_authorships` du document.
2. `publications.countries` ← union des `source_publications.countries` de même `publication_id`.

Deux portées partagent l'agrégation (tails `_SP_COUNTRIES_FROM_SCOPE` / `_PUB_COUNTRIES_FROM_SCOPE`) : bornée aux `countries_dirty` (`refresh_address_source_countries` / `refresh_publication_countries`, cf. `_DIRTY_SA` — refresh global du pipeline), ou bornée à des adresses (`refresh_source_publications_countries_for_addresses` / `refresh_publications_countries_for_addresses` — refresh ciblé après une modification manuelle, via `application/services/addresses/countries.py:propagate_countries_to_publications`).

Fonctions module-level ; `PgCountryQueries` est l'adapter qui implémente `application.ports.pipeline.countries.CountryQueries`.
"""

import json

from sqlalchemy import Connection, text

from application.ports.pipeline.countries import (
    AddressCountryStatus,
    CountryQueries,
    SuggestEligibleCounts,
)

# CTE des signatures à recalculer : celles marquées `countries_dirty` (posé par normalize), ou liées à une adresse dont `countries` a changé. Dérivées par JOIN, sans marquage de masse ; seules celles qui changent sont réécrites.
_DIRTY_SA = """
    WITH dirty_sa AS (
        SELECT id FROM source_authorships WHERE countries_dirty
        UNION
        SELECT saa.source_authorship_id
        FROM source_authorship_addresses saa
        JOIN addresses a ON a.id = saa.address_id
        WHERE a.countries_dirty
    )
"""

# Tail partagé du recalcul `source_publications.countries` : attend une CTE
# amont `scoped_sp(sp_id)` (les documents à recalculer). Recalcule la valeur
# pleine — union des pays de toutes les adresses des signatures du document —
# et n'écrit que les lignes qui changent (LEFT JOIN → NULL si aucune adresse).
_SP_COUNTRIES_FROM_SCOPE = """,
    agg AS (
        SELECT sa.source_publication_id AS sp_id,
               array_agg(DISTINCT c::text ORDER BY c::text) AS new_countries
        FROM source_authorships sa
        JOIN scoped_sp ss ON ss.sp_id = sa.source_publication_id
        JOIN source_authorship_addresses saa ON saa.source_authorship_id = sa.id
        JOIN addresses a ON a.id = saa.address_id
        CROSS JOIN LATERAL unnest(a.countries) AS c
        WHERE a.countries IS NOT NULL
        GROUP BY sa.source_publication_id
    )
    UPDATE source_publications sp
    SET countries = agg.new_countries
    FROM scoped_sp ss
    LEFT JOIN agg ON agg.sp_id = ss.sp_id
    WHERE sp.id = ss.sp_id
      AND sp.countries IS DISTINCT FROM agg.new_countries
"""

# Tail partagé du recalcul `publications.countries` : attend une CTE amont
# `scoped_pub(pub_id)`. Union des `source_publications.countries` de la
# publication ; n'écrit que les lignes qui changent (LEFT JOIN → NULL si aucune).
_PUB_COUNTRIES_FROM_SCOPE = """,
    agg AS (
        SELECT sp.publication_id AS pub_id,
               array_agg(DISTINCT c::text ORDER BY c::text) AS new_countries
        FROM source_publications sp
        JOIN scoped_pub spp ON spp.pub_id = sp.publication_id
        CROSS JOIN LATERAL unnest(sp.countries) AS c
        WHERE sp.countries IS NOT NULL
        GROUP BY sp.publication_id
    )
    UPDATE publications p
    SET countries = agg.new_countries
    FROM scoped_pub spp
    LEFT JOIN agg ON agg.pub_id = spp.pub_id
    WHERE p.id = spp.pub_id
      AND p.countries IS DISTINCT FROM agg.new_countries
"""


def refresh_address_source_countries(conn: Connection) -> int:
    """Recalcule `source_publications.countries` des documents ayant une signature à recalculer (`countries_dirty`, ou liée à une adresse dont les pays ont changé). Idempotent. Retourne le nombre de documents mis à jour."""
    return conn.execute(
        text(
            _DIRTY_SA
            + """,
            scoped_sp AS (
                SELECT DISTINCT sa.source_publication_id AS sp_id
                FROM source_authorships sa
                JOIN dirty_sa d ON d.id = sa.id
                WHERE sa.source_publication_id IS NOT NULL
            )
            """
            + _SP_COUNTRIES_FROM_SCOPE
        )
    ).rowcount


def refresh_publication_countries(conn: Connection) -> int:
    """Recalcule `publications.countries` des publications dont une signature est à recalculer (`countries_dirty`, ou liée à une adresse dont les pays ont changé). Idempotent. Retourne le nombre de publications mises à jour."""
    return conn.execute(
        text(
            _DIRTY_SA
            + """,
            scoped_pub AS (
                SELECT DISTINCT sp.publication_id AS pub_id
                FROM source_publications sp
                JOIN source_authorships sa ON sa.source_publication_id = sp.id
                JOIN dirty_sa d ON d.id = sa.id
                WHERE sp.publication_id IS NOT NULL
            )
            """
            + _PUB_COUNTRIES_FROM_SCOPE
        )
    ).rowcount


def clear_countries_dirty(conn: Connection) -> None:
    """Purge les deux flags `countries_dirty` (sa + adresses) en fin de cascade."""
    conn.execute(
        text("UPDATE source_authorships SET countries_dirty = false WHERE countries_dirty")
    )
    conn.execute(text("UPDATE addresses SET countries_dirty = false WHERE countries_dirty"))


def refresh_source_publications_countries_for_addresses(
    conn: Connection, address_ids: list[int]
) -> int:
    """Recalcule `source_publications.countries` des documents rattachés à l'une des `address_ids` — refresh ciblé après une modification manuelle de pays. Idempotent. Retourne le nombre de documents mis à jour."""
    if not address_ids:
        return 0
    return conn.execute(
        text(
            """
            WITH scoped_sp AS (
                SELECT DISTINCT sa.source_publication_id AS sp_id
                FROM source_authorship_addresses saa
                JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                WHERE saa.address_id = ANY(:ids)
                  AND sa.source_publication_id IS NOT NULL
            )
            """
            + _SP_COUNTRIES_FROM_SCOPE
        ),
        {"ids": address_ids},
    ).rowcount


def refresh_publications_countries_for_addresses(conn: Connection, address_ids: list[int]) -> int:
    """Recalcule `publications.countries` des publications rattachées à l'une des `address_ids` — refresh ciblé après une modification manuelle de pays. Idempotent. Retourne le nombre de publications mises à jour."""
    if not address_ids:
        return 0
    return conn.execute(
        text(
            """
            WITH scoped_pub AS (
                SELECT DISTINCT sd.publication_id AS pub_id
                FROM source_authorship_addresses saa
                JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                WHERE saa.address_id = ANY(:ids) AND sd.publication_id IS NOT NULL
            )
            """
            + _PUB_COUNTRIES_FROM_SCOPE
        ),
        {"ids": address_ids},
    ).rowcount


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


def count_suggest_eligible(conn: Connection) -> SuggestEligibleCounts:
    """Compteurs des adresses sans pays (éligibles, déjà suggérées, tentées sans match)."""
    row = conn.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE suggested_countries IS NULL) AS eligible,
                COUNT(*) FILTER (WHERE cardinality(suggested_countries) > 0) AS has_suggestion,
                COUNT(*) FILTER (
                    WHERE suggested_countries IS NOT NULL AND cardinality(suggested_countries) = 0
                ) AS empty_attempted
            FROM addresses
            WHERE countries IS NULL
        """)
    ).one()
    return SuggestEligibleCounts(row.eligible, row.has_suggestion, row.empty_attempted)


def fetch_suggest_targets_chunk(
    conn: Connection, *, after_id: int, limit: int, retry_empty: bool = False
) -> list[tuple[int, str]]:
    """Tranche `(id, normalized_text)` des adresses sans pays à suggérer (keyset par id).

    `retry_empty=True` (mode full) : nouvelles **+ vides** (`suggested_countries IS NULL OR cardinality = 0`) — on réessaie les échecs au cas où le pool aurait grossi, sans toucher aux suggestions positives (qui changent rarement et coûtent cher à recalculer). Sinon (incrémental) : seulement les nouvelles (`suggested_countries IS NULL`). Liste vide = terminé.
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


def write_countries(
    conn: Connection,
    rows: list[tuple[int, list[str]]],
    *,
    target_column: str = "suggested_countries",
) -> None:
    """Écrit en bloc une colonne pays d'`addresses` (`countries` ou `suggested_countries`).

    `target_column` : `suggested_countries` (suggestions, `[]` = tentée sans match) ou `countries` (pays détectés/confirmés). Bulk via `jsonb_array_elements`, idempotent (`IS DISTINCT FROM` → seules les lignes qui changent sont écrites).

    Quand on écrit `countries`, pose aussi `countries_dirty = true` sur ces mêmes lignes (déjà réécrites → gratuit) : le refresh dérivera de là les signatures à recalculer, sans marquage de masse. `suggested_countries` ne touche pas la cascade, sans flag.
    """
    if target_column not in ("suggested_countries", "countries"):
        raise ValueError(f"target_column invalide : {target_column!r}")
    if not rows:
        return
    dirty_set = ", countries_dirty = true" if target_column == "countries" else ""
    payload = json.dumps([{"id": addr_id, "c": countries} for addr_id, countries in rows])
    conn.execute(
        text(f"""
            UPDATE addresses a
            SET {target_column} = d.cty{dirty_set}
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


def load_country_forms(conn: Connection) -> dict[str, str]:
    """Noms de pays (`place_name_forms`, `kind = 'country'`) : `{form_normalized: iso_code}`."""
    rows = conn.execute(
        text("SELECT form_normalized, iso_code FROM place_name_forms WHERE kind = 'country'")
    ).all()
    return {r.form_normalized: r.iso_code for r in rows}


def load_place_forms(conn: Connection) -> dict[str, str]:
    """Noms de lieux (`place_name_forms`, `kind IN ('institution', 'city')`) : `{form_normalized: iso_code}`."""
    rows = conn.execute(
        text(
            "SELECT form_normalized, iso_code FROM place_name_forms "
            "WHERE kind IN ('institution', 'city')"
        )
    ).all()
    return {r.form_normalized: r.iso_code for r in rows}


def fetch_addresses_missing_country_normalized(conn: Connection) -> list[tuple[int, str]]:
    """`(id, normalized_text)` des adresses sans pays, pour la détection par nom de lieu."""
    rows = conn.execute(
        text("SELECT id, normalized_text FROM addresses WHERE countries IS NULL")
    ).all()
    return [(r.id, r.normalized_text) for r in rows]


class PgCountryQueries(CountryQueries):
    """Adapter PostgreSQL implémentant `application.ports.pipeline.countries.CountryQueries`."""

    def count_address_country_status(self, conn: Connection) -> AddressCountryStatus:
        return count_address_country_status(conn)

    def refresh_address_source_countries(self, conn: Connection) -> int:
        return refresh_address_source_countries(conn)

    def refresh_publication_countries(self, conn: Connection) -> int:
        return refresh_publication_countries(conn)

    def clear_countries_dirty(self, conn: Connection) -> None:
        clear_countries_dirty(conn)

    def load_country_forms(self, conn: Connection) -> dict[str, str]:
        return load_country_forms(conn)

    def load_place_forms(self, conn: Connection) -> dict[str, str]:
        return load_place_forms(conn)

    def fetch_addresses_missing_country_normalized(self, conn: Connection) -> list[tuple[int, str]]:
        return fetch_addresses_missing_country_normalized(conn)

    def count_suggest_eligible(self, conn: Connection) -> SuggestEligibleCounts:
        return count_suggest_eligible(conn)

    def fetch_suggest_targets_chunk(
        self, conn: Connection, *, after_id: int, limit: int, retry_empty: bool = False
    ) -> list[tuple[int, str]]:
        return fetch_suggest_targets_chunk(
            conn, after_id=after_id, limit=limit, retry_empty=retry_empty
        )

    def load_country_pool(self, conn: Connection) -> list[tuple[str, list[str]]]:
        return load_country_pool(conn)

    def write_countries(
        self,
        conn: Connection,
        rows: list[tuple[int, list[str]]],
        *,
        target_column: str = "suggested_countries",
    ) -> None:
        write_countries(conn, rows, target_column=target_column)
