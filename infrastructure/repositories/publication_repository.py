"""Adapter PostgreSQL pour la persistance des publications.

Isole le SQL de la couche application. Implémente le port
`PublicationRepository` défini dans domain/ports/.

Mode dispatch (cur psycopg | Connection SA) pour cohabiter avec le
chantier sqlalchemy-core-adoption. La branche SA utilise `text()`
paramétré (les queries publications sont trop intriquées en casts
enum et opérations array pour gagner à passer par MetaData) ; la
branche psycopg conserve le code existant. Phase 4 supprimera la
branche psycopg.
"""

from typing import Any

from sqlalchemy import Connection, text

from domain.publication import (  # noqa: F401 — re-export pour compat
    PubByDoi,
    PubByNnt,
    PubByTitle,
    PubThesisCandidate,
)
from infrastructure.db.queries.filters import OA_CLOSED_SQL
from infrastructure.db_helpers import row_as
from infrastructure.db_helpers import row_val as _val


class PgPublicationRepository:
    """Accès PostgreSQL à l'agrégat Publication.

    Accepte un curseur psycopg ou une Connection SQLAlchemy.
    """

    def __init__(self, conn_or_cur: Any) -> None:
        self._conn = conn_or_cur
        self._is_sa = isinstance(conn_or_cur, Connection)

    # ── Recherches ─────────────────────────────────────────────────

    def find_by_doi(self, doi: str) -> PubByDoi | None:
        """Cherche une publication par DOI (case-insensitive)."""
        if not doi:
            return None
        if self._is_sa:
            result = self._conn.execute(
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
        with row_as(self._conn, PubByDoi) as cur:
            cur.execute(
                "SELECT id, doc_type, title_normalized FROM publications "
                "WHERE lower(doi) = lower(%s)",
                (doi,),
            )
            return cur.fetchone()

    def find_by_nnt(self, nnt: str) -> PubByNnt | None:
        """Cherche une publication via NNT stocké dans source_publications.external_ids."""
        if not nnt:
            return None
        if self._is_sa:
            result = self._conn.execute(
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
        with row_as(self._conn, PubByNnt) as cur:
            cur.execute(
                """
                SELECT p.id, p.doc_type, p.title_normalized
                FROM publications p
                JOIN source_publications sd ON sd.publication_id = p.id
                WHERE sd.external_ids->>'nnt' = %s
                LIMIT 1
                """,
                (nnt.upper(),),
            )
            return cur.fetchone()

    def find_by_title(
        self,
        title_normalized: str,
        pub_year: int,
        journal_id: int,
    ) -> PubByTitle | None:
        """Cherche une publication par titre normalisé + année + journal.
        Ne matche que les articles avec journal connu."""
        if not title_normalized or not journal_id:
            return None
        if self._is_sa:
            result = self._conn.execute(
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
        with row_as(self._conn, PubByTitle) as cur:
            cur.execute(
                """
                SELECT id, doi FROM publications
                WHERE title_normalized = %s AND pub_year = %s AND journal_id = %s
                LIMIT 1
                """,
                (title_normalized, pub_year, journal_id),
            )
            return cur.fetchone()

    def find_thesis_by_title(
        self,
        title_normalized: str,
        pub_year: int,
    ) -> list[PubThesisCandidate]:
        """Cherche des thèses par titre normalisé + année.

        Retourne les candidats pour déduplication thesis-specific
        (pas de journal_id, donc le tier 2 standard ne fonctionne pas).
        """
        if not title_normalized or not pub_year:
            return []
        if self._is_sa:
            result = self._conn.execute(
                text("""
                    SELECT id, doi FROM publications
                    WHERE title_normalized = :tn AND pub_year = :py
                      AND doc_type IN ('thesis', 'ongoing_thesis')
                    ORDER BY id
                """),
                {"tn": title_normalized, "py": pub_year},
            )
            return [PubThesisCandidate(id=row.id, doi=row.doi) for row in result]
        with row_as(self._conn, PubThesisCandidate) as cur:
            cur.execute(
                """
                SELECT id, doi FROM publications
                WHERE title_normalized = %s AND pub_year = %s
                  AND doc_type IN ('thesis', 'ongoing_thesis')
                ORDER BY id
                """,
                (title_normalized, pub_year),
            )
            return cur.fetchall()

    # ── Écritures simples ──────────────────────────────────────────

    def update_oa_status(self, pub_id: int, oa_status: str) -> None:
        """Met à jour le statut OA d'une publication."""
        if self._is_sa:
            self._conn.execute(
                text(
                    "UPDATE publications "
                    "SET oa_status = CAST(:os AS oa_type), updated_at = now() "
                    "WHERE id = :id"
                ),
                {"os": oa_status, "id": pub_id},
            )
            return
        self._conn.execute(
            """
            UPDATE publications SET oa_status = %s::oa_type, updated_at = now()
            WHERE id = %s
            """,
            (oa_status, pub_id),
        )

    def update_countries(self, pub_id: int, countries: list[str]) -> None:
        """Met à jour les pays d'une publication."""
        if self._is_sa:
            self._conn.execute(
                text("UPDATE publications SET countries = :c, updated_at = now() WHERE id = :id"),
                {"c": countries, "id": pub_id},
            )
            return
        self._conn.execute(
            """
            UPDATE publications SET countries = %s, updated_at = now()
            WHERE id = %s
            """,
            (countries, pub_id),
        )

    def update_sources(self, pub_id: int) -> None:
        """Recalcule publications.sources depuis source_publications.

        Pas de lecture préalable : agrégation SQL directe en une requête.
        """
        if self._is_sa:
            self._conn.execute(
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
        self._conn.execute(
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

    def get_doi(self, pub_id: int) -> str | None:
        """Retourne le DOI courant d'une publication, ou None."""
        if self._is_sa:
            result = self._conn.execute(
                text("SELECT doi FROM publications WHERE id = :id"), {"id": pub_id}
            )
            return result.scalar_one_or_none()
        self._conn.execute("SELECT doi FROM publications WHERE id = %s", (pub_id,))
        row = self._conn.fetchone()
        if row is None:
            return None
        return row["doi"] if isinstance(row, dict) else row[0]

    def set_doi(self, pub_id: int, doi: str) -> None:
        """Attribue un DOI à une publication (ne vérifie pas les conflits
        d'unicité — le caller doit l'avoir fait via find_by_doi)."""
        if self._is_sa:
            self._conn.execute(
                text("UPDATE publications SET doi = :doi, updated_at = now() WHERE id = :id"),
                {"doi": doi, "id": pub_id},
            )
            return
        self._conn.execute(
            "UPDATE publications SET doi = %s, updated_at = now() WHERE id = %s",
            (doi, pub_id),
        )

    def clear_doi(self, pub_id: int) -> None:
        """Retire le DOI d'une publication (utilisé lors des conflits
        chapitre/ouvrage)."""
        if self._is_sa:
            self._conn.execute(
                text("UPDATE publications SET doi = NULL, updated_at = now() WHERE id = :id"),
                {"id": pub_id},
            )
            return
        self._conn.execute(
            "UPDATE publications SET doi = NULL, updated_at = now() WHERE id = %s",
            (pub_id,),
        )

    # ── Agrégation depuis source_publications ──────────────────────

    def get_source_rows(self, pub_id: int) -> list[dict]:
        """Retourne toutes les lignes source_publications attachées à
        une publication, avec les champs nécessaires au recalcul
        d'agrégation (refresh_from_sources).

        Branche psycopg : ouvre un cursor dict_row interne pour garantir
        l'accès par nom quel que soit le row_factory du caller.
        """
        if self._is_sa:
            result = self._conn.execute(
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

        dict_cur = self._conn.connection.cursor(row_factory=dict_row)
        try:
            dict_cur.execute(
                """
                SELECT source, doi, doc_type, pub_year, journal_id, oa_status,
                       container_title, language, abstract, keywords, countries,
                       topics, biblio, meta, is_retracted, external_ids
                FROM source_publications
                WHERE publication_id = %s
                """,
                (pub_id,),
            )
            return dict_cur.fetchall()
        finally:
            dict_cur.close()

    def update_aggregated(
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
        """Écrit les valeurs agrégées sur une publication.

        Appelé par refresh_from_sources après calcul des valeurs
        fusionnées. Le caller garde la responsabilité d'appeler
        ensuite `update_sources` pour le tableau `sources`.
        """
        if self._is_sa:
            self._conn.execute(
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

        self._conn.execute(
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

    def create(
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
        """Insère une publication et retourne son id.

        Le caller est responsable du tier de déduplication avant
        d'appeler `create` — le repo ne fait que le INSERT brut.
        """
        if self._is_sa:
            result = self._conn.execute(
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
        self._conn.execute(
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
        return _val(self._conn.fetchone(), 0)

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_into(self, target_id: int, source_id: int) -> None:
        """Fusionne la publication `source_id` dans `target_id`.

        Séquence en 5 étapes, toute la logique SQL ici (une seule
        transaction) :
        1. Transfert des source_publications
        2. Transfert des authorships vérité (dédup par person_id)
        3. Enrichissement des métadonnées de la cible depuis la source
           (en respectant les contraintes d'unicité sur doi, la règle
           OA 'diamond gagne toujours', et la fusion de countries)
        4. Nettoyage de distinct_publications
        5. Suppression de la publication source

        Le caller garde la responsabilité d'appeler update_sources
        après, et d'émettre l'événement d'audit.
        """
        if self._is_sa:
            _merge_into_sa(self._conn, target_id, source_id)
            return

        # 1. Transférer les source_publications
        self._conn.execute(
            "UPDATE source_publications SET publication_id = %s WHERE publication_id = %s",
            (target_id, source_id),
        )

        # 2. Transférer les authorships vérité (dédup par person_id)
        self._conn.execute(
            """
            DELETE FROM authorships
            WHERE publication_id = %s
              AND person_id IN (
                  SELECT person_id FROM authorships WHERE publication_id = %s
              )
            """,
            (source_id, target_id),
        )
        self._conn.execute(
            "UPDATE authorships SET publication_id = %s WHERE publication_id = %s",
            (target_id, source_id),
        )

        # 3. Enrichir la cible avec les métadonnées de la source.
        # Ordre : capturer les valeurs src → NULL-er doi src (libère
        # la contrainte UNIQUE lower(doi)) → enrichir target.
        # Cursor dict_row interne : `self._conn` peut être tuple_row
        # (ex: normalize_hal/wos avec USE_DICT_CURSOR=False) — on garantit
        # ici l'accès par nom de colonne.
        from psycopg.rows import dict_row

        dict_cur = self._conn.connection.cursor(row_factory=dict_row)
        try:
            dict_cur.execute(
                """
                SELECT doi, journal_id, oa_status::text AS oa_status,
                       language, container_title, countries
                FROM publications WHERE id = %s
                """,
                (source_id,),
            )
            src = dict_cur.fetchone()
        finally:
            dict_cur.close()
        self._conn.execute("UPDATE publications SET doi = NULL WHERE id = %s", (source_id,))
        self._conn.execute(
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
        self._conn.execute(
            """
            DELETE FROM distinct_publications
            WHERE pub_id_a = %s OR pub_id_b = %s
            """,
            (source_id, source_id),
        )
        self._conn.execute("DELETE FROM publications WHERE id = %s", (source_id,))

    # ── distinct_publications ──────────────────────────────────────

    def mark_distinct(self, pub_id_a: int, pub_id_b: int) -> tuple[int, int] | None:
        """Marque deux publications comme distinctes. Idempotent.

        Retourne (a, b) si la paire vient d'être insérée, None sinon —
        le caller décide s'il émet un audit ou pas.
        """
        if self._is_sa:
            result = self._conn.execute(
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
        self._conn.execute(
            """
            INSERT INTO distinct_publications (pub_id_a, pub_id_b)
            VALUES (LEAST(%s, %s), GREATEST(%s, %s))
            ON CONFLICT DO NOTHING
            RETURNING pub_id_a, pub_id_b
            """,
            (pub_id_a, pub_id_b, pub_id_a, pub_id_b),
        )
        row = self._conn.fetchone()
        if not row:
            return None
        return row["pub_id_a"], row["pub_id_b"]


def _json_dumps_or_none(value: dict | None) -> str | None:
    """Sérialise un dict en string JSON pour `CAST(:p AS jsonb)`. None passé tel quel."""
    if value is None:
        return None
    import json

    return json.dumps(value)


def _merge_into_sa(conn: Connection, target_id: int, source_id: int) -> None:
    """Branche SA de merge_into. Cross-aggregate (publications, authorships,
    source_publications, distinct_publications) — text() partout."""
    # 1. Transférer les source_publications
    conn.execute(
        text("UPDATE source_publications SET publication_id = :t WHERE publication_id = :s"),
        {"t": target_id, "s": source_id},
    )

    # 2. Transférer les authorships vérité (dédup par person_id)
    conn.execute(
        text("""
            DELETE FROM authorships
            WHERE publication_id = :s
              AND person_id IN (
                  SELECT person_id FROM authorships WHERE publication_id = :t
              )
        """),
        {"s": source_id, "t": target_id},
    )
    conn.execute(
        text("UPDATE authorships SET publication_id = :t WHERE publication_id = :s"),
        {"t": target_id, "s": source_id},
    )

    # 3. Enrichir la cible avec les métadonnées de la source.
    result = conn.execute(
        text("""
            SELECT doi, journal_id, CAST(oa_status AS text) AS oa_status,
                   language, container_title, countries
            FROM publications WHERE id = :id
        """),
        {"id": source_id},
    )
    src = result.one()
    conn.execute(text("UPDATE publications SET doi = NULL WHERE id = :id"), {"id": source_id})
    conn.execute(
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
    conn.execute(
        text("DELETE FROM distinct_publications WHERE pub_id_a = :s OR pub_id_b = :s"),
        {"s": source_id},
    )
    conn.execute(text("DELETE FROM publications WHERE id = :s"), {"s": source_id})
