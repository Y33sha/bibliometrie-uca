"""Création et recalcul d'une publication depuis ses `source_publications`."""

import json
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.publications.aggregation import refresh_from_sources as _refresh_aggregate
from domain.publications.identifiers import DOI
from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT
from domain.publications.publication import Publication
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from domain.source_publications.metadata_correction.rules import (
    MetadataForCorrection,
    effective_doc_type_for_publication,
)
from domain.source_publications.metadata_correction.shared_doi import CONVERGENCE_CASES
from domain.source_publications.source_publication import SourcePublication
from domain.sources.registry import SOURCE_PRIORITY
from domain.types import JsonValue
from infrastructure.db.rows import rows_as
from infrastructure.db.scalars import scalar_int
from infrastructure.sql_fragments import corrected_by


class _SourcePublicationRow(NamedTuple):
    """Projection SQL `get_source_publications` : colonnes de `source_publications` consommées par l'agrégation canonique (`refresh_from_sources` côté domain)."""

    id: int
    source: str
    source_id: str
    title: str
    pub_year: int | None
    doc_type: str | None
    doi: str | None
    journal_id: int | None
    monograph_id: int | None
    container_title: str | None
    language: str | None
    oa_status: str | None
    is_retracted: bool | None
    abstract: str | None
    countries: list[str] | None
    urls: list[str] | None
    keywords: list[str] | None
    topics: dict[str, JsonValue] | None
    biblio: dict[str, JsonValue] | None
    meta: dict[str, JsonValue] | None
    license: str | None


def _source_publication_from_row(row: _SourcePublicationRow) -> SourcePublication:
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
        monograph_id=row.monograph_id,
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
        license=row.license,
    )


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
            unpaywall_checked_at=m["unpaywall_checked_at"],
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

    # ── Agrégation depuis source_publications ──────────────────────

    def get_source_publications(self, pub_id: int) -> list[SourcePublication]:
        # Le `doi` projeté est la colonne nue ; la substitution Zenodo (concept plutôt que version) est déjà persistée par `metadata_correction`.
        """Les `SourcePublication` attachées à une publication canonique, matière de l'agrégation canonique (`refresh_from_sources`)."""
        result = self._conn.execute(
            text("""
                SELECT sp.id, sp.source::text AS source, sp.source_id,
                       sp.title, sp.pub_year, sp.doc_type::text AS doc_type,
                       sp.doi,
                       sp.journal_id, sp.monograph_id, sp.container_title, sp.language,
                       sp.oa_status::text AS oa_status, sp.is_retracted, sp.abstract,
                       sp.countries, sp.urls, sp.keywords,
                       sp.topics, sp.biblio, sp.meta, sp.license::text AS license
                FROM source_publications sp
                WHERE sp.publication_id = :id
            """),
            {"id": pub_id},
        )
        return [_source_publication_from_row(vue) for vue in rows_as(_SourcePublicationRow, result)]

    def get_converged_secondary_ids(self, pub_id: int) -> frozenset[int]:
        """Ids des `source_publications` de `pub_id` dont le DOI a été substitué par une correction de convergence (forme secondaire : version, variante, pièce d'un dataset). L'agrégation les dépriorise pour que les scalaires descriptifs viennent de l'enregistrement canonique."""
        result = self._conn.execute(
            text(f"""
                SELECT id FROM source_publications
                WHERE publication_id = :id
                  AND {corrected_by("doi", "source_publications")} = ANY(:cases)
            """),
            {"id": pub_id, "cases": list(CONVERGENCE_CASES)},
        )
        return frozenset(row.id for row in result)

    def get_monograph_journal_ids(self, monograph_ids: Sequence[int]) -> dict[int, int | None]:
        """`journal_id` de chaque monographie : sa collection, pour l'agrégation dans `refresh_from_sources`."""
        rows = self._conn.execute(
            text("SELECT id, journal_id FROM monographs WHERE id = ANY(:ids)"),
            {"ids": list(monograph_ids)},
        )
        return {r.id: r.journal_id for r in rows}

    def get_journal_type(self, journal_id: int) -> str | None:
        """`journal_type` d'un journal, pour la re-correction canonique journal-dépendante dans `refresh_from_sources`. None si le journal n'existe pas ou son type n'est pas posé."""
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

    def delete(self, pub_id: int) -> None:
        """Supprime une publication. Le cascade DB nettoie `authorships` et `publication_subjects` ; `apc_payments` et `source_publications.publication_id` passent à NULL."""
        self._conn.execute(
            text("DELETE FROM publications WHERE id = :id"),
            {"id": pub_id},
        )


def _json_dumps_or_none(value: Mapping[str, JsonValue] | None) -> str | None:
    """Sérialise un dict en string JSON pour `CAST(:p AS jsonb)`. None passé tel quel."""
    if value is None:
        return None
    return json.dumps(value)


# ── Création ─────────────────────────────────────────────────────────────


