"""
Matche ou crée les publications canoniques pour les `source_publications` non rattachés, puis rafraîchit les publications dont au moins un source a été modifié.

Phase du pipeline qui s'exécute APRÈS affiliations (quand in_perimeter est déterminé sur les source_authorships) et AVANT persons/authorships.

Deux passes :
1. Pour chaque `source_publication` sans `publication_id` (tous périmètres confondus) : cascade de matching cross-source (`decide_publication_match` sur DOI, NNT, HAL_ID, THESIS_TITLE_YEAR). Si match : rattache, quel que soit le périmètre — c'est ce qui permet de résoudre les conflits inter-sources (ex. version HAL hors-UCA + version OpenAlex UCA → rattachement à la même publication canonique). Sinon : crée la publication, mais uniquement si `allow_create` (dérivé de la colonne `in_perimeter`) est vrai — sans authorship in_perimeter, on ne fait pas entrer une nouvelle publication dans le périmètre.
2. Pour chaque publication stale (au moins un `source_publication.updated_at > publications.updated_at`) : `refresh_from_sources` pour ré-agréger les méta canoniques (dont DOI promu par priorité de source).

L'orchestrateur dépend du port `PublicationsMatchOrCreateQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/match_or_create_publications.py`.
"""

import logging
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
from application.publications import refresh_from_sources
from domain.normalize import normalize_text
from domain.publications.deduplication import (
    MetadataDeduplicationCase,
    decide_publication_match,
)
from domain.publications.metadata import (
    OA_STATUS_UNKNOWN_DEFAULT,
    clean_publication_title,
    has_minimal_publication_metadata,
)
from domain.source_publications.keys import project_confirmation_keys

Outcome = Literal["created", "linked", "skipped_no_metadata", "skipped_no_perimeter"]


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

    En dry_run, la cascade de matching n'est pas jouée — le doc est compté comme "à traiter" sans distinction entre match/create/skip-no-perimeter.
    """
    title = doc.title or ""
    pub_year = doc.pub_year
    if not has_minimal_publication_metadata(title, pub_year):
        return "skipped_no_metadata"
    assert pub_year is not None  # garanti par has_minimal_publication_metadata (truthy check)

    if dry_run:
        return "created"

    # `doc_type`/`journal_id`/`oa_status` sont lus tels quels : la phase `metadata_correction` les a déjà mappés source→canonique et corrigés en place sur la `source_publication`, y compris pour les règles journal-dépendantes (elle tourne après `publishers_journals`, JOIN `journals`). Le matching porte donc sur les valeurs corrigées sans re-correction ici — qui, faute de JOIN `journals` sur cette projection, ne verrait de toute façon pas ces règles.
    doc_type = doc.doc_type or "other"
    journal_id = doc.journal_id
    oa_status = doc.oa_status or OA_STATUS_UNKNOWN_DEFAULT
    language = doc.language
    container_title = doc.container_title

    # Décodage HTML double-encodage du titre (OpenAlex / ScanR) avant comparaison ou écriture.
    cleaned_title = clean_publication_title(title) or ""
    if cleaned_title != title:
        title = cleaned_title
    title_normalized = normalize_text(title)

    # Clés de confirmation (DOI effectif Zenodo inclus, NNT/PMID/HAL normalisés) :
    # projection partagée avec la réconciliation des composantes — une seule
    # définition de « quelles clés porte cette SP ».
    keys = project_confirmation_keys(doc.doi, doc.external_ids)
    doi = keys.doi
    nnt = keys.nnt
    pmid = keys.pmid
    hal_ids = keys.hal_ids

    # Prefetch DOI : un DOI qui pointe une publication existante est un match positif.
    # Les conflits chapitre/ouvrage (DOI de l'ouvrage porté par erreur par un chapitre)
    # sont neutralisés **a priori** par la correction relationnelle (`metadata_correction`
    # cluster) qui nulle le DOI erroné sur la SP avant cette phase — au match, ces SP
    # n'ont plus le DOI conflictuel, il n'y a donc plus d'arbitrage à faire ici.
    doi_merge_with_id: int | None = None
    if doi:
        existing_by_doi = pub_repo.find_by_doi(doi)
        if existing_by_doi:
            doi_merge_with_id = existing_by_doi.id

    # Prefetch NNT
    nnt_match_id: int | None = None
    if nnt:
        nnt_match_id = pub_repo.find_by_nnt(nnt)

    # Prefetch HAL_ID : matche sur le premier des hal-ids référencés qui résout
    # (clé multivaluée portée par `external_ids` sur toutes les sources).
    hal_id_match_id: int | None = None
    for h in hal_ids:
        hal_id_match_id = pub_repo.find_by_hal_id(h)
        if hal_id_match_id is not None:
            break

    # Prefetch PMID (clé portée par `external_ids` ; un PMID = un article PubMed)
    pmid_match_id: int | None = None
    if pmid:
        pmid_match_id = pub_repo.find_by_pmid(pmid)

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
        pmid_match_id=pmid_match_id,
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
        # ── Assignation : tous les orphelins (match cross-source, ou création gatée périmètre) ──
        # Un seul traitement per-row pour tous les orphelins, quel que soit le périmètre :
        # le gate `allow_create = in_perimeter` empêche la création hors-périmètre, mais le
        # rattachement à une publication existante reste permis (résolution des conflits
        # inter-sources). La réconciliation des composantes (passe suivante) capte les ponts.
        docs = queries.fetch_orphan_source_publications(conn)
        logger.info("Assignation : %d source_publications orphelins", len(docs))

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
                logger.info("  Assignation : %d/%d traités...", i + 1, len(docs))

        if not dry_run:
            conn.commit()
        logger.info(
            "Assignation terminée : %d créées, %d rattachées, %d sans métadonnées, %d hors-périmètre",
            counts["created"],
            counts["linked"],
            counts["skipped_no_metadata"],
            counts["skipped_no_perimeter"],
        )

        # ── Refresh des publications stale ──
        # Au moins un source_publication modifié depuis le dernier refresh
        # canonique (couvre les re-traitements des normalizers + les nouveaux
        # rattachements effectués à l'assignation).
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
