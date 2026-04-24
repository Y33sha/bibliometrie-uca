"""Adapter PostgreSQL async pour `addresses` et ses propagations (§2.12).

Parallèle à infrastructure/repositories/address_repository.py.
"""

from typing import Any


class PgAsyncAddressRepository:
    """Accès PostgreSQL async à l'agrégat Address."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    # ── Validation des liens adresse ↔ structure ───────────────────

    async def reset_manual_link(self, address_id: int, structure_id: int) -> None:
        await self._cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = %s AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_id, structure_id),
        )
        await self._cur.execute(
            """
            UPDATE address_structures SET is_confirmed = NULL
            WHERE address_id = %s AND structure_id = %s
            """,
            (address_id, structure_id),
        )

    async def upsert_structure_link(
        self,
        address_id: int,
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        await self._cur.execute(
            """
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES (%s, %s, %s)
            ON CONFLICT (address_id, structure_id) DO UPDATE
                SET is_confirmed = EXCLUDED.is_confirmed
            """,
            (address_id, structure_id, is_confirmed),
        )

    async def batch_reset_manual_links(
        self,
        address_ids: list[int],
        structure_id: int,
    ) -> int:
        await self._cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = ANY(%s) AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_ids, structure_id),
        )
        await self._cur.execute(
            """
            UPDATE address_structures SET is_confirmed = NULL
            WHERE address_id = ANY(%s) AND structure_id = %s
            """,
            (address_ids, structure_id),
        )
        return self._cur.rowcount

    async def batch_upsert_structure_links(
        self,
        address_ids: list[int],
        structure_id: int,
        is_confirmed: bool,
    ) -> None:
        await self._cur.executemany(
            """
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES (%s, %s, %s)
            ON CONFLICT (address_id, structure_id) DO UPDATE
                SET is_confirmed = EXCLUDED.is_confirmed
            """,
            [(aid, structure_id, is_confirmed) for aid in address_ids],
        )

    async def delete_manual_structure_link(
        self,
        address_id: int,
        structure_id: int,
    ) -> bool:
        await self._cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = %s AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_id, structure_id),
        )
        return self._cur.rowcount > 0

    async def which_contribute_to_perimeter(
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
        await self._cur.execute(
            """
            SELECT address_id FROM address_structures
            WHERE address_id = ANY(%s)
              AND structure_id = %s
              AND is_confirmed IS DISTINCT FROM FALSE
            """,
            (address_ids, structure_id),
        )
        rows = await self._cur.fetchall()
        return {r["address_id"] for r in rows}

    # ── Pays ───────────────────────────────────────────────────────

    async def set_countries(
        self,
        address_id: int,
        countries: list[str] | None,
    ) -> None:
        await self._cur.execute(
            "UPDATE addresses SET countries = %s WHERE id = %s",
            (countries if countries else None, address_id),
        )

    async def propagate_countries_to_similar_address(
        self,
        address_id: int,
    ) -> list[int]:
        await self._cur.execute(
            """
            UPDATE addresses a2
            SET countries = a1.countries
            FROM addresses a1
            WHERE a1.id = %s
              AND a2.normalized_text = a1.normalized_text
              AND a2.id <> a1.id
              AND LENGTH(a2.normalized_text) >= 5
            RETURNING a2.id
            """,
            (address_id,),
        )
        rows = await self._cur.fetchall()
        return [r["id"] for r in rows]

    async def batch_add_country_by_ids(
        self,
        country_code: str,
        address_ids: list[int],
    ) -> list[int]:
        await self._cur.execute(
            """
            UPDATE addresses
            SET countries = CASE
                WHEN countries IS NULL THEN ARRAY[%s]::char(2)[]
                WHEN %s = ANY(countries) THEN countries
                ELSE array_append(countries, %s::char(2))
            END
            WHERE id = ANY(%s)
            RETURNING id
            """,
            (country_code, country_code, country_code, address_ids),
        )
        rows = await self._cur.fetchall()
        return [r["id"] for r in rows]

    async def batch_add_country_by_where(
        self,
        country_code: str,
        where_clause: str,
        where_params: list,
    ) -> list[int]:
        await self._cur.execute(
            f"""
            UPDATE addresses
            SET countries = CASE
                WHEN countries IS NULL THEN ARRAY[%s]::char(2)[]
                WHEN %s = ANY(countries) THEN countries
                ELSE array_append(countries, %s::char(2))
            END
            WHERE {where_clause}
            RETURNING id
            """,
            [country_code, country_code, country_code] + where_params,
        )
        rows = await self._cur.fetchall()
        return [r["id"] for r in rows]

    async def propagate_countries_across_similar_addresses(self) -> list[int]:
        await self._cur.execute(
            """
            UPDATE addresses a2
            SET countries = a1.countries
            FROM addresses a1
            WHERE a1.countries IS NOT NULL
              AND a2.normalized_text = a1.normalized_text
              AND a2.countries IS DISTINCT FROM a1.countries
              AND LENGTH(a2.normalized_text) >= 5
              AND a2.id <> a1.id
            RETURNING a2.id
            """,
        )
        rows = await self._cur.fetchall()
        return [r["id"] for r in rows]

    # ── Propagation vers source_publications et publications ───────

    async def refresh_source_publications_countries(
        self,
        address_ids: list[int],
    ) -> int:
        await self._cur.execute(
            """
            UPDATE source_publications sd
            SET countries = sub.new_countries
            FROM (
                SELECT sa.source_publication_id AS doc_id,
                       (SELECT array_agg(DISTINCT c::text ORDER BY c::text)
                        FROM source_authorship_addresses saa2
                        JOIN addresses a2 ON a2.id = saa2.address_id
                        JOIN source_authorships sa2 ON sa2.id = saa2.source_authorship_id,
                        LATERAL unnest(a2.countries) AS c
                        WHERE sa2.source_publication_id = sa.source_publication_id
                          AND a2.countries IS NOT NULL
                       ) AS new_countries
                FROM source_authorship_addresses saa
                JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                WHERE saa.address_id = ANY(%s)
                GROUP BY sa.source_publication_id
            ) sub
            WHERE sd.id = sub.doc_id
              AND sd.countries IS DISTINCT FROM sub.new_countries
            """,
            (address_ids,),
        )
        return self._cur.rowcount

    async def refresh_publications_countries_for_addresses(
        self,
        address_ids: list[int],
    ) -> int:
        await self._cur.execute(
            """
            WITH affected_pubs AS (
                SELECT DISTINCT sd.publication_id
                FROM source_authorship_addresses saa
                JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                WHERE saa.address_id = ANY(%s) AND sd.publication_id IS NOT NULL
            )
            UPDATE publications p
            SET countries = sub.all_countries
            FROM (
                SELECT ap.publication_id,
                       (SELECT array_agg(DISTINCT c::text ORDER BY c::text)
                        FROM source_publications sd,
                        LATERAL unnest(sd.countries) AS c
                        WHERE sd.publication_id = ap.publication_id
                          AND sd.countries IS NOT NULL
                       ) AS all_countries
                FROM affected_pubs ap
            ) sub
            WHERE p.id = sub.publication_id
              AND p.countries IS DISTINCT FROM sub.all_countries
            """,
            (address_ids,),
        )
        return self._cur.rowcount
