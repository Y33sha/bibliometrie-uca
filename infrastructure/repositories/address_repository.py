"""Adapter PostgreSQL sync pour `addresses` et ses propagations.

Note : ce repo expose des méthodes de propagation cross-aggregate
(`refresh_publications_countries_for_addresses`, etc.) qui touchent
`publications.countries` et `source_publications.countries`. Pattern
accepté en exception, documenté dans `docs/architecture.md`.
"""

from sqlalchemy import Connection, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from infrastructure.db.tables import address_structures, addresses


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

    def delete_manual_structure_link(
        self,
        address_id: int,
        structure_id: int,
    ) -> bool:
        result = self._conn.execute(
            delete(address_structures)
            .where(address_structures.c.address_id == address_id)
            .where(address_structures.c.structure_id == structure_id)
            .where(address_structures.c.matched_form_id.is_(None))
        )
        return result.rowcount > 0

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

    def propagate_countries_to_similar_address(
        self,
        address_id: int,
    ) -> list[int]:
        result = self._conn.execute(
            text("""
                UPDATE addresses a2
                SET countries = a1.countries
                FROM addresses a1
                WHERE a1.id = :id
                  AND a2.normalized_text = a1.normalized_text
                  AND a2.id <> a1.id
                  AND LENGTH(a2.normalized_text) >= 5
                RETURNING a2.id
            """),
            {"id": address_id},
        )
        return [row.id for row in result]

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

    def batch_add_country_by_where(
        self,
        country_code: str,
        where_clause: str,
        where_params: list,
    ) -> list[int]:
        # `where_clause` arrive en str brut avec paramstyle psycopg `%s`.
        # SA Core `text()` utilise paramstyle nommé : on convertit à la volée.
        sql_where = where_clause
        params: dict = {"cc": country_code}
        for i, v in enumerate(where_params):
            sql_where = sql_where.replace("%s", f":p_{i}", 1)
            params[f"p_{i}"] = v
        result = self._conn.execute(
            text(f"""
                UPDATE addresses
                SET countries = CASE
                    WHEN countries IS NULL THEN ARRAY[:cc]::char(2)[]
                    WHEN :cc = ANY(countries) THEN countries
                    ELSE array_append(countries, CAST(:cc AS char(2)))
                END
                WHERE {sql_where}
                RETURNING id
            """),
            params,
        )
        return [row.id for row in result]

    def propagate_countries_across_similar_addresses(self) -> list[int]:
        result = self._conn.execute(
            text("""
                UPDATE addresses a2
                SET countries = a1.countries
                FROM addresses a1
                WHERE a1.countries IS NOT NULL
                  AND a2.normalized_text = a1.normalized_text
                  AND a2.countries IS DISTINCT FROM a1.countries
                  AND LENGTH(a2.normalized_text) >= 5
                  AND a2.id <> a1.id
                RETURNING a2.id
            """)
        )
        return [row.id for row in result]

    # ── Propagation vers source_authorships, source_publications et publications ──

    def refresh_sa_countries_for_addresses(
        self,
        address_ids: list[int],
    ) -> int:
        """Recalcule `source_authorships.countries` pour les sa pointant vers
        ces adresses (cascade ciblée après modification manuelle).

        Deux passes (mêmes principes que `refresh_sa_countries` global) :

        1. Recalcule depuis les adresses utiles pour les sa concernées
           — un sa peut avoir d'autres adresses dont les pays n'ont pas
           changé, donc on agrège sur l'ensemble.
        2. Met à NULL les sa concernées qui n'ont plus aucune adresse
           avec pays (cas où on a retiré le seul pays porteur).
        """
        if not address_ids:
            return 0
        pass_1 = self._conn.execute(
            text("""
                WITH affected_sa AS (
                    SELECT DISTINCT source_authorship_id AS sa_id
                    FROM source_authorship_addresses
                    WHERE address_id = ANY(:ids)
                ),
                expanded AS (
                    SELECT DISTINCT asa.sa_id, c::text AS country_code
                    FROM affected_sa asa
                    JOIN source_authorship_addresses saa ON saa.source_authorship_id = asa.sa_id
                    JOIN addresses a ON a.id = saa.address_id,
                    LATERAL unnest(a.countries) AS c
                    WHERE a.countries IS NOT NULL
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
            {"ids": address_ids},
        ).rowcount
        pass_2 = self._conn.execute(
            text("""
                UPDATE source_authorships sa
                SET countries = NULL
                WHERE sa.countries IS NOT NULL
                  AND sa.id IN (
                      SELECT source_authorship_id
                      FROM source_authorship_addresses
                      WHERE address_id = ANY(:ids)
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM source_authorship_addresses saa
                      JOIN addresses a ON a.id = saa.address_id
                      WHERE saa.source_authorship_id = sa.id
                        AND a.countries IS NOT NULL
                  )
            """),
            {"ids": address_ids},
        ).rowcount
        return pass_1 + pass_2

    def refresh_source_publications_countries(
        self,
        address_ids: list[int],
    ) -> int:
        if not address_ids:
            return 0
        result = self._conn.execute(
            text("""
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
                    WHERE saa.address_id = ANY(:ids)
                    GROUP BY sa.source_publication_id
                ) sub
                WHERE sd.id = sub.doc_id
                  AND sd.countries IS DISTINCT FROM sub.new_countries
            """),
            {"ids": address_ids},
        )
        return result.rowcount

    def refresh_publications_countries_for_addresses(
        self,
        address_ids: list[int],
    ) -> int:
        if not address_ids:
            return 0
        result = self._conn.execute(
            text("""
                WITH affected_pubs AS (
                    SELECT DISTINCT sd.publication_id
                    FROM source_authorship_addresses saa
                    JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    WHERE saa.address_id = ANY(:ids) AND sd.publication_id IS NOT NULL
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
            """),
            {"ids": address_ids},
        )
        return result.rowcount
