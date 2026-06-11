"""
Crée une publication canonique par `source_publication` orphelin, puis rafraîchit les publications dont au moins un source a été modifié.

Phase du pipeline qui s'exécute APRÈS affiliations (in_perimeter déterminé sur les source_authorships) et AVANT persons/authorships.

Modèle création⇒fusion :
1. Pour chaque `source_publication` sans `publication_id` (tous périmètres confondus) : création d'une publication, `effective_metadata` appliquant les corrections (doc_type, journal, oa_status). Pas de matching ni de gate périmètre — le dédoublonnage est délégué aux passes de fusion qui suivent (par identifiant : DOI/hal_id/NNT/PMID ; par métadonnées : thèse/proceedings).
2. Pour chaque publication stale (au moins un `source_publication.updated_at > publications.updated_at`) : `refresh_from_sources` pour ré-agréger les méta canoniques (dont DOI promu par priorité de source).

L'orchestrateur dépend du port `PublicationsCreateQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/create_publications.py`.
"""

import logging
from typing import Literal

from sqlalchemy import Connection

from application.ports.pipeline.publications_create import (
    PublicationsCreateQueries,
    SourcePublicationRow,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.publications import refresh_from_sources
from domain.normalize import normalize_text
from domain.publications.correction import effective_metadata
from domain.publications.doc_types import map_doc_type
from domain.publications.metadata import (
    OA_STATUS_UNKNOWN_DEFAULT,
    clean_publication_title,
    has_minimal_publication_metadata,
)
from domain.source_publications.views import SourcePublicationWithJournalView

Outcome = Literal["created", "skipped_no_metadata"]


def _view_from_row(doc: SourcePublicationRow) -> SourcePublicationWithJournalView:
    """Construit une `SourcePublicationWithJournalView` à partir d'une `SourcePublicationRow` pour passer à `effective_metadata`. La vue n'est jamais persistée ; elle sert d'input à la cascade de corrections à la création.

    Les champs joints depuis `journals` (`journal_type`, `oa_model`, `apc_amount`) sont laissés à `None` : la projection `SourcePublicationRow` ne JOINe pas `journals`. Conséquence : à la création, seules les règles SP-intrinsèques (URL theses.fr/dumas) peuvent firer ; les règles journal-dépendantes (`media`, …) s'appliquent au refresh post-création, où la vue est correctement enrichie (cf. `get_source_publications` côté repo).
    """
    return SourcePublicationWithJournalView(
        id=doc.id,
        source=doc.source,
        source_id=doc.source_id,
        title=doc.title or "",
        pub_year=doc.pub_year,
        doc_type=doc.doc_type,
        doi=doc.doi,
        journal_id=doc.journal_id,
        container_title=doc.container_title,
        language=doc.language,
        oa_status=doc.oa_status,
        is_retracted=None,
        abstract=None,
        countries=(),
        keywords=(),
        urls=tuple(doc.urls or ()),
        topics=None,
        biblio=None,
        meta=None,
        journal_type=None,
        oa_model=None,
        apc_amount=None,
    )


def extract_known_identifiers(external_ids: dict[str, object] | None) -> dict[str, str]:
    """Filtre `external_ids` aux valeurs `str` non vides.

    Convention : toutes les clés de dédup cross-source (`hal_id`, `nnt`, `pmid`, …) vivent dans `external_ids`, y compris quand elles coïncident avec `source_id` (cas HAL : le normalizer pose `external_ids.hal_id = [source_id]` — liste, cf. theses pour NNT). Pas de fallback sur `source_id` — la responsabilité est portée par les normalizers à l'écriture.
    """
    if not isinstance(external_ids, dict):
        return {}
    return {k: v for k, v in external_ids.items() if isinstance(v, str) and v}


def process_document(
    conn: Connection,
    queries: PublicationsCreateQueries,
    doc: SourcePublicationRow,
    dry_run: bool,
    *,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> Outcome:
    """Crée une publication canonique pour un `source_publication` orphelin.

    Modèle création⇒fusion : pas de matching ni de gate périmètre. `effective_metadata` applique les corrections (doc_type, journal, oa_status) avant écriture ; le DOI effectif Zenodo (concept DOI résolu en amont) prime sur le DOI version. Le dédoublonnage est assuré en aval par les passes de fusion.

    En dry_run, rien n'est écrit — le doc est compté comme "à créer".
    """
    title = doc.title or ""
    pub_year = doc.pub_year
    if not has_minimal_publication_metadata(title, pub_year):
        return "skipped_no_metadata"
    assert pub_year is not None  # garanti par has_minimal_publication_metadata (truthy check)

    if dry_run:
        return "created"

    doi = doc.doi
    raw_doc_type = doc.doc_type
    journal_id = doc.journal_id
    raw_oa_status = doc.oa_status

    # Corrections appliquées à la SP entrante avant écriture (cf. domain/publications/correction.py).
    corrected = effective_metadata(_view_from_row(doc))
    if corrected.doc_type is not None:
        raw_doc_type = corrected.doc_type.value
    if corrected.journal_id is not None:
        journal_id = corrected.journal_id.value
    if corrected.oa_status is not None:
        raw_oa_status = corrected.oa_status.value

    doc_type = map_doc_type(raw_doc_type, doc.source) or "other"
    oa_status = raw_oa_status or OA_STATUS_UNKNOWN_DEFAULT

    # Décodage HTML double-encodage du titre (OpenAlex / ScanR) avant écriture.
    cleaned_title = clean_publication_title(title) or ""
    if cleaned_title != title:
        title = cleaned_title
    title_normalized = normalize_text(title)

    # Pour les œuvres Zenodo, le DOI canonique est le concept DOI (résolu en
    # amont par `resolve_zenodo_concept`) : concept + versions partagent ce DOI
    # effectif et convergent vers une publication unique via la fusion par DOI.
    known_ids = extract_known_identifiers(doc.external_ids)
    zenodo_concept_doi = known_ids.get("zenodo_concept_doi")
    if zenodo_concept_doi:
        doi = zenodo_concept_doi

    publication_id = pub_repo.create(
        title=title,
        title_normalized=title_normalized,
        doc_type=doc_type,
        pub_year=pub_year,
        doi=doi,
        oa_status=oa_status,
        journal_id=journal_id,
        container_title=doc.container_title,
        language=doc.language,
    )
    queries.link_source_publication_to_publication(conn, doc.id, publication_id)
    refresh_from_sources(publication_id, repo=pub_repo, audit_repo=audit_repo)

    return "created"


def run(
    conn: Connection,
    queries: PublicationsCreateQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
    dry_run: bool = False,
) -> None:
    try:
        # ── Création : 1 publication par orphelin ──
        docs = queries.fetch_orphan_source_publications(conn)
        logger.info("Création : %d source_publications orphelins", len(docs))

        counts: dict[Outcome, int] = {"created": 0, "skipped_no_metadata": 0}
        for i, doc in enumerate(docs):
            outcome = process_document(
                conn, queries, doc, dry_run, pub_repo=pub_repo, audit_repo=audit_repo
            )
            counts[outcome] += 1

            if (i + 1) % 500 == 0:
                if not dry_run:
                    conn.commit()
                logger.info("  Création : %d/%d traités...", i + 1, len(docs))

        if not dry_run:
            conn.commit()
        logger.info(
            "Création terminée : %d créées, %d sans métadonnées",
            counts["created"],
            counts["skipped_no_metadata"],
        )

        # ── Refresh des publications stale ──
        # Au moins un source_publication modifié depuis le dernier refresh
        # canonique (couvre les re-traitements des normalizers + les créations
        # ci-dessus). Le dédoublonnage est porté par les passes de fusion qui
        # suivent cette phase dans le pipeline.
        stale_ids = queries.fetch_stale_publication_ids(conn)
        logger.info("%d publications stale à rafraîchir", len(stale_ids))
        refreshed = 0
        for i, pub_id in enumerate(stale_ids):
            try:
                refresh_from_sources(pub_id, repo=pub_repo, audit_repo=audit_repo)
            except Exception:
                logger.exception("  refresh_from_sources crash sur pub_id=%d", pub_id)
                raise
            refreshed += 1
            if (i + 1) % 500 == 0:
                if not dry_run:
                    conn.commit()
                logger.info("  %d/%d rafraîchis...", i + 1, len(stale_ids))

        if dry_run:
            logger.info(
                "DRY-RUN : %d à créer (approx.), %d sans métadonnées, %d à rafraîchir",
                counts["created"],
                counts["skipped_no_metadata"],
                refreshed,
            )
            conn.rollback()
        else:
            conn.commit()
            logger.info("Terminé : %d publications rafraîchies", refreshed)

    except Exception:
        conn.rollback()
        logger.exception("Erreur")
        raise
