"""
Matche ou crée les publications canoniques pour les `source_publications` non rattachés, puis rafraîchit les publications dont au moins un source a été modifié.

Phase du pipeline qui s'exécute APRÈS affiliations (quand in_perimeter est déterminé sur les source_authorships) et AVANT persons/authorships.

Deux passes :
1. Pour chaque `source_publication` sans `publication_id` (tous périmètres confondus) : cascade de matching cross-source (`decide_publication_match` sur DOI, NNT, HAL_ID, THESIS_TITLE_YEAR). Si match : rattache, quel que soit le périmètre — c'est ce qui permet de résoudre les conflits inter-sources (ex. version HAL hors-UCA + version OpenAlex UCA → rattachement à la même publication canonique). Sinon : crée la publication, mais uniquement si `allow_create` (dérivé de la colonne `in_perimeter`) est vrai — sans authorship in_perimeter, on ne fait pas entrer une nouvelle publication dans le périmètre.
2. Pour chaque publication stale (au moins un `source_publication.updated_at > publications.updated_at`) : `refresh_from_sources` pour ré-agréger les méta canoniques (dont DOI promu par priorité de source).

L'orchestrateur dépend du port `PublicationsMatchOrCreateQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/match_or_create_publications.py`.
"""

import logging
import time
from typing import Literal

from sqlalchemy import Connection

