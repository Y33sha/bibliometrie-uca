"""Adapter PostgreSQL pour la persistance des publications.

Isole le SQL de la couche application. Implémente le port
`PublicationRepository` défini dans domain/ports/.

Toutes les queries publications utilisent `text()` paramétré : trop
intriquées en casts enum (oa_type, doc_type, source_type) et opérations
array pour gagner à passer par MetaData.
"""

from sqlalchemy import Connection, text

from domain.publication import (  # noqa: F401 — re-export pour compat
    PubByDoi,
    PubByNnt,
    PubByTitle,
    PubThesisCandidate,
)
from infrastructure.db.queries.filters import OA_CLOSED_SQL


class PgPublicationRepository:
    """Accès PostgreSQL à l'agrégat Publication via une `Connection` SA."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Recherches ─────────────────────────────────────────────────

    def find_by_doi(self, doi: str) -> PubByDoi | None:
        """Cherche une publication par DOI (case-insensitive)."""
        if not doi:
            return None
        row = self._conn.execute(
            text(
                "SELECT id, CAST(doc_type AS text) AS doc_type, title_normalized "
                "FROM publications WHERE lower(doi) = lower(:doi)"
            ),
            {"doi": doi},
        ).first()
        if not row:
            return None
        return PubByDoi(id=row.id, doc_type=row.doc_type, title_normalized=row.title_normalized)

    def find_by_nnt(self, nnt: str) -> PubByNnt | None:
        """Cherche une publication via NNT stocké dans source_publications.external_ids."""
        if not nnt:
            return None
        row = self._conn.execute(
            text("""
                SELECT p.id, CAST(p.doc_type AS text) AS doc_type, p.title_normalized
                FROM publications p
                JOIN source_publications sd ON sd.publication_id = p.id
                WHERE sd.external_ids->>'nnt' = :nnt
                LIMIT 1
            """),
            {"nnt": nnt.upper()},
        ).first()
        if not row:
            return None
        return PubByNnt(id=row.id, doc_type=row.doc_type, title_normalized=row.title_normalized)

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
        row = self._conn.execute(
            text("""
                SELECT id, doi FROM publications
                WHERE title_normalized = :tn AND pub_year = :py AND journal_id = :jid
                LIMIT 1
            """),
            {"tn": title_normalized, "py": pub_year, "jid": journal_id},
        ).first()
        if not row:
            return None
        return PubByTitle(id=row.id, doi=row.doi)

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

    # ── Écritures simples ──────────────────────────────────────────

    def update_oa_status(self, pub_id: int, oa_status: str) -> None:
        """Met à jour le statut OA d'une publication."""
        self._conn.execute(
            text(
                "UPDATE publications "
                "SET oa_status = CAST(:os AS oa_type), updated_at = now() "
                "WHERE id = :id"
            ),
            {"os": oa_status, "id": pub_id},
        )

    def update_countries(self, pub_id: int, countries: list[str]) -> None:
        """Met à jour les pays d'une publication."""
        self._conn.execute(
            text("UPDATE publications SET countries = :c, updated_at = now() WHERE id = :id"),
            {"c": countries, "id": pub_id},
        )

    def update_sources(self, pub_id: int) -> None:
        """Recalcule publications.sources depuis source_publications.

        Pas de lecture préalable : agrégation SQL directe en une requête.
        """
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

    # ── Accès bas niveau au champ doi ──────────────────────────────

    def get_doi(self, pub_id: int) -> str | None:
        """Retourne le DOI courant d'une publication, ou None."""
        return self._conn.execute(
            text("SELECT doi FROM publications WHERE id = :id"), {"id": pub_id}
        ).scalar_one_or_none()

    def set_doi(self, pub_id: int, doi: str) -> None:
        """Attribue un DOI à une publication (ne vérifie pas les conflits
        d'unicité — le caller doit l'avoir fait via find_by_doi)."""
        self._conn.execute(
            text("UPDATE publications SET doi = :doi, updated_at = now() WHERE id = :id"),
            {"doi": doi, "id": pub_id},
        )

    def clear_doi(self, pub_id: int) -> None:
        """Retire le DOI d'une publication (utilisé lors des conflits
        chapitre/ouvrage)."""
        self._conn.execute(
            text("UPDATE publications SET doi = NULL, updated_at = now() WHERE id = :id"),
            {"id": pub_id},
        )

    # ── Agrégation depuis source_publications ──────────────────────

    def get_source_rows(self, pub_id: int) -> list[dict]:
        """Retourne toutes les lignes source_publications attachées à
        une publication, avec les champs nécessaires au recalcul
        d'agrégation (refresh_from_sources).
        """
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
        return self._conn.execute(
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
        ).scalar_one()

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
        # 1. Transférer les source_publications
        self._conn.execute(
            text("UPDATE source_publications SET publication_id = :t WHERE publication_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # 2. Transférer les authorships vérité (dédup par person_id)
        self._conn.execute(
            text("""
                DELETE FROM authorships
                WHERE publication_id = :s
                  AND person_id IN (
                      SELECT person_id FROM authorships WHERE publication_id = :t
                  )
            """),
            {"s": source_id, "t": target_id},
        )
        self._conn.execute(
            text("UPDATE authorships SET publication_id = :t WHERE publication_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # 3. Enrichir la cible avec les métadonnées de la source.
        # Ordre : capturer les valeurs src → NULL-er doi src (libère
        # la contrainte UNIQUE lower(doi)) → enrichir target.
        src = self._conn.execute(
            text("""
                SELECT doi, journal_id, CAST(oa_status AS text) AS oa_status,
                       language, container_title, countries
                FROM publications WHERE id = :id
            """),
            {"id": source_id},
        ).one()
        self._conn.execute(
            text("UPDATE publications SET doi = NULL WHERE id = :id"), {"id": source_id}
        )
        self._conn.execute(
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
        self._conn.execute(
            text("DELETE FROM distinct_publications WHERE pub_id_a = :s OR pub_id_b = :s"),
            {"s": source_id},
        )
        self._conn.execute(text("DELETE FROM publications WHERE id = :s"), {"s": source_id})

    # ── distinct_publications ──────────────────────────────────────

    def mark_distinct(self, pub_id_a: int, pub_id_b: int) -> tuple[int, int] | None:
        """Marque deux publications comme distinctes. Idempotent.

        Retourne (a, b) si la paire vient d'être insérée, None sinon —
        le caller décide s'il émet un audit ou pas.
        """
        row = self._conn.execute(
            text("""
                INSERT INTO distinct_publications (pub_id_a, pub_id_b)
                VALUES (LEAST(:a, :b), GREATEST(:a, :b))
                ON CONFLICT DO NOTHING
                RETURNING pub_id_a, pub_id_b
            """),
            {"a": pub_id_a, "b": pub_id_b},
        ).first()
        if not row:
            return None
        return row.pub_id_a, row.pub_id_b


def _json_dumps_or_none(value: dict | None) -> str | None:
    """Sérialise un dict en string JSON pour `CAST(:p AS jsonb)`. None passé tel quel."""
    if value is None:
        return None
    import json

    return json.dumps(value)
