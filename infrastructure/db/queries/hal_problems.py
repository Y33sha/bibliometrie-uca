"""Query services async pour le router `/api/hal-problems/*`.

Contrôles qualité HAL au niveau des publications (doublons de dépôts,
manques dans les collections, conflits d'affiliation) + comptes HAL
multiples par personne. Implémente le port
`application.ports.hal_problems_queries.AsyncHalProblemsQueries` via
`PgAsyncHalProblemsQueries` (duck typing).
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class PgAsyncHalProblemsQueries:
    """Adapter SA pour `AsyncHalProblemsQueries`."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def _hal_pub_detail(self, pub_id: int) -> dict[str, Any] | None:
        """Détail publication pour doublons HAL."""
        pub_row = (
            await self._conn.execute(
                text("""
                    SELECT p.id, p.title, p.pub_year, p.doc_type::text AS doc_type,
                           p.doi, p.container_title
                    FROM publications p WHERE p.id = :pid
                """),
                {"pid": pub_id},
            )
        ).one_or_none()
        if not pub_row:
            return None
        hal_rows = (
            await self._conn.execute(
                text("""
                    SELECT sd.source_id AS halid, sd.hal_collections,
                           sd.doc_type AS hal_doc_type,
                           sd.pub_year AS hal_pub_year, sd.title AS hal_title,
                           (SELECT COUNT(*) FROM source_authorships sa2
                            WHERE sa2.source = 'hal' AND sa2.source_publication_id = sd.id
                              AND NOT sa2.excluded) AS author_count
                    FROM source_publications sd
                    WHERE sd.publication_id = :pid AND sd.source = 'hal'
                """),
                {"pid": pub_id},
            )
        ).all()
        hal_docs = [dict(r._mapping) for r in hal_rows]
        return {**dict(pub_row._mapping), "hal_docs": hal_docs}

    async def hal_duplicate_accounts(self, *, page: int, per_page: int) -> dict[str, Any]:
        """Personnes liées à 2+ comptes HAL distincts."""
        offset = (page - 1) * per_page
        total_row = (
            await self._conn.execute(
                text("""
                    SELECT COUNT(*) AS total FROM (
                        SELECT person_id
                        FROM source_persons
                        WHERE source = 'hal' AND person_id IS NOT NULL
                          AND (source_ids->>'hal_person_id') IS NOT NULL
                        GROUP BY person_id
                        HAVING COUNT(DISTINCT source_ids->>'hal_person_id') >= 2
                    ) sub
                """)
            )
        ).one()
        total = total_row.total

        rows = (
            await self._conn.execute(
                text("""
                    SELECT p.id AS person_id, p.last_name, p.first_name,
                           (prh.id IS NOT NULL) AS has_rh,
                           (SELECT json_agg(json_build_object(
                               'hal_person_id', (sa.source_ids->>'hal_person_id')::int,
                               'full_name', sa.full_name,
                               'idhal', sa.source_ids->>'idhal',
                               'orcid', sa.orcid,
                               'pub_count', (SELECT COUNT(*) FROM source_authorships sa2
                                             WHERE sa2.source = 'hal'
                                               AND sa2.source_person_id = sa.id)
                           ) ORDER BY (sa.source_ids->>'hal_person_id')::int)
                            FROM source_persons sa
                            WHERE sa.source = 'hal' AND sa.person_id = p.id
                              AND (sa.source_ids->>'hal_person_id') IS NOT NULL
                           ) AS hal_accounts
                    FROM persons p
                    LEFT JOIN persons_rh prh ON prh.person_id = p.id
                    WHERE p.id IN (
                        SELECT person_id
                        FROM source_persons
                        WHERE source = 'hal' AND person_id IS NOT NULL
                          AND (source_ids->>'hal_person_id') IS NOT NULL
                        GROUP BY person_id
                        HAVING COUNT(DISTINCT source_ids->>'hal_person_id') >= 2
                    )
                    ORDER BY LOWER(p.last_name), LOWER(p.first_name)
                    LIMIT :pg_limit OFFSET :pg_offset
                """),
                {"pg_limit": per_page, "pg_offset": offset},
            )
        ).all()
        persons = [dict(r._mapping) for r in rows]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "persons": persons,
        }

    async def hal_duplicate_pubs_by_doi(self, *, page: int, per_page: int) -> dict[str, Any]:
        """Dépôts HAL avec DOI identique rattachés à la même publication."""
        offset = (page - 1) * per_page
        total_row = (
            await self._conn.execute(
                text("""
                    SELECT COUNT(*) AS total FROM (
                        SELECT sd.publication_id, LOWER(sd.doi)
                        FROM source_publications sd
                        WHERE sd.source = 'hal' AND sd.doi IS NOT NULL AND sd.doi != ''
                        GROUP BY sd.publication_id, LOWER(sd.doi)
                        HAVING COUNT(*) >= 2
                    ) sub
                """)
            )
        ).one()
        total = total_row.total

        rows = (
            await self._conn.execute(
                text("""
                    SELECT LOWER(sd.doi) AS doi,
                           sd.publication_id AS pub_id,
                           array_agg(sd.source_id ORDER BY sd.source_id) AS halids
                    FROM source_publications sd
                    WHERE sd.source = 'hal' AND sd.doi IS NOT NULL AND sd.doi != ''
                    GROUP BY sd.publication_id, LOWER(sd.doi)
                    HAVING COUNT(*) >= 2
                    ORDER BY LOWER(sd.doi)
                    LIMIT :pg_limit OFFSET :pg_offset
                """),
                {"pg_limit": per_page, "pg_offset": offset},
            )
        ).all()
        pairs = []
        for r in rows:
            pub = await self._hal_pub_detail(r.pub_id)
            if pub:
                pairs.append({"doi": r.doi, "halids": r.halids, "publication": pub})

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "pairs": pairs,
        }

    async def hal_duplicate_pubs_by_metadata(self, *, page: int, per_page: int) -> dict[str, Any]:
        """Doublons possibles : dépôts HAL avec métadonnées identiques."""
        offset = (page - 1) * per_page
        dup_query = """
            FROM publications p1
            JOIN publications p2
              ON p1.title_normalized = p2.title_normalized AND p1.id < p2.id
            JOIN source_publications hd1
              ON hd1.publication_id = p1.id AND hd1.source = 'hal'
            JOIN source_publications hd2
              ON hd2.publication_id = p2.id AND hd2.source = 'hal'
            WHERE LENGTH(p1.title_normalized) > 30
              AND p1.pub_year = p2.pub_year
              AND p1.doc_type = p2.doc_type
              AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL
                       AND LOWER(p1.doi) <> LOWER(p2.doi))
              AND ABS(
                  (SELECT COUNT(*) FROM source_authorships sa1
                   WHERE sa1.source = 'hal' AND sa1.source_publication_id = hd1.id
                     AND NOT sa1.excluded)
                  - (SELECT COUNT(*) FROM source_authorships sa2
                     WHERE sa2.source = 'hal' AND sa2.source_publication_id = hd2.id
                       AND NOT sa2.excluded)
              ) <= 2
              AND NOT EXISTS (SELECT 1 FROM distinct_publications dp
                              WHERE dp.pub_id_a = LEAST(p1.id, p2.id)
                                AND dp.pub_id_b = GREATEST(p1.id, p2.id))
        """

        total_row = (await self._conn.execute(text(f"SELECT COUNT(*) AS total {dup_query}"))).one()
        total = total_row.total

        rows = (
            await self._conn.execute(
                text(f"""
                    SELECT p1.id AS id_a, p2.id AS id_b
                    {dup_query}
                    ORDER BY p1.id
                    LIMIT :pg_limit OFFSET :pg_offset
                """),
                {"pg_limit": per_page, "pg_offset": offset},
            )
        ).all()
        pairs = []
        for r in rows:
            pub_a = await self._hal_pub_detail(r.id_a)
            pub_b = await self._hal_pub_detail(r.id_b)
            if pub_a and pub_b:
                pairs.append({"pub_a": pub_a, "pub_b": pub_b})

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "pairs": pairs,
        }

    async def hal_missing_collections_labs(self) -> list[dict[str, Any]]:
        """Liste des labos avec collection HAL configurée."""
        rows = (
            await self._conn.execute(
                text("""
                    SELECT s.id, s.acronym, s.name, s.hal_collection
                    FROM structures s
                    WHERE s.hal_collection IS NOT NULL AND s.structure_type = 'labo'
                    ORDER BY s.acronym
                """)
            )
        ).all()
        return [dict(r._mapping) for r in rows]

    async def hal_missing_collections(
        self, *, lab_id: int, page: int, per_page: int
    ) -> dict[str, Any]:
        """Publications affiliées à un labo sur OA/WoS, présentes dans HAL,
        mais absentes de la collection HAL du labo."""
        lab_row = (
            await self._conn.execute(
                text("SELECT acronym, hal_collection FROM structures WHERE id = :id"),
                {"id": lab_id},
            )
        ).one_or_none()
        if not lab_row or not lab_row.hal_collection:
            return {"error": "no_collection"}

        offset = (page - 1) * per_page
        col = lab_row.hal_collection
        binds: dict[str, Any] = {
            "lab_arr": [lab_id],
            "col": col,
            "pg_limit": per_page,
            "pg_offset": offset,
        }

        base_where = """
            FROM publications p
            JOIN authorships a
              ON a.publication_id = p.id
             AND a.structure_ids && CAST(:lab_arr AS int[])
            WHERE EXISTS (SELECT 1 FROM source_publications sd
                          WHERE sd.publication_id = p.id AND sd.source = 'hal')
              AND NOT EXISTS (SELECT 1 FROM source_publications sd
                              WHERE sd.publication_id = p.id AND sd.source = 'hal'
                                AND :col = ANY(sd.hal_collections))
        """

        total_row = (
            await self._conn.execute(
                text(f"SELECT COUNT(DISTINCT p.id) AS total {base_where}"),
                binds,
            )
        ).one()
        total = total_row.total

        rows = (
            await self._conn.execute(
                text(f"""
                    SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text AS doc_type,
                           p.doi,
                           (SELECT array_agg(sd2.source_id) FROM source_publications sd2
                            WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
                           NOT EXISTS (SELECT 1 FROM source_publications sd2
                                       WHERE sd2.publication_id = p.id AND sd2.source = 'hal'
                                         AND 'PRES_CLERMONT' = ANY(sd2.hal_collections)) AS hors_uca
                    {base_where}
                    ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
                    LIMIT :pg_limit OFFSET :pg_offset
                """),
                binds,
            )
        ).all()
        pubs = [dict(r._mapping) for r in rows]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "lab_acronym": lab_row.acronym,
            "hal_collection": col,
            "publications": pubs,
        }

    async def hal_affiliation_conflicts(self, *, page: int, per_page: int) -> dict[str, Any]:
        """Publications affiliées UCA dans HAL mais pas dans une autre source."""
        offset = (page - 1) * per_page
        # On cherche les positions d'auteur où HAL atteste l'UCA et où au moins
        # une autre source (non-HAL) a examiné la même position et conclu hors-UCA.
        # `EXISTS source_authorship_addresses` sert de preuve que la source a
        # examiné l'affiliation (crossref n'en produit pas, donc exclu de fait).
        base_cte = """
        WITH hal_uca AS (
            SELECT a.publication_id, a.author_position
            FROM authorships a
            WHERE a.in_perimeter = TRUE
              AND EXISTS (SELECT 1 FROM source_authorships sa
                          WHERE sa.authorship_id = a.id AND sa.source = 'hal')
              AND EXISTS (SELECT 1 FROM structures s
                          WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo')
        ),
        conflict_pubs AS (
            SELECT DISTINCT h.publication_id
            FROM hal_uca h
            JOIN source_publications sd
              ON sd.publication_id = h.publication_id
             AND sd.source <> 'hal'
            JOIN source_authorships sa
              ON sa.source_publication_id = sd.id
             AND sa.author_position = h.author_position
            WHERE sa.source <> 'hal'
              AND sa.in_perimeter = FALSE
              AND EXISTS (SELECT 1 FROM source_authorship_addresses saa
                          WHERE saa.source_authorship_id = sa.id)
        )
        """

        total_row = (
            await self._conn.execute(text(f"{base_cte} SELECT COUNT(*) AS n FROM conflict_pubs"))
        ).one()
        total = total_row.n

        rows = (
            await self._conn.execute(
                text(f"""
                    {base_cte}
                    SELECT p.id, p.title, p.pub_year, p.doc_type::text AS doc_type, p.doi,
                           (SELECT array_agg(sd2.source_id) FROM source_publications sd2
                            WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
                           (SELECT string_agg(DISTINCT s.acronym, ', ' ORDER BY s.acronym)
                            FROM authorships a2
                            JOIN structures s ON s.id = ANY(a2.structure_ids)
                            WHERE a2.publication_id = p.id
                              AND a2.in_perimeter = TRUE
                              AND s.structure_type = 'labo') AS labs
                    FROM conflict_pubs cp
                    JOIN publications p ON p.id = cp.publication_id
                    ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
                    LIMIT :pg_limit OFFSET :pg_offset
                """),
                {"pg_limit": per_page, "pg_offset": offset},
            )
        ).all()
        pubs = [
            {
                "id": r.id,
                "title": r.title,
                "pub_year": r.pub_year,
                "doc_type": r.doc_type,
                "doi": r.doi,
                "halids": r.halids,
                "labs": r.labs,
            }
            for r in rows
        ]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "publications": pubs,
        }