from application.pipeline.publications.metadata_deduplication_rules import (
    match_proceedings_by_title_year_authorcount,
    match_thesis_by_title_year,
)
from application.ports.pipeline.publications_match_or_create import (
    PublicationsMatchOrCreateQueries,
    SourcePublicationRow,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.publications import (
    refresh_from_sources,
    resolve_doi_conflict,
)
from domain.normalize import normalize_text
from domain.publications.correction import effective_metadata
from domain.publications.deduplication import (
    MetadataDeduplicationCase,
    decide_publication_match,
)
from domain.publications.doc_types import map_doc_type
from domain.publications.identifiers import normalize_nnt
from domain.publications.metadata import (
    OA_STATUS_UNKNOWN_DEFAULT,
    clean_publication_title,
    has_minimal_publication_metadata,
)
from domain.source_publications.views import SourcePublicationWithJournalView

Outcome = Literal["created", "linked", "skipped_no_metadata", "skipped_no_perimeter"]


def _view_from_row(doc: SourcePublicationRow) -> SourcePublicationWithJournalView:
    """Construit une `SourcePublicationWithJournalView` à partir d'une `SourcePublicationRow` pour passer à `effective_metadata`. La vue n'est jamais persistée ; elle sert d'input à la cascade de corrections à l'entrée match_or_create.

    Les champs joints depuis `journals` (`journal_type`, `oa_model`, `apc_amount`) sont laissés à `None` : la projection `SourcePublicationRow` ne JOINe pas `journals` aujourd'hui. Conséquence : à l'entrée match_or_create, seules les règles SP-intrinsèques (URL theses.fr/dumas) peuvent firer ; les règles journal-dépendantes (`media`, …) s'appliqueront au refresh post-création où la vue est correctement enrichie (cf. `get_source_publications` côté repo).

    # TODO: quand une règle journal-dépendante produira un `doc_type` routé par la dédup (`thesis`/`proceedings`), JOINer `journals` dans `fetch_orphan_in_perimeter_source_publications` et alimenter les champs ici — sinon la dédup-entrée passera à côté.
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

    Convention : toutes les clés de dédup cross-source (`hal_id`, `nnt`, `pmid`, …) vivent dans `external_ids`, y compris quand elles coïncident avec `source_id` (cas HAL : le normalizer pose `external_ids.hal_id = source_id`, cf. theses pour NNT). Pas de fallback sur `source_id` — la responsabilité est portée par les normalizers à l'écriture.
    """
    if not isinstance(external_ids, dict):
        return {}
    return {k: v for k, v in external_ids.items() if isinstance(v, str) and v}


def process_document(
    conn: Connection,
    queries: PublicationsMatchOrCreateQueries,
    doc: SourcePublicationRow,
    dry_run: bool,
    *,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> Outcome:
    """Crée, rattache ou ignore une publication pour un `source_publication` orphelin.

    Pattern prefetch → décideur → dispatch : extrait les identifiants candidats, les confronte aux index existants, puis délègue le choix `match`/`create` à `decide_publication_match`. La création est gated par `allow_create = doc.in_perimeter` : un orphelin hors-périmètre peut être rattaché à une publication canonique existante (résolution des conflits inter-sources), mais ne peut pas en créer une nouvelle.

    En dry_run, la cascade de matching (avec son effet de bord `clear_doi` côté `resolve_doi_conflict`) n'est pas jouée — le doc est compté comme "à traiter" sans distinction entre match/create/skip-no-perimeter.
    """
    title = doc.title or ""
    pub_year = doc.pub_year
    if not has_minimal_publication_metadata(title, pub_year):
        return "skipped_no_metadata"
    assert pub_year is not None  # garanti par has_minimal_publication_metadata (truthy check)

    if dry_run:
        return "created"

    doi = doc.doi
    source = doc.source
    raw_doc_type = doc.doc_type
    journal_id = doc.journal_id
    raw_oa_status = doc.oa_status

    # Corrections appliquées à la SP entrante avant les queries de dedup metadata, pour que le matching porte sur les valeurs corrigées (cf. domain/publications/correction.py).
    corrected = effective_metadata(_view_from_row(doc))
    if corrected.doc_type is not None:
        raw_doc_type = corrected.doc_type.value
    if corrected.journal_id is not None:
        journal_id = corrected.journal_id.value
    if corrected.oa_status is not None:
        raw_oa_status = corrected.oa_status.value

    doc_type = map_doc_type(raw_doc_type, source) or "other"
    oa_status = raw_oa_status or OA_STATUS_UNKNOWN_DEFAULT
    language = doc.language
    container_title = doc.container_title

    # Décodage HTML double-encodage du titre (OpenAlex / ScanR) avant comparaison ou écriture.
    cleaned_title = clean_publication_title(title) or ""
    if cleaned_title != title:
        title = cleaned_title
    title_normalized = normalize_text(title)

    known_ids = extract_known_identifiers(doc.external_ids)
    nnt = known_ids.get("nnt")
    if nnt:
        nnt = normalize_nnt(nnt)
    hal_id = known_ids.get("hal_id")

    # Prefetch DOI : résolution du conflit éventuel (chapter/book) qui peut invalider le DOI ou poser un id de fusion.
    doi_merge_with_id: int | None = None
    if doi:
        existing_by_doi = pub_repo.find_by_doi(doi)
        if existing_by_doi:
            new_doi_str, doi_merge_with_id = resolve_doi_conflict(
                doi,
                doc_type,
                title_normalized,
                existing_by_doi,
                repo=pub_repo,
            )
            doi = new_doi_str

    # Prefetch NNT
    nnt_match_id: int | None = None
    if nnt:
        nnt_match_id = pub_repo.find_by_nnt(nnt)

    # Prefetch HAL_ID (clé portée par `external_ids` sur toutes les sources, y compris HAL natif)
    hal_id_match_id: int | None = None
    if hal_id:
        hal_id_match_id = pub_repo.find_by_hal_id(hal_id)

    # Prefetch dédup par métadonnées : aiguillage par doc_type vers la
    # règle correspondante. Les règles vivent dans
    # `metadata_deduplication_rules.py` ; chaque membre de
    # `MetadataDeduplicationCase` est documenté côté domain.
    metadata_match: tuple[int, MetadataDeduplicationCase] | None = None
    if doc_type == "thesis":
        metadata_match = match_thesis_by_title_year(
            conn,
            queries=queries,
            source_publication_id=doc.id,
            title_normalized=title_normalized,
            pub_year=pub_year,
            pub_repo=pub_repo,
        )
    elif doc_type == "proceedings":
        metadata_match = match_proceedings_by_title_year_authorcount(
            conn,
            queries=queries,
            source_publication_id=doc.id,
            title_normalized=title_normalized,
            pub_year=pub_year,
            doi=doi,
            pub_repo=pub_repo,
        )

    decision = decide_publication_match(
        doi_merge_with_id=doi_merge_with_id,
        nnt_match_id=nnt_match_id,
        hal_id_match_id=hal_id_match_id,
        metadata_match=metadata_match,
    )

    if decision.action == "match":
        assert decision.publication_id is not None
        publication_id = decision.publication_id
        outcome: Outcome = "linked"
    else:
        allow_create = doc.in_perimeter
        if not allow_create:
            return "skipped_no_perimeter"
        publication_id = pub_repo.create(
            title=title,
            title_normalized=title_normalized,
            doc_type=doc_type,
            pub_year=pub_year,
            doi=doi,
            oa_status=oa_status,
            journal_id=journal_id,
            container_title=container_title,
            language=language,
        )
        outcome = "created"

    queries.link_source_publication_to_publication(conn, doc.id, publication_id)
    refresh_from_sources(publication_id, repo=pub_repo, audit_repo=audit_repo)

    return outcome


def run(
    conn: Connection,
    queries: PublicationsMatchOrCreateQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
    dry_run: bool = False,
) -> None:
    try:
        # ── Phase A : orphelins in_perimeter (création ou rattachement) ──
        docs = queries.fetch_orphan_in_perimeter_source_publications(conn)
        logger.info("Phase A : %d source_publications orphelins in_perimeter", len(docs))

        counts: dict[Outcome, int] = {
            "created": 0,
            "linked": 0,
            "skipped_no_metadata": 0,
            "skipped_no_perimeter": 0,
        }
        for i, doc in enumerate(docs):
            outcome = process_document(
                conn, queries, doc, dry_run, pub_repo=pub_repo, audit_repo=audit_repo
            )
            counts[outcome] += 1

            if (i + 1) % 500 == 0:
                if not dry_run:
                    conn.commit()
                logger.info("  Phase A : %d/%d traités...", i + 1, len(docs))

        if not dry_run:
            conn.commit()
        logger.info(
            "Phase A terminée : %d créées, %d rattachées, %d sans métadonnées",
            counts["created"],
            counts["linked"],
            counts["skipped_no_metadata"],
        )

        # ── Phase B : rattachement set-based des orphelins hors-périmètre ──
        # 3 UPDATEs SQL bulk (DOI / NNT / hal_id), exécutés séparément avec
        # commit + log entre chaque pour granularité d'observabilité.
        # Bénéficie des publications créées en Phase A. Pas de création
        # (gated par in_perimeter).
        if dry_run:
            logger.info("Phase B (bulk link hors-périmètre) : skipped (dry-run)")
        else:
            logger.info("Phase B step 1/3 : rattachement par DOI...")
            t0 = time.perf_counter()
            n_doi = queries.bulk_link_orphans_by_doi(conn)
            conn.commit()
            logger.info("  → %d rattachées (%.1fs)", n_doi, time.perf_counter() - t0)

            logger.info("Phase B step 2/3 : rattachement par NNT...")
            t0 = time.perf_counter()
            n_nnt = queries.bulk_link_orphans_by_nnt(conn)
            conn.commit()
            logger.info("  → %d rattachées (%.1fs)", n_nnt, time.perf_counter() - t0)

            logger.info("Phase B step 3/3 : rattachement par hal_id...")
            t0 = time.perf_counter()
            n_hal_id = queries.bulk_link_orphans_by_hal_id(conn)
            conn.commit()
            logger.info("  → %d rattachées (%.1fs)", n_hal_id, time.perf_counter() - t0)

            logger.info(
                "Phase B terminée : %d rattachées (DOI=%d, NNT=%d, hal_id=%d)",
                n_doi + n_nnt + n_hal_id,
                n_doi,
                n_nnt,
                n_hal_id,
            )

        # ── Phase 2 : refresh des publications stale ──
        # Au moins un source_publication modifié depuis le dernier refresh
        # canonique (couvre les re-traitements des normalizers + les nouveaux
        # rattachements effectués en Phase A/B).
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
                "DRY-RUN : %d à traiter (approx.), %d sans métadonnées, %d à rafraîchir",
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
