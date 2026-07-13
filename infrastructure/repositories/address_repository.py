"""Adapter PostgreSQL sync pour `addresses` et ses propagations.

Note : ce repo expose des méthodes de propagation cross-aggregate
(`refresh_publications_countries_for_addresses`, etc.) qui touchent
`publications.countries` et `source_publications.countries`. Pattern
accepté en exception, documenté dans `docs/architecture.md`.
"""

from sqlalchemy import Connection, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.repositories.address_repository import AddressCountryFilter
from infrastructure.db.tables import address_structures, addresses
from infrastructure.queries.pipeline import countries as country_queries


class PgAddressRepository:
    """Accès PostgreSQL sync à l'agrégat Address."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Validation des liens adresse ↔ structure ───────────────────

    def reset_manual_link(self, address_id: int, structure_id: int) -> None:
        self._conn.execute(
            delete(address_structures)
            .where(address_structures.c.address_id == address_id)
            .where(address_structures.c.structure_id == structure_id)
            .where(address_structures.c.matched_form_id.is_(None))
        )
        self._conn.execute(
            update(address_structures)
            .where(address_structures.c.address_id == address_id)
            .where(address_structures.c.structure_id == structure_id)
            .values(is_confirmed=None)
        )

    def upsert_structure_link(
        self,
        address_id: int,
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        stmt = pg_insert(address_structures).values(
            address_id=address_id,
            structure_id=structure_id,
            is_confirmed=is_confirmed,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["address_id", "structure_id"],
            set_={"is_confirmed": stmt.excluded.is_confirmed},
        )
        self._conn.execute(stmt)

    def batch_reset_manual_links(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> int:
        self._conn.execute(
            delete(address_structures)
            .where(address_structures.c.address_id.in_(address_ids))
            .where(address_structures.c.structure_id == structure_id)
            .where(address_structures.c.matched_form_id.is_(None))
        )
        result = self._conn.execute(
            update(address_structures)
            .where(address_structures.c.address_id.in_(address_ids))
            .where(address_structures.c.structure_id == structure_id)
            .values(is_confirmed=None)
        )
        return result.rowcount

    def batch_upsert_structure_links(
        self,
        address_ids: list[int],
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        if not address_ids:
            return
        stmt = pg_insert(address_structures)
        stmt = stmt.on_conflict_do_update(
            index_elements=["address_id", "structure_id"],
            set_={"is_confirmed": stmt.excluded.is_confirmed},
        )
        # SA exécute en mode "executemany" si on passe une liste de dicts.
        self._conn.execute(
            stmt,
            [
                {"address_id": aid, "structure_id": structure_id, "is_confirmed": is_confirmed}
                for aid in address_ids
            ],
        )

    def which_contribute_to_perimeter(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> set[int]:
        """Cf. docstring du port.

        Condition miroir de la clause WHERE de
        `recompute_in_perimeter_on_source_authorships` — à garder synchronisée.
        """
        if not address_ids:
            return set()
        result = self._conn.execute(
            select(address_structures.c.address_id)
            .where(address_structures.c.address_id.in_(address_ids))
            .where(address_structures.c.structure_id == structure_id)
            .where(address_structures.c.is_confirmed.is_distinct_from(False))
        )
        return {row.address_id for row in result}

    # ── Pays ───────────────────────────────────────────────────────

    def set_countries(
        self,
        address_id: int,
        countries: list[str] | None,
    ) -> None:
        self._conn.execute(
            update(addresses)
            .where(addresses.c.id == address_id)
            .values(countries=countries if countries else None)
        )

    def batch_add_country_by_ids(
        self,
        country_code: str,
        address_ids: list[int],
    ) -> list[int]:
        if not address_ids:
            return []
        result = self._conn.execute(
            text("""
                UPDATE addresses
                SET countries = CASE
                    WHEN countries IS NULL THEN ARRAY[:cc]::char(2)[]
                    WHEN :cc = ANY(countries) THEN countries
                    ELSE array_append(countries, CAST(:cc AS char(2)))
                END
                WHERE id = ANY(:ids)
                RETURNING id
            """),
            {"cc": country_code, "ids": address_ids},
        )
        return [row.id for row in result]

    def batch_add_country_by_filter(
        self,
        country_code: str,
        criteria: AddressCountryFilter,
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
        result = self._conn.execute(
            text(f"""
                UPDATE addresses
                SET countries = CASE
                    WHEN countries IS NULL THEN ARRAY[:cc]::char(2)[]
                    WHEN :cc = ANY(countries) THEN countries
                    ELSE array_append(countries, CAST(:cc AS char(2)))
                END
                WHERE {where_clause}
                RETURNING id
            """),
            params,
        )
        return [row.id for row in result]

    def propagate_countries_across_similar_addresses(
        self,
        source_ids: list[int],
    ) -> list[int]:
        if not source_ids:
            return []
        result = self._conn.execute(
            text("""
                UPDATE addresses a2
                SET countries = a1.countries
                FROM addresses a1
                WHERE a1.id = ANY(:source_ids)
                  AND a1.countries IS NOT NULL
                  AND a2.normalized_text = a1.normalized_text
                  AND a2.countries IS DISTINCT FROM a1.countries
                  AND LENGTH(a2.normalized_text) >= 5
                  AND a2.id <> a1.id
                RETURNING a2.id
            """),
            {"source_ids": source_ids},
        )
        return [row.id for row in result]

    # ── Propagation vers source_publications et publications ──

    def refresh_source_publications_countries(
        self,
        address_ids: list[int],
    ) -> int:
        return country_queries.refresh_source_publications_countries_for_addresses(
            self._conn, address_ids
        )

    def refresh_publications_countries_for_addresses(
        self,
        address_ids: list[int],
    ) -> int:
        return country_queries.refresh_publications_countries_for_addresses(self._conn, address_ids)
