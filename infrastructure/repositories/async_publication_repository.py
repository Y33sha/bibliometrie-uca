"""Adapter PostgreSQL async pour les publications.

Parallèle à infrastructure/repositories/publication_repository.py.

Mode dispatch (cur psycopg | AsyncConnection SA) pour cohabiter avec le
chantier sqlalchemy-core-adoption (sous-phase 2.7). Phase 4 supprimera
la branche psycopg.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

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
    """Accès PostgreSQL async à l'agrégat Publication.

    Accepte un curseur psycopg ou une AsyncConnection SQLAlchemy.
    """

    def __init__(self, conn_or_cur: Any) -> None:
        self._conn = conn_or_cur
        self._is_sa = isinstance(conn_or_cur, AsyncConnection)

    # ── Recherches ─────────────────────────────────────────────────

    async def find_by_doi(self, doi: str) -> PubByDoi | None:
        if not doi:
            return None
        if self._is_sa:
            result = await self._conn.execute(
                text(
                    "SELECT id, CAST(doc_type AS text) AS doc_type, title_normalized "
                    "FROM publications WHERE lower(doi) = lower(:doi)"
                ),
                {"doi": doi},
            )
            row = result.first()
            if not row:
                return None
            return PubByDoi(id=row.id, doc_type=row.doc_type, title_normalized=row.title_normalized)
        async with async_row_as(self._conn, PubByDoi) as cur:
            await cur.execute(
                "SELECT id, doc_type, title_normalized FROM publications "
                "WHERE lower(doi) = lower(%s)",
                (doi,),
            )
            return await cur.fetchone()

    async def find_by_nnt(self, nnt: str) -> PubByNnt | None:
        if not nnt:
            return None
        if self._is_sa:
            result = await self._conn.execute(
                text("""
                    SELECT p.id, CAST(p.doc_type AS text) AS doc_type, p.title_normalized
                    FROM publications p
                    JOIN source_publications sd ON sd.publication_id = p.id
                    WHERE sd.external_ids->>'nnt' = :nnt
                    LIMIT 1
                """),
                {"nnt": nnt.upper()},
            )
            row = result.first()
            if not row:
                return None
            return PubByNnt(id=row.id, doc_type=row.doc_type, title_normalized=row.title_normalized)
        async with async_row_as(self._conn, PubByNnt) as cur:
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
        if self._is_sa:
            result = await self._conn.execute(
                text("""
                    SELECT id, doi FROM publications
                    WHERE title_normalized = :tn AND pub_year = :py AND journal_id = :jid
                    LIMIT 1
                """),
                {"tn": title_normalized, "py": pub_year, "jid": journal_id},
            )
            row = result.first()
            if not row:
                return None
            return PubByTitle(id=row.id, doi=row.doi)
        async with async_row_as(self._conn, PubByTitle) as cur:
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
        if self._is_sa:
            result = await self._conn.execute(
                text("""
                    SELECT id, doi FROM publications
                    WHERE title_normalized = :tn AND pub_year = :py
                      AND doc_type IN ('thesis', 'ongoing_thesis')
                    ORDER BY id
                """),
                {"tn": title_normalized, "py": pub_year},
            )
            return [PubThesisCandidate(id=row.id, doi=row.doi) for row in result]
        async with async_row_as(self._conn, PubThesisCandidate) as cur:
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
        if self._is_sa:
            await self._conn.execute(
                text(
                    "UPDATE publications "
                    "SET oa_status = CAST(:os AS oa_type), updated_at = now() "
                    "WHERE id = :id"
                ),
                {"os": oa_status, "id": pub_id},
            )
            return
        await self._conn.execute(
            """
            UPDATE publications SET oa_status = %s::oa_type, updated_at = now()
            WHERE id = %s
            """,
            (oa_status, pub_id),
        )

    async def update_countries(self, pub_id: int, countries: list[str]) -> None:
        if self._is_sa:
            await self._conn.execute(
                text("UPDATE publications SET countries = :c, updated_at = now() WHERE id = :id"),
                {"c": countries, "id": pub_id},
            )
            return
        await self._conn.execute(
            """
            UPDATE publications SET countries = %s, updated_at = now()
            WHERE id = %s
            """,
            (countries, pub_id),
        )

    async def update_sources(self, pub_id: int) -> None:
        if self._is_sa:
            await self._conn.execute(
                text("""
                    UPDATE publications SET sources = COALESCE(sub.srcs, '{}'),
                                            updated_at = now()
                    FROM (
                        SELECT array_agg(
                            DISTINCT CAST(source AS source_type)
                            ORDER BY CAST(source AS source_type)
                        ) AS srcs
                        FROM source_publications
                        WHERE publication_id = :id
                    ) sub
                    WHERE id = :id
                """),
                {"id": pub_id},
            )
            return
        await self._conn.execute(
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
        if self._is_sa:
            result = await self._conn.execute(
                text("SELECT doi FROM publications WHERE id = :id"), {"id": pub_id}
            )
            return result.scalar_one_or_none()
        await self._conn.execute("SELECT doi FROM publications WHERE id = %s", (pub_id,))
        row = await self._conn.fetchone()
        if row is None:
            return None
        return row["doi"] if isinstance(row, dict) else row[0]

    async def set_doi(self, pub_id: int, doi: str) -> None:
        if self._is_sa:
            await self._conn.execute(
                text("UPDATE publications SET doi = :doi, updated_at = now() WHERE id = :id"),
                {"doi": doi, "id": pub_id},
            )
            return
        await self._conn.execute(
            "UPDATE publications SET doi = %s, updated_at = now() WHERE id = %s",
            (doi, pub_id),
        )

    async def clear_doi(self, pub_id: int) -> None:
        if self._is_sa:
            await self._conn.execute(
                text("UPDATE publications SET doi = NULL, updated_at = now() WHERE id = :id"),
                {"id": pub_id},
            )
            return
        await self._conn.execute(
            "UPDATE publications SET doi = NULL, updated_at = now() WHERE id = %s",
            (pub_id,),
        )

    # ── Agrégation depuis source_publications ──────────────────────

    async def get_source_rows(self, pub_id: int) -> list[dict]:
        """Retourne les lignes source_publications pour refresh_from_sources.

        Ouvre un curseur dict_row local — le curseur courant peut être
        en class_row ou autre, mais ici on veut un accès par nom.
        """
        if self._is_sa:
            result = await self._conn.execute(
                text("""
                    SELECT source, doi, doc_type, pub_year, journal_id, oa_status,
                           container_title, language, abstract, keywords, countries,
                           topics, biblio, meta, is_retracted, external_ids
                    FROM source_publications
                    WHERE publication_id = :id
                """),
                {"id": pub_id},
            )
            return [dict(row._mapping) for row in result]
        from psycopg.rows import dict_row

        async with self._conn.connection.cursor(row_factory=dict_row) as dict_cur:
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
        if self._is_sa:
            # SA sérialise auto les dict en JSONB — pas de Json() wrap.
            await self._conn.execute(
                text("""
                    UPDATE publications SET
                        doi = :doi, doc_type = CAST(:doc_type AS doc_type),
                        pub_year = :pub_year, journal_id = :journal_id,
                        oa_status = CAST(:oa_status AS oa_type),
                        container_title = :container_title, language = :language,
                        abstract = :abstract, keywords = :keywords,
                        countries = :countries, topics = CAST(:topics AS jsonb),
                        biblio = CAST(:biblio AS jsonb), meta = CAST(:meta AS jsonb),
                        is_retracted = :is_retracted, updated_at = now()
                    WHERE id = :pub_id
                """),
                {
                    "doi": doi,
                    "doc_type": doc_type,
                    "pub_year": pub_year,
                    "journal_id": journal_id,
                    "oa_status": oa_status,
                    "container_title": container_title,
                    "language": language,
                    "abstract": abstract,
                    "keywords": keywords,
                    "countries": countries,
                    "topics": _json_dumps_or_none(topics),
                    "biblio": _json_dumps_or_none(biblio),
                    "meta": _json_dumps_or_none(meta),
                    "is_retracted": is_retracted,
                    "pub_id": pub_id,
                },
            )
            return
        from psycopg.types.json import Jsonb as Json

        await self._conn.execute(
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
        if self._is_sa:
            result = await self._conn.execute(
                text("""
                    INSERT INTO publications
                        (title, title_normalized, doc_type, pub_year, doi,
                         oa_status, journal_id, container_title, language)
                    VALUES (:title, :tn, CAST(:doc_type AS doc_type), :py, :doi,
                            CAST(:oa AS oa_type), :jid, :ct, :lang)
                    RETURNING id
                """),
                {
                    "title": title,
                    "tn": title_normalized,
                    "doc_type": doc_type,
                    "py": pub_year,
                    "doi": doi,
                    "oa": oa_status,
                    "jid": journal_id,
                    "ct": container_title,
                    "lang": language,
                },
            )
            return result.scalar_one()
        await self._conn.execute(
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
        return _val(await self._conn.fetchone(), 0)

    # ── Fusion ─────────────────────────────────────────────────────

    async def merge_into(self, target_id: int, source_id: int) -> None:
        if self._is_sa:
            await _merge_into_sa(self._conn, target_id, source_id)
            return

        # 1. Transférer les source_publications
        await self._conn.execute(
            "UPDATE source_publications SET publication_id = %s WHERE publication_id = %s",
            (target_id, source_id),
        )

        # 2. Transférer les authorships vérité (dédup par person_id)
        await self._conn.execute(
            """
            DELETE FROM authorships
            WHERE publication_id = %s
              AND person_id IN (
                  SELECT person_id FROM authorships WHERE publication_id = %s
              )
            """,
            (source_id, target_id),
        )
        await self._conn.execute(
            "UPDATE authorships SET publication_id = %s WHERE publication_id = %s",
            (target_id, source_id),
        )

        # 3. Enrichir la cible avec les métadonnées de la source.
        await self._conn.execute(
            """
            SELECT doi, journal_id, oa_status::text AS oa_status,
                   language, container_title, countries
            FROM publications WHERE id = %s
            """,
            (source_id,),
        )
        src = await self._conn.fetchone()
        await self._conn.execute("UPDATE publications SET doi = NULL WHERE id = %s", (source_id,))
        await self._conn.execute(
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
        await self._conn.execute(
            """
            DELETE FROM distinct_publications
            WHERE pub_id_a = %s OR pub_id_b = %s
            """,
            (source_id, source_id),
        )
        await self._conn.execute("DELETE FROM publications WHERE id = %s", (source_id,))

    # ── distinct_publications ──────────────────────────────────────

    async def mark_distinct(self, pub_id_a: int, pub_id_b: int) -> tuple[int, int] | None:
        if self._is_sa:
            result = await self._conn.execute(
                text("""
                    INSERT INTO distinct_publications (pub_id_a, pub_id_b)
                    VALUES (LEAST(:a, :b), GREATEST(:a, :b))
                    ON CONFLICT DO NOTHING
                    RETURNING pub_id_a, pub_id_b
                """),
                {"a": pub_id_a, "b": pub_id_b},
            )
            row = result.first()
            if not row:
                return None
            return row.pub_id_a, row.pub_id_b
        await self._conn.execute(
            """
            INSERT INTO distinct_publications (pub_id_a, pub_id_b)
            VALUES (LEAST(%s, %s), GREATEST(%s, %s))
            ON CONFLICT DO NOTHING
            RETURNING pub_id_a, pub_id_b
            """,
            (pub_id_a, pub_id_b, pub_id_a, pub_id_b),
        )
        row = await self._conn.fetchone()
        if not row:
            return None
        return row["pub_id_a"], row["pub_id_b"]


def _json_dumps_or_none(value: dict | None) -> str | None:
    """Sérialise un dict en string JSON pour `CAST(:p AS jsonb)`. None passé tel quel."""
    if value is None:
        return None
    import json

    return json.dumps(value)


async def _merge_into_sa(conn: AsyncConnection, target_id: int, source_id: int) -> None:
    """Branche SA de merge_into. Cross-aggregate (publications, authorships,
    source_publications, distinct_publications) — text() partout."""
    # 1. Transférer les source_publications
    await conn.execute(
        text("UPDATE source_publications SET publication_id = :t WHERE publication_id = :s"),
        {"t": target_id, "s": source_id},
    )

    # 2. Transférer les authorships vérité (dédup par person_id)
    await conn.execute(
        text("""
            DELETE FROM authorships
            WHERE publication_id = :s
              AND person_id IN (
                  SELECT person_id FROM authorships WHERE publication_id = :t
              )
        """),
        {"s": source_id, "t": target_id},
    )
    await conn.execute(
        text("UPDATE authorships SET publication_id = :t WHERE publication_id = :s"),
        {"t": target_id, "s": source_id},
    )

    # 3. Enrichir la cible avec les métadonnées de la source.
    result = await conn.execute(
        text("""
            SELECT doi, journal_id, CAST(oa_status AS text) AS oa_status,
                   language, container_title, countries
            FROM publications WHERE id = :id
        """),
        {"id": source_id},
    )
    src = result.one()
    await conn.execute(text("UPDATE publications SET doi = NULL WHERE id = :id"), {"id": source_id})
    await conn.execute(
        text(f"""
            UPDATE publications SET
                doi = COALESCE(doi, LOWER(:doi)),
                journal_id = COALESCE(journal_id, :jid),
                oa_status = CASE
                    WHEN :oa1 = 'diamond' THEN CAST('diamond' AS oa_type)
                    WHEN oa_status IN {OA_CLOSED_SQL}
                        AND :oa2 NOT IN {OA_CLOSED_SQL}
                    THEN CAST(:oa3 AS oa_type) ELSE oa_status END,
                language = COALESCE(language, :lang),
                container_title = COALESCE(container_title, :ct),
                countries = CASE
                    WHEN countries IS NULL THEN CAST(:c1 AS text[])
                    WHEN CAST(:c2 AS text[]) IS NULL THEN countries
                    ELSE (SELECT array_agg(DISTINCT c ORDER BY c)
                          FROM unnest(countries || CAST(:c3 AS text[])) AS c)
                    END,
                updated_at = now()
            WHERE id = :tid
        """),
        {
            "doi": src.doi,
            "jid": src.journal_id,
            "oa1": src.oa_status,
            "oa2": src.oa_status,
            "oa3": src.oa_status,
            "lang": src.language,
            "ct": src.container_title,
            "c1": src.countries,
            "c2": src.countries,
            "c3": src.countries,
            "tid": target_id,
        },
    )

    # 4. Nettoyer distinct_publications et supprimer la source
    await conn.execute(
        text("DELETE FROM distinct_publications WHERE pub_id_a = :s OR pub_id_b = :s"),
        {"s": source_id},
    )
    await conn.execute(text("DELETE FROM publications WHERE id = :s"), {"s": source_id})