def create_publication(
    *,
    title_normalized: str,
    doc_type: str | None,
    pub_year: int,
    doi: str | None,
    repo: PublicationStore,
) -> int:
    """Crée une publication semée sur le minimum requis par les colonnes NOT NULL, et retourne son id.

    Les valeurs de semis tiennent jusqu'au premier `refresh_from_sources`, qui pose les métadonnées définitives par agrégation une fois les `source_publications` rattachées : `title` reçoit le titre normalisé, `doc_type` vaut `other` quand la source n'en donne aucun, `oa_status` vaut la valeur par défaut, et les métadonnées de publication (journal, titre de conteneur, langue) restent nulles.
    """
    return repo.create(
        title=title_normalized,
        title_normalized=title_normalized,
        doc_type=doc_type or "other",
        pub_year=pub_year,
        doi=doi,
        oa_status=OA_STATUS_UNKNOWN_DEFAULT,
    )


# ── Recalcul complet des métadonnées depuis les source_publications ──────


def refresh_from_sources(
    pub_id: int,
    *,
    repo: PublicationStore,
) -> None:
    """Recalcule les métadonnées canoniques d'une publication depuis ses `source_publications`.

    Recalcul complet : lit toutes les sources attachées, agrège (`domain.publications.aggregation`), rejoue les corrections nées de l'arbitrage, persiste. Rattrape les métadonnées périmées (`ongoing_thesis` → `thesis` après soutenance).

    Deux cas de suppression : la publication sans source rattachée, qu'aucune source n'atteste ; et celle dont le `doc_type` résolu tombe dans `OUT_OF_SCOPE_DOC_TYPES` (invariant « hors périmètre = jamais matérialisé »). Le `delete` détache les `source_publications` (FK ON DELETE SET NULL) et emporte les `authorships` canoniques en cascade.

    Ne touche que la publication reçue et ses sources : quelles `source_publications` forment une même œuvre relève de la réconciliation (`pipeline/transformation/publications`). Laisse `notes` et `sources` inchangés (`update_sources` les pose).
    """
    pub = repo.find_by_id(pub_id)
    if pub is None:
        return

    sources = repo.get_source_publications(pub_id)
    if not sources:
        repo.delete(pub_id)
        return

    secondary_ids = repo.get_converged_secondary_ids(pub_id)
    # L'agrégation repart des colonnes déjà corrigées par la phase `metadata_correction`, pas du brut.
    monograph_ids = sorted({s.monograph_id for s in sources if s.monograph_id is not None})
    _refresh_aggregate(
        pub,
        sources,
        source_priority=SOURCE_PRIORITY,
        secondary_ids=secondary_ids,
        monograph_journals=repo.get_monograph_journal_ids(monograph_ids) if monograph_ids else {},
    )
    _apply_canonical_doc_type_correction(pub, repo=repo)

    if pub.doc_type in OUT_OF_SCOPE_DOC_TYPES:
        repo.delete(pub_id)
        return

    repo.save(pub)
    repo.update_sources(pub_id)


def _apply_canonical_doc_type_correction(pub: Publication, *, repo: PublicationStore) -> None:
    """Rejoue les corrections de `doc_type` sur la publication canonique après l'arbitrage.

    L'arbitrage prend chaque champ de la source la plus prioritaire qui le renseigne : la publication porte alors une combinaison — `doc_type` de l'une, `journal_id` de l'autre — qu'aucune `source_publication` ne portait, et qu'aucune correction par source n'a pu voir. Le contrat reçoit les champs que l'agrégation arbitre, dont le `journal_type` du `journal_id` canonique.

    `effective_doc_type_for_publication` écarte les règles lisant un fait propre à un enregistrement source ; les champs correspondants restent nuls ici. L'`oa_status` est hors du rejeu, en entrée comme en sortie — une source corrigée remonte d'elle-même par l'agrégation du statut le plus ouvert, et Unpaywall tranche après vérification.

    Mute `pub.doc_type` et trace la règle dans `pub.meta['corrections']['doc_type']`. Idempotent.
    """
    journal_type = repo.get_journal_type(pub.journal_id) if pub.journal_id is not None else None
    corrected = effective_doc_type_for_publication(
        MetadataForCorrection(
            title=pub.title,
            doc_type=pub.doc_type,
            doi=str(pub.doi) if pub.doi else None,
            journal_id=pub.journal_id,
            oa_status=None,
            urls=None,
            journal_type=journal_type,
            oa_model=None,
            embargo_expired=False,
            self_declared_preprint=False,
            declares_conference=False,
            registrant_publisher_type=None,
        )
    )
    if corrected is not None and corrected.value != pub.doc_type:
        pub.doc_type = corrected.value
        meta = dict(pub.meta or {})
        existing_corrections = meta.get("corrections")
        corrections = dict(existing_corrections) if isinstance(existing_corrections, dict) else {}
        corrections["doc_type"] = corrected.rule.value
        meta["corrections"] = corrections
        pub.meta = meta
