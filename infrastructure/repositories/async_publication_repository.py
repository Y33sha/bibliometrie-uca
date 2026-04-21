"""Adapter PostgreSQL async pour les publications (§2.12).

Parallèle à infrastructure/repositories/publication_repository.py.
"""

from typing import Any

from domain.publication import (
    PubByDoi,
    PubByNnt,
    PubByTitle,
    PubThesisCandidate,
)
from infrastructure.db.queries.filters import OA_CLOSED_SQL
from infrastructure.db_helpers import async_row_as
from infrastructure.db_helpers import row_val as _val


class PgAsyncPublicationRepository:
    """Accès PostgreSQL async à l'agrégat Publication."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    # ── Recherches ─────────────────────────────────────────────────

    async def find_by_doi(self, doi: str) -> PubByDoi | None:
        if not doi:
            return None
        async with async_row_as(self._cur, PubByDoi) as cur:
            await cur.execute(
                "SELECT id, doc_type, title_normalized FROM publications "
                "WHERE lower(doi) = lower(%s)",
                (doi,),
            )
            return await cur.fetchone()

    async def find_by_nnt(self, nnt: str) -> PubByNnt | None:
        if not nnt:
            return None
        async with async_row_as(self._cur, PubByNnt) as cur:
            await cur.execute(
                """
                SELECT p.id, p.doc_type, p.title_normalized
                FROM publications p
                JOIN source_publications sd ON sd.publication_id = p.id
                WHERE sd.external_ids->>'nnt' = %s
                LIMIT 1
                """,
                (nnt.upper(),),
            )
            return await cur.fetchone()

    async def find_by_title(
        self,
        title_normalized: str,
        pub_year: int,
        journal_id: int,
    ) -> PubByTitle | None:
        if not title_normalized or not journal_id:
            return None
        async with async_row_as(self._cur, PubByTitle) as cur:
            await cur.execute(
                """
                SELECT id, doi FROM publications
                WHERE title_normalized = %s AND pub_year = %s AND journal_id = %s
                LIMIT 1
                """,
                (title_normalized, pub_year, journal_id),
            )
            return await cur.fetchone()

    async def find_thesis_by_title(
        self,
        title_normalized: str,
        pub_year: int,
    ) -> list[PubThesisCandidate]:
        if not title_normalized or not pub_year:
            return []
        async with async_row_as(self._cur, PubThesisCandidate) as cur:
            await cur.execute(
                """
                SELECT id, doi FROM publications
                WHERE title_normalized = %s AND pub_year = %s
                  AND doc_type IN ('thesis', 'ongoing_thesis')
                ORDER BY id
                """,
                (title_normalized, pub_year),
            )
            return await cur.fetchall()

    # ── Écritures simples ──────────────────────────────────────────

    async def update_oa_status(self, pub_id: int, oa_status: str) -> None:
        await self._cur.execute(
            """
            UPDATE publications SET oa_status = %s::oa_type, updated_at = now()
            WHERE id = %s
            """,
            (oa_status, pub_id),
        )

    async def update_countries(self, pub_id: int, countries: list[str]) -> None:
        await self._cur.execute(
            """
            UPDATE publications SET countries = %s, updated_at = now()
            WHERE id = %s
            """,
            (countries, pub_id),
        )

    async def update_sources(self, pub_id: int) -> None:
        await self._cur.execute(
            """
            UPDATE publications SET sources = COALESCE(sub.srcs, '{}'), updated_at = now()
            FROM (
                SELECT array_agg(DISTINCT source::source_type ORDER BY source::source_type) AS srcs
                FROM source_publications
                WHERE publication_id = %s
            ) sub
            WHERE id = %s
            """,
            (pub_id, pub_id),
        )

    # ── Accès bas niveau au champ doi ──────────────────────────────

    async def get_doi(self, pub_id: int) -> str | None:
        await self._cur.execute("SELECT doi FROM publications WHERE id = %s", (pub_id,))
        row = await self._cur.fetchone()
        if row is None:
            return None
        return row["doi"] if isinstance(row, dict) else row[0]

    async def set_doi(self, pub_id: int, doi: str) -> None:
        await self._cur.execute(
            "UPDATE publications SET doi = %s, updated_at = now() WHERE id = %s",
            (doi, pub_id),
        )

    async def clear_doi(self, pub_id: int) -> None:
        await self._cur.execute(
            "UPDATE publications SET doi = NULL, updated_at = now() WHERE id = %s",
            (pub_id,),
        )

    # ── Agrégation depuis source_publications ──────────────────────

    async def get_source_rows(self, pub_id: int) -> list[dict]:
        """Retourne les lignes source_publications pour refresh_from_sources.

        Ouvre un curseur dict_row local — le curseur courant peut être
        en class_row ou autre, mais ici on veut un accès par nom.
        """
        from psycopg.rows import dict_row

        async with self._cur.connection.cursor(row_factory=dict_row) as dict_cur:
            await dict_cur.execute(
                """
                SELECT source, doi, doc_type, pub_year, journal_id, oa_status,
                       container_title, language, abstract, keywords, countries,
                       topics, biblio, meta, is_retracted, external_ids
                FROM source_publications
                WHERE publication_id = %s
                """,
                (pub_id,),
            )
            return await dict_cur.fetchall()

    async def update_aggregated(
        self,
        pub_id: int,
        *,
        doi: str | None,
        doc_type: str,
        pub_year: int | None,
        journal_id: int | None,
        oa_status: str | None,
        container_title: str | None,
        language: str | None,
        abstract: str | None,
        keywords: list[str] | None,
        countries: list[str] | None,
        topics: dict | None,
        biblio: dict | None,
        meta: dict | None,
        is_retracted: bool,
    ) -> None:
        from psycopg.types.json import Jsonb as Json

        await self._cur.execute(
            """
            UPDATE publications SET
                doi = %s, doc_type = %s::doc_type, pub_year = %s,
                journal_id = %s, oa_status = %s::oa_type,
                container_title = %s, language = %s, abstract = %s,
                keywords = %s, countries = %s,
                topics = %s, biblio = %s, meta = %s,
                is_retracted = %s, updated_at = now()
            WHERE id = %s
            """,
            (
                doi,
                doc_type,
                pub_year,
                journal_id,
                oa_status,
                container_title,
                language,
                abstract,
                keywords,
                countries,
                Json(topics) if topics else None,
                Json(biblio) if biblio else None,
                Json(meta) if meta else None,
                is_retracted,
                pub_id,
            ),
        )

    # ── Création ───────────────────────────────────────────────────

    async def create(
        self,
        *,
        title: str,
        title_normalized: str,
        doc_type: str,
        pub_year: int,
        doi: str | None,
        oa_status: str,
        journal_id: int | None,
        container_title: str | None,
        language: str | None,
    ) -> int:
        await self._cur.execute(
            """
            INSERT INTO publications
                (title, title_normalized, doc_type, pub_year, doi,
                 oa_status, journal_id, container_title, language)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                title,
                title_normalized,
                doc_type,
                pub_year,
                doi,
                oa_status,
                journal_id,
                container_title,
                language,
            ),
        )
        return _val(await self._cur.fetchone(), 0)

    # ── Fusion ─────────────────────────────────────────────────────

    async def merge_into(self, target_id: int, source_id: int) -> None:
        # 1. Transférer les source_publications
        await self._cur.execute(
            "UPDATE source_publications SET publication_id = %s WHERE publication_id = %s",
            (target_id, source_id),
        )

        # 2. Transférer les authorships vérité (dédup par person_id)
        await self._cur.execute(
            """
            DELETE FROM authorships
            WHERE publication_id = %s
              AND person_id IN (
                  SELECT person_id FROM authorships WHERE publication_id = %s
              )
            """,
            (source_id, target_id),
        )
        await self._cur.execute(
            "UPDATE authorships SET publication_id = %s WHERE publication_id = %s",
            (target_id, source_id),
        )

        # 3. Enrichir la cible avec les métadonnées de la source.
        await self._cur.execute(
            """
            SELECT doi, journal_id, oa_status::text AS oa_status,
                   language, container_title, countries
            FROM publications WHERE id = %s
            """,
            (source_id,),
        )
        src = await self._cur.fetchone()
        await self._cur.execute("UPDATE publications SET doi = NULL WHERE id = %s", (source_id,))
        await self._cur.execute(
            f"""
            UPDATE publications SET
                doi = COALESCE(doi, LOWER(%s)),
                journal_id = COALESCE(journal_id, %s),
                oa_status = CASE
                    WHEN %s = 'diamond' THEN 'diamond'::oa_type
                    WHEN oa_status IN {OA_CLOSED_SQL}
                        AND %s NOT IN {OA_CLOSED_SQL}
                    THEN %s::oa_type ELSE oa_status END,
                language = COALESCE(language, %s),
                container_title = COALESCE(container_title, %s),
                countries = CASE
                    WHEN countries IS NULL THEN %s::text[]
                    WHEN %s::text[] IS NULL THEN countries
                    ELSE (SELECT array_agg(DISTINCT c ORDER BY c)
                          FROM unnest(countries || %s::text[]) AS c)
                    END,
                updated_at = now()
            WHERE id = %s
            """,
            (
                src["doi"],
                src["journal_id"],
                src["oa_status"],
                src["oa_status"],
                src["oa_status"],
                src["language"],
                src["container_title"],
                src["countries"],
                src["countries"],
                src["countries"],
                target_id,
            ),
        )

        # 4. Nettoyer distinct_publications et supprimer la source
        await self._cur.execute(
            """
            DELETE FROM distinct_publications
            WHERE pub_id_a = %s OR pub_id_b = %s
            """,
            (source_id, source_id),
        )
        await self._cur.execute("DELETE FROM publications WHERE id = %s", (source_id,))

    # ── distinct_publications ──────────────────────────────────────

    async def mark_distinct(self, pub_id_a: int, pub_id_b: int) -> tuple[int, int] | None:
        await self._cur.execute(
            """
            INSERT INTO distinct_publications (pub_id_a, pub_id_b)
            VALUES (LEAST(%s, %s), GREATEST(%s, %s))
            ON CONFLICT DO NOTHING
            RETURNING pub_id_a, pub_id_b
            """,
            (pub_id_a, pub_id_b, pub_id_a, pub_id_b),
        )
        row = await self._cur.fetchone()
        if not row:
            return None
        return row["pub_id_a"], row["pub_id_b"]
