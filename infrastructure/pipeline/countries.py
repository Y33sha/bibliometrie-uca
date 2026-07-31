"""Query service SQL de la phase `countries` : résoudre les pays d'une adresse, puis les propager aux caches dénormalisés.

**Résolution** — pose `addresses.countries` (seule source de vérité) par détection et suggestion. Détection : les formes de `place_name_forms` (`load_country_forms`, `load_place_forms`) confrontées aux adresses sans pays (`fetch_addresses_missing_country_normalized`), écriture via `write_countries`. Suggestion : les adresses déjà résolues forment un pool (`load_country_pool`) rapproché des cibles restantes (`fetch_suggest_targets_chunk`) pour alimenter `addresses.suggested_countries`. `count_address_country_status` et `count_suggest_eligible` en donnent le bilan.

**Propagation** — recalcule deux caches depuis `addresses.countries` :

1. `source_publications.countries` ← union des pays des adresses des `source_authorships` du document.
2. `publications.countries` ← union des `source_publications.countries` de même `publication_id`.

Deux portées partagent l'agrégation (tails `_SP_COUNTRIES_FROM_SCOPE` / `_PUB_COUNTRIES_FROM_SCOPE`) : bornée aux `countries_dirty` (`refresh_address_source_countries` / `refresh_publication_countries`, cf. `_DIRTY_SA` — refresh global du pipeline), ou bornée à des adresses (`refresh_source_publications_countries_for_addresses` / `refresh_publications_countries_for_addresses` — refresh ciblé après une modification manuelle, via `application/services/addresses/countries.py:propagate_countries_to_publications`).

`PgCountryQueries` implémente `application.ports.pipeline.countries.CountryQueries` ; le contrat de chaque opération vit au port.
"""

import json

from sqlalchemy import Connection, text

from application.ports.pipeline.countries import (
    AddressCountryFilter,
    AddressCountryStatus,
    CountryQueries,
    SuggestEligibleCounts,
)
from domain.countries import PlaceNameKind

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

# Ajout idempotent d'un code pays à `addresses.countries` : ni doublon, ni écrasement des codes déjà posés. Le code à ajouter est lié au paramètre `:cc`.
_ADD_COUNTRY_SET_CLAUSE = """
    SET countries = CASE
        WHEN countries IS NULL THEN ARRAY[:cc]::char(2)[]
        WHEN :cc = ANY(countries) THEN countries
        ELSE array_append(countries, CAST(:cc AS char(2)))
    END
"""


class PgCountryQueries(CountryQueries):
    """Adapter PostgreSQL implémentant `application.ports.pipeline.countries.CountryQueries`. Contrat de chaque méthode au port."""

    def count_address_country_status(self, conn: Connection) -> AddressCountryStatus:
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

    def refresh_address_source_countries(self, conn: Connection) -> int:
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

    def refresh_publication_countries(self, conn: Connection) -> int:
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

    def clear_countries_dirty(self, conn: Connection) -> None:
        conn.execute(
            text("UPDATE source_authorships SET countries_dirty = false WHERE countries_dirty")
        )
        conn.execute(text("UPDATE addresses SET countries_dirty = false WHERE countries_dirty"))

    def load_country_forms(self, conn: Connection) -> dict[str, str]:
        rows = conn.execute(
            text(
                f"SELECT form_normalized, iso_code FROM place_name_forms "
                f"WHERE kind = '{PlaceNameKind.COUNTRY.value}'"
            )
        ).all()
        return {r.form_normalized: r.iso_code for r in rows}

    def load_place_forms(self, conn: Connection) -> dict[str, str]:
        rows = conn.execute(
            text(
                f"SELECT form_normalized, iso_code FROM place_name_forms "
                f"WHERE kind IN ('{PlaceNameKind.INSTITUTION.value}', '{PlaceNameKind.CITY.value}')"
            )
        ).all()
        return {r.form_normalized: r.iso_code for r in rows}

    def fetch_addresses_missing_country_normalized(self, conn: Connection) -> list[tuple[int, str]]:
        rows = conn.execute(
            text("SELECT id, normalized_text FROM addresses WHERE countries IS NULL")
        ).all()
        return [(r.id, r.normalized_text) for r in rows]

    def count_suggest_eligible(self, conn: Connection) -> SuggestEligibleCounts:
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
        self, conn: Connection, *, after_id: int, limit: int, retry_empty: bool = False
    ) -> list[tuple[int, str]]:
        # `retry_empty` (mode full) réessaie aussi les échecs (`= []`), sans toucher aux suggestions positives (rares à changer, coûteuses à recalculer).
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

    def load_country_pool(self, conn: Connection) -> list[tuple[str, list[str]]]:
        rows = conn.execute(
            text("SELECT normalized_text, countries FROM addresses WHERE countries IS NOT NULL")
        ).all()
        return [(r.normalized_text, r.countries) for r in rows]

    def write_countries(
        self,
        conn: Connection,
        rows: list[tuple[int, list[str]]],
        *,
        target_column: str = "suggested_countries",
    ) -> None:
        # Bulk via `jsonb_array_elements`, idempotent (`IS DISTINCT FROM`). Écrire `countries` pose aussi `countries_dirty` sur les lignes touchées (déjà réécrites → gratuit) ; `suggested_countries` ne touche pas la cascade.
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

    def batch_add_country_by_ids(
        self, conn: Connection, country_code: str, address_ids: list[int]
    ) -> list[int]:
        if not address_ids:
            return []
        result = conn.execute(
            text(f"""
                UPDATE addresses
                {_ADD_COUNTRY_SET_CLAUSE}
                WHERE id = ANY(:ids)
                RETURNING id
            """),
            {"cc": country_code, "ids": address_ids},
        )
        return [row.id for row in result]

    def batch_add_country_by_filter(
        self, conn: Connection, country_code: str, criteria: AddressCountryFilter
    ) -> list[int]:
        conditions: list[str] = []
        params: dict = {"cc": country_code}
        if criteria.search:
            conditions.append("unaccent(raw_text) ILIKE unaccent(:search)")
            params["search"] = f"%{criteria.search}%"
        if criteria.has_country is True:
            conditions.append("countries IS NOT NULL")
        elif criteria.has_country is False:
            conditions.append("countries IS NULL")
        if criteria.country_code:
            conditions.append(":country_code = ANY(countries)")
            params["country_code"] = criteria.country_code
        if criteria.suggested_country:
            conditions.append(":suggested_country = ANY(suggested_countries)")
            params["suggested_country"] = criteria.suggested_country

        if not conditions:
            return []

        where_clause = " AND ".join(conditions)
        result = conn.execute(
            text(f"""
                UPDATE addresses
                {_ADD_COUNTRY_SET_CLAUSE}
                WHERE {where_clause}
                RETURNING id
            """),
            params,
        )
        return [row.id for row in result]

    def propagate_countries_across_similar_addresses(
        self, conn: Connection, source_ids: list[int]
    ) -> list[int]:
        if not source_ids:
            return []
        result = conn.execute(
            text("""
                UPDATE addresses a2
                SET countries = a1.countries
                FROM addresses a1
                WHERE a1.id = ANY(:source_ids)
                  AND a1.countries IS NOT NULL
                  AND a2.normalized_text = a1.normalized_text
                  AND a2.countries IS DISTINCT FROM a1.countries
                  AND a2.id <> a1.id
                RETURNING a2.id
            """),
            {"source_ids": source_ids},
        )
        return [row.id for row in result]

    def refresh_source_publications_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
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

    def refresh_publications_countries_for_addresses(
        self, conn: Connection, address_ids: list[int]
    ) -> int:
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
