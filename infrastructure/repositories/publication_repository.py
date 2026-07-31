"""Adapter PostgreSQL pour la persistance des publications.

Isole le SQL de la couche application. Implémente le port `PublicationRepository` défini dans application/ports/repositories/.

Toutes les queries publications utilisent `text()` paramétré : trop intriquées en casts enum (oa_type, doc_type, source_type) et opérations array pour gagner à passer par MetaData.
"""

import json
from typing import Any, NamedTuple

from sqlalchemy import Connection, text

from application.ports.repositories.publication_repository import PublicationRepository
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from domain.source_publications.metadata_correction.shared_doi import CONVERGENCE_CASES
from domain.source_publications.source_publication import SourcePublication


class _SourcePublicationViewRow(NamedTuple):
    """Projection SQL `get_source_publications` : colonnes de `source_publications` consommées par l'agrégation canonique (`refresh_from_sources` côté domain)."""

    id: int
    source: str
    source_id: str
    title: str
    pub_year: int | None
    doc_type: str | None
    doi: str | None
    journal_id: int | None
    container_title: str | None
    language: str | None
    oa_status: str | None
    is_retracted: bool | None
    abstract: str | None
    countries: list[str] | None
    urls: list[str] | None
    keywords: list[str] | None
    topics: dict[str, Any] | None
    biblio: dict[str, Any] | None
    meta: dict[str, Any] | None


def _view_from_row(row: _SourcePublicationViewRow) -> SourcePublication:
    """Mapping d'une row SQL `source_publications` ⨝ `journals` vers la vue de lecture. Convertit les `text[]` Postgres en tuples immutables."""
    return SourcePublication(
        id=row.id,
        source=row.source,
        source_id=row.source_id,
        title=row.title,
        pub_year=row.pub_year,
        doc_type=row.doc_type,
        doi=row.doi,
        journal_id=row.journal_id,
        container_title=row.container_title,
        language=row.language,
        oa_status=row.oa_status,
        is_retracted=row.is_retracted,
        abstract=row.abstract,
        countries=tuple(row.countries or ()),
        urls=tuple(row.urls or ()),
        keywords=tuple(row.keywords or ()),
        topics=row.topics,
        biblio=row.biblio,
        meta=row.meta,
    )


