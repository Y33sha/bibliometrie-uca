"""Adapter PostgreSQL pour `addresses`, `address_structures` et leurs
propagations vers source_publications/publications.countries.
"""

from psycopg2.extras import execute_values


class PgAddressRepository:
    """Accès PostgreSQL à l'agrégat Address."""

    def __init__(self, cur):
        self._cur = cur

    # ── Validation des liens adresse ↔ structure ───────────────────

    def reset_manual_link(self, address_id: int, structure_id: int) -> None:
        """Retire le lien manuel (matched_form_id IS NULL) et remet les
        liens auto-détectés restants à is_confirmed=NULL."""
        self._cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = %s AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_id, structure_id),
        )
        self._cur.execute(
            """
            UPDATE address_structures SET is_confirmed = NULL
            WHERE address_id = %s AND structure_id = %s
            """,
            (address_id, structure_id),
        )

    def upsert_structure_link(
        self, address_id: int, structure_id: int, is_confirmed: bool,
    ) -> None:
        """Upsert le lien address ↔ structure avec is_confirmed (True/False)."""
        self._cur.execute(
            """
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES (%s, %s, %s)
            ON CONFLICT (address_id, structure_id) DO UPDATE
                SET is_confirmed = EXCLUDED.is_confirmed
            """,
            (address_id, structure_id, is_confirmed),
        )

    def batch_reset_manual_links(
        self, address_ids: list[int], structure_id: int,
    ) -> int:
        """Version batch de reset_manual_link. Retourne le nombre de lignes
        remises à is_confirmed=NULL (après suppression des liens manuels)."""
        self._cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = ANY(%s) AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_ids, structure_id),
        )
        self._cur.execute(
            """
            UPDATE address_structures SET is_confirmed = NULL
            WHERE address_id = ANY(%s) AND structure_id = %s
            """,
            (address_ids, structure_id),
        )
        return self._cur.rowcount

    def batch_upsert_structure_links(
        self, address_ids: list[int], structure_id: int, is_confirmed: bool,
    ) -> None:
        """Upsert en batch via execute_values."""
        execute_values(
            self._cur,
            """
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES %s
            ON CONFLICT (address_id, structure_id) DO UPDATE
                SET is_confirmed = EXCLUDED.is_confirmed
            """,
            [(aid, structure_id, is_confirmed) for aid in address_ids],
        )

    def delete_manual_structure_link(
        self, address_id: int, structure_id: int,
    ) -> bool:
        """Supprime uniquement le lien manuel (matched_form_id IS NULL).
        Retourne True si une ligne a été supprimée."""
        self._cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = %s AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_id, structure_id),
        )
        return self._cur.rowcount > 0

    # ── Pays ───────────────────────────────────────────────────────

    def set_countries(
        self, address_id: int, countries: list[str] | None,
    ) -> None:
        """Fixe la colonne countries (NULL si vide)."""
        self._cur.execute(
            "UPDATE addresses SET countries = %s WHERE id = %s",
            (countries if countries else None, address_id),
        )

    def propagate_countries_to_similar_address(
        self, address_id: int,
    ) -> list[int]:
        """Réplique addresses.countries vers les adresses ayant le même
        normalized_text (len >= 5). Retourne les IDs propagés."""
        self._cur.execute(
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
        return [r["id"] for r in self._cur.fetchall()]

    def batch_add_country_by_ids(
        self, country_code: str, address_ids: list[int],
    ) -> list[int]:
        """Ajoute country_code à addresses.countries pour chaque id du lot.
        Idempotent (no-op si déjà présent)."""
        self._cur.execute(
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
        return [r["id"] for r in self._cur.fetchall()]

    def batch_add_country_by_where(
        self, country_code: str, where_clause: str, where_params: list,
    ) -> list[int]:
        """Ajoute country_code sur un WHERE dynamique construit par le
        service. Le service est responsable d'échapper ses filtres (tous
        utilisent des paramètres %s)."""
        self._cur.execute(
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
        return [r["id"] for r in self._cur.fetchall()]

    def propagate_countries_across_similar_addresses(self) -> list[int]:
        """Propage les countries entre toutes les adresses de même
        normalized_text différant sur la valeur — s'utilise après un
        batch_add_country_by_* pour homogénéiser le référentiel."""
        self._cur.execute(
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
        return [r["id"] for r in self._cur.fetchall()]

    # ── Propagation vers source_publications et publications ───────

    def refresh_source_publications_countries(
        self, address_ids: list[int],
    ) -> int:
        """Recalcule source_publications.countries à partir des adresses
        touchées. Retourne le nombre de lignes réellement modifiées."""
        self._cur.execute(
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

    def refresh_publications_countries_for_addresses(
        self, address_ids: list[int],
    ) -> int:
        """Recalcule publications.countries (union des source_publications).
        À appeler APRÈS refresh_source_publications_countries."""
        self._cur.execute(
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
