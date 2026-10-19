"""Persistance d'une publication : lecture, enregistrement, création, suppression."""

import json
from collections.abc import Mapping

from sqlalchemy import Connection, text

from domain.merge import MergedEntity
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from domain.types import JsonValue
from infrastructure.db.scalars import scalar_int
from infrastructure.repositories.merge_steps import record_redirect


class PublicationStore:
    """Accès PostgreSQL à l'agrégat Publication via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Recherches ─────────────────────────────────────────────────

    def find_ids_by_journal_id(self, journal_id: int) -> list[int]:
        """Ids des publications rattachées à ce journal. Utilisé pour requalifier le stock quand un input éditable du journal (ex. `journal_type`) change."""
        result = self._conn.execute(
            text("SELECT id FROM publications WHERE journal_id = :jid ORDER BY id"),
            {"jid": journal_id},
        )
        return [row.id for row in result]

    def find_doc_types_by_ids(self, pub_ids: list[int]) -> dict[int, str]:
        """`doc_type` de chaque publication demandée, en une lecture. Une publication absente de la table manque de la réponse — un refresh peut l'avoir supprimée."""
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
        """Hydrate l'agrégat `Publication` depuis `publications` (attributs canoniques), ou `None` si absente. Les authorships ne sont pas chargées ici (projection lecture séparée au besoin)."""
        row = self._conn.execute(
            text("""
                SELECT p.id, p.title, p.title_normalized,
                       CAST(p.doc_type AS text) AS doc_type,
                       p.pub_year, p.doi,
                       CAST(p.oa_status AS text) AS oa_status,
                       CAST(p.license AS text) AS license,
                       CAST(p.deposit_license AS text) AS deposit_license,
                       p.journal_id, p.monograph_id, p.container_title, p.language,
                       d.abstract, p.is_retracted, p.countries, d.keywords,
                       d.topics, d.biblio, p.meta
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
            license=m["license"],
            deposit_license=m["deposit_license"],
            journal_id=m["journal_id"],
            monograph_id=m["monograph_id"],
            container_title=m["container_title"],
            language=m["language"],
            abstract=m["abstract"],
            is_retracted=m["is_retracted"],
            countries=tuple(m["countries"]) if m["countries"] else (),
            keywords=tuple(m["keywords"]) if m["keywords"] else (),
            topics=m["topics"],
            biblio=m["biblio"],
            meta=m["meta"],
        )

    def save(self, pub: Publication) -> None:
        """Persiste l'état mutable de l'agrégat `Publication` (tous les champs éditables ; `pub_year` reste immuable après création). Requiert `pub.id` posé."""
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
                    license = CAST(:license AS license_type),
                    deposit_license = CAST(:deposit_license AS license_type),
                    journal_id = :jid,
                    monograph_id = :mid,
                    container_title = :ct,
                    language = :lang,
                    is_retracted = :is_retracted,
                    countries = CAST(:countries AS text[]),
                    meta = CAST(:meta AS jsonb),
                    -- Sources recalculées : la phase subjects ingère de nouveau la publication.
                    subjects_ingested_at = NULL,
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
                "license": pub.license,
                "deposit_license": pub.deposit_license,
                "jid": pub.journal_id,
                "mid": pub.monograph_id,
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
        """Recalcule `publications.sources` par agrégation des `source_publications` rattachées."""
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
        """Insère une publication (INSERT brut, la déduplication relève du caller) et retourne son `id`. Les colonnes hors NOT NULL et DOI prennent leur défaut ; `save` les pose."""
        return scalar_int(
            self._conn.execute(
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
            )
        )

    # ── Suppression ────────────────────────────────────────────────

    def has_source_publications(self, pub_id: int) -> bool:
        """Vrai si au moins une `source_publication` est rattachée à la publication."""
        return bool(
            self._conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM source_publications WHERE publication_id = :id)"
                ),
                {"id": pub_id},
            ).scalar_one()
        )

    def repoint_dependents(self, from_publication_id: int, to_publication_id: int) -> None:
        """Re-pointe les paiements APC (`apc_payments`) de `from_publication_id` vers `to_publication_id`, et enregistre la redirection de son identifiant."""
        self._conn.execute(
            text("UPDATE apc_payments SET publication_id = :t WHERE publication_id = :s"),
            {"s": from_publication_id, "t": to_publication_id},
        )
        record_redirect(
            self._conn, MergedEntity.PUBLICATION, to_publication_id, from_publication_id
        )

    def delete(self, pub_id: int) -> None:
        """Supprime une publication. Le cascade DB nettoie `authorships` et `publication_subjects` ; `apc_payments` et `source_publications.publication_id` passent à NULL. Appelée par le module du cycle de vie (`pipeline.transformation.publications.lifecycle`)."""
        self._conn.execute(
            text("DELETE FROM publications WHERE id = :id"),
            {"id": pub_id},
        )


def _json_dumps_or_none(value: Mapping[str, JsonValue] | None) -> str | None:
    """Sérialise un dict en string JSON pour `CAST(:p AS jsonb)`. None passé tel quel."""
    if value is None:
        return None
    return json.dumps(value)