class PgPublicationRepository(PublicationRepository):
    """Accès PostgreSQL à l'agrégat Publication via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Recherches ─────────────────────────────────────────────────

    def find_ids_by_journal_id(self, journal_id: int) -> list[int]:
        result = self._conn.execute(
            text("SELECT id FROM publications WHERE journal_id = :jid ORDER BY id"),
            {"jid": journal_id},
        )
        return [row.id for row in result]

    def find_doc_types_by_ids(self, pub_ids: list[int]) -> dict[int, str]:
        if not pub_ids:
            return {}
        result = self._conn.execute(
            text(
                "SELECT id, CAST(doc_type AS text) AS doc_type FROM publications WHERE id = ANY(:ids)"
            ),
            {"ids": pub_ids},
        )
        return {row.id: row.doc_type for row in result}

    # ── Chargement / persistance de l'aggregate Publication ────────

    def find_by_id(self, pub_id: int) -> Publication | None:
        row = self._conn.execute(
            text("""
                SELECT p.id, p.title, p.title_normalized,
                       CAST(p.doc_type AS text) AS doc_type,
                       p.pub_year, p.doi,
                       CAST(p.oa_status AS text) AS oa_status,
                       p.journal_id, p.container_title, p.language,
                       d.abstract, p.is_retracted, p.countries, d.keywords,
                       d.topics, d.biblio, p.meta, p.unpaywall_checked_at
                FROM publications p
                LEFT JOIN publications_detail d ON d.publication_id = p.id
                WHERE p.id = :id
            """),
            {"id": pub_id},
        ).first()
        if not row:
            return None
        m = row._mapping
        return Publication(
            id=m["id"],
            title=m["title"],
            pub_year=m["pub_year"],
            title_normalized=m["title_normalized"],
            doc_type=m["doc_type"],
            doi=DOI(m["doi"]) if m["doi"] else None,
            oa_status=m["oa_status"],
            journal_id=m["journal_id"],
            container_title=m["container_title"],
            language=m["language"],
            abstract=m["abstract"],
            is_retracted=m["is_retracted"],
            countries=tuple(m["countries"]) if m["countries"] else (),
            keywords=tuple(m["keywords"]) if m["keywords"] else (),
            topics=m["topics"],
            biblio=m["biblio"],
            meta=m["meta"],
            unpaywall_checked_at=m["unpaywall_checked_at"],
        )

    def save(self, pub: Publication) -> None:
        if pub.id is None:
            raise ValueError("save(pub) : pub.id doit être posé (utiliser create pour insérer)")
        self._conn.execute(
            text("""
                UPDATE publications SET
                    title = :title,
                    title_normalized = :tn,
                    doc_type = CAST(:dt AS doc_type),
                    doi = :doi,
                    oa_status = CAST(:oa AS oa_type),
                    journal_id = :jid,
                    container_title = :ct,
                    language = :lang,
                    is_retracted = :is_retracted,
                    countries = CAST(:countries AS text[]),
                    meta = CAST(:meta AS jsonb),
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "id": pub.id,
                "title": pub.title,
                "tn": pub.title_normalized,
                "dt": pub.doc_type,
                "doi": str(pub.doi) if pub.doi else None,
                "oa": pub.oa_status,
                "jid": pub.journal_id,
                "ct": pub.container_title,
                "lang": pub.language,
                "is_retracted": pub.is_retracted,
                "countries": list(pub.countries) if pub.countries else None,
                "meta": _json_dumps_or_none(pub.meta),
            },
        )
        # Colonnes grasses (abstract / keywords / topics / biblio) → table 1:1 publications_detail (upsert).
        self._conn.execute(
            text("""
                INSERT INTO publications_detail
                    (publication_id, abstract, keywords, topics, biblio)
                VALUES (:id, :abstract, CAST(:keywords AS text[]),
                        CAST(:topics AS jsonb), CAST(:biblio AS jsonb))
                ON CONFLICT (publication_id) DO UPDATE SET
                    abstract = EXCLUDED.abstract,
                    keywords = EXCLUDED.keywords,
                    topics = EXCLUDED.topics,
                    biblio = EXCLUDED.biblio
            """),
            {
                "id": pub.id,
                "abstract": pub.abstract,
                "keywords": list(pub.keywords) if pub.keywords else None,
                "topics": _json_dumps_or_none(pub.topics),
                "biblio": _json_dumps_or_none(pub.biblio),
            },
        )

    # ── Écritures simples ──────────────────────────────────────────

    def update_sources(self, pub_id: int) -> None:
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

    # ── Agrégation depuis source_publications ──────────────────────

    def get_source_publications(self, pub_id: int) -> list[SourcePublication]:
        # Le `doi` projeté est la colonne nue ; la substitution Zenodo (concept plutôt que version) est déjà persistée par `metadata_correction`.
        result = self._conn.execute(
            text("""
                SELECT sp.id, sp.source::text AS source, sp.source_id,
                       sp.title, sp.pub_year, sp.doc_type::text AS doc_type,
                       sp.doi,
                       sp.journal_id, sp.container_title, sp.language,
                       sp.oa_status::text AS oa_status, sp.is_retracted, sp.abstract,
                       sp.countries, sp.urls, sp.keywords,
                       sp.topics, sp.biblio, sp.meta
                FROM source_publications sp
                WHERE sp.publication_id = :id
            """),
            {"id": pub_id},
        )
        return [_view_from_row(_SourcePublicationViewRow(**row._mapping)) for row in result]

    def get_converged_secondary_ids(self, pub_id: int) -> frozenset[int]:
        result = self._conn.execute(
            text("""
                SELECT id FROM source_publications
                WHERE publication_id = :id
                  AND raw_metadata->'doi'->>'corrected_by' = ANY(:cases)
            """),
            {"id": pub_id, "cases": list(CONVERGENCE_CASES)},
        )
        return frozenset(row.id for row in result)

    def get_journal_type(self, journal_id: int) -> str | None:
        return self._conn.execute(
            text("SELECT journal_type::text FROM journals WHERE id = :id"),
            {"id": journal_id},
        ).scalar_one_or_none()

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
    ) -> int:
        return self._conn.execute(
            text("""
                INSERT INTO publications
                    (title, title_normalized, doc_type, pub_year, doi, oa_status)
                VALUES (:title, :tn, CAST(:doc_type AS doc_type), :py, :doi,
                        CAST(:oa AS oa_type))
                RETURNING id
            """),
            {
                "title": title,
                "tn": title_normalized,
                "doc_type": doc_type,
                "py": pub_year,
                "doi": doi,
                "oa": oa_status,
            },
        ).scalar_one()

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_into(self, target_id: int, source_id: int) -> None:
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

        # 3. Repointer distinct_publications de source vers target : pour chaque paire (source, autre), insérer (autre, target) réordonnée. On écarte l'auto-paire (autre = target) et on dédoublonne via ON CONFLICT, puis on supprime les paires de source.
        self._conn.execute(
            text("""
                INSERT INTO distinct_publications (pub_id_a, pub_id_b)
                SELECT LEAST(other_id, :t), GREATEST(other_id, :t)
                FROM (
                    SELECT CASE WHEN pub_id_a = :s THEN pub_id_b ELSE pub_id_a END AS other_id
                    FROM distinct_publications
                    WHERE pub_id_a = :s OR pub_id_b = :s
                ) AS pairs
                WHERE other_id <> :t
                ON CONFLICT (pub_id_a, pub_id_b) DO NOTHING
            """),
            {"t": target_id, "s": source_id},
        )
        self._conn.execute(
            text("DELETE FROM distinct_publications WHERE pub_id_a = :s OR pub_id_b = :s"),
            {"s": source_id},
        )

        # 4. Supprimer la source.
        self._conn.execute(text("DELETE FROM publications WHERE id = :s"), {"s": source_id})

    # ── Suppression ────────────────────────────────────────────────

    def delete(self, pub_id: int) -> None:
        self._conn.execute(
            text("DELETE FROM publications WHERE id = :id"),
            {"id": pub_id},
        )

    # ── distinct_publications ──────────────────────────────────────

    def mark_distinct(self, pub_id_a: int, pub_id_b: int) -> tuple[int, int] | None:
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
    return json.dumps(value)
