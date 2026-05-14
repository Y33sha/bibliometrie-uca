"""
Matche ou crée les publications canoniques pour les `source_publications` in-perimeter non rattachés, puis rafraîchit les publications dont au moins un source a été modifié.

Phase du pipeline qui s'exécute APRÈS affiliations (quand in_perimeter est déterminé sur les source_authorships) et AVANT persons/authorships.

Deux passes :
1. Pour chaque `source_publication` sans `publication_id` ayant au moins un `source_authorship` in_perimeter : cascade de matching cross-source (`decide_publication_match` sur DOI, NNT, HAL_ID, THESIS_TITLE_YEAR). Si match : rattache + `try_merge_by_doi` tardif pour les matches non-DOI. Sinon : crée la publication.
2. Pour chaque publication stale (au moins un `source_publication.updated_at > publications.updated_at`) : `refresh_from_sources` pour ré-agréger les méta canoniques.

L'orchestrateur dépend du port `PublicationsMatchOrCreateQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/match_or_create_publications.py`.
"""

import logging
from typing import Any

from sqlalchemy import Connection

from application.ports.pipeline.publications_match_or_create import (
    PublicationsMatchOrCreateQueries,
)
from application.publications import (
    refresh_from_sources,
    resolve_doi_conflict,
    try_merge_by_doi,
)
from domain.normalize import normalize_text
from domain.ports.publication_repository import PublicationRepository
from domain.publication import normalize_nnt
from domain.publications.deduplication import (
    DeduplicationKey,
    MetadataDeduplicationCase,
    decide_publication_match,
)
from domain.publications.doc_types import map_doc_type
from domain.publications.metadata import (
    OA_STATUS_UNKNOWN_DEFAULT,
    clean_publication_title,
    has_minimal_publication_metadata,
)
from domain.sources.theses import thesis_authors_compatible

_NATIVE_KIND_BY_SOURCE: dict[str, str] = {
    "hal": "hal_id",
    "openalex": "openalex_id",
    "wos": "wos_id",
    "scanr": "scanr_id",
}


def extract_known_identifiers(
    source: str,
    source_id: str | None,
    external_ids: dict[str, Any] | None,
) -> dict[str, str]:
    """Aplatit les identifiants connus d'un `source_publication`.

    Combine l'identifiant natif (interprété selon `source`, posé dans `source_publications.source_id`) avec les identifiants cross-source détectés (`external_ids`). Les valeurs `external_ids` priment en cas de collision — elles sont la forme canonique normalisée à la normalisation.

    Renvoie un dict `{kind: value}` plat où `kind` est une clé canonique (`hal_id`, `nnt`, `pmid`, …). Seules les valeurs `str` non vides sont retenues.
    """
    ids: dict[str, str] = {}
    if external_ids:
        ids.update({k: v for k, v in external_ids.items() if isinstance(v, str) and v})
    native_kind = _NATIVE_KIND_BY_SOURCE.get(source)
    if native_kind and source_id:
        ids.setdefault(native_kind, source_id)
    return ids


def process_document(
    conn: Connection,
    queries: PublicationsMatchOrCreateQueries,
    doc: Any,
    dry_run: bool,
    *,
    pub_repo: PublicationRepository,
) -> bool:
    """Crée ou rattache une publication pour un `source_publication` orphelin.

    Pattern prefetch → décideur → dispatch : extrait les identifiants candidats, les confronte aux index existants, puis délègue le choix `match`/`create` à `decide_publication_match`.
    """
    title = doc["title"] or ""
    pub_year = doc["pub_year"]
    if not has_minimal_publication_metadata(title, pub_year):
        return False

    if dry_run:
        return True

    doi = doc["doi"]
    source = doc["source"]
    doc_type = map_doc_type(doc["doc_type"], source) or "other"
    journal_id = doc["journal_id"]
    oa_status = doc["oa_status"] or OA_STATUS_UNKNOWN_DEFAULT
    language = doc["language"]
    container_title = doc["container_title"]

    # Décodage HTML double-encodage du titre (OpenAlex / ScanR) avant comparaison ou écriture.
    cleaned_title = clean_publication_title(title) or ""
    if cleaned_title != title:
        title = cleaned_title
    title_normalized = normalize_text(title)

    known_ids = extract_known_identifiers(source, doc["source_id"], doc["external_ids"])
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
        existing_by_nnt = pub_repo.find_by_nnt(nnt)
        if existing_by_nnt:
            nnt_match_id = existing_by_nnt.id

    # Prefetch HAL_ID (lookup cross-source : path natif HAL + external_ids posé par OpenAlex/ScanR)
    hal_id_match_id: int | None = None
    if hal_id:
        hal_id_match_id = pub_repo.find_by_hal_id(hal_id)

    # Prefetch dédup spécifique thèse : title+year + compatibilité auteur sur le primary.
    metadata_match: tuple[int, MetadataDeduplicationCase] | None = None
    if doc_type == "thesis":
        metadata_match = _match_thesis_by_title_year(
            conn,
            queries=queries,
            source_publication_id=doc["id"],
            title_normalized=title_normalized,
            pub_year=pub_year,
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
        # Enrichissement DOI tardif si match par autre clé que DOI : la pub trouvée peut ne pas porter le DOI proposé.
        if decision.matched_by != DeduplicationKey.DOI and doi:
            publication_id = try_merge_by_doi(publication_id, doi, repo=pub_repo)
    else:
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

    queries.link_source_publication_to_publication(conn, doc["id"], publication_id)
    refresh_from_sources(publication_id, repo=pub_repo)

    return True


def _match_thesis_by_title_year(
    conn: Connection,
    *,
    queries: PublicationsMatchOrCreateQueries,
    source_publication_id: int,
    title_normalized: str,
    pub_year: int,
    pub_repo: PublicationRepository,
) -> tuple[int, MetadataDeduplicationCase] | None:
    """Cherche une thèse canonique compatible par titre+année + auteur principal.

    Pour chaque candidat retourné par `find_thesis_by_title`, vérifie la compatibilité de l'auteur primary (via `thesis_authors_compatible`). Si l'auteur du `source_publication` courant est inconnu, le candidat est accepté sans vérification (préserve le comportement historique de `normalize_theses.find_publication`).
    """
    if not title_normalized or not pub_year:
        return None
    candidates = pub_repo.find_thesis_by_title(title_normalized, pub_year)
    if not candidates:
        return None
    author = queries.fetch_thesis_primary_author_from_source_publication(
        conn, source_publication_id
    )
    for cand in candidates:
        primary = queries.fetch_thesis_primary_author(conn, cand.id)
        if not author or thesis_authors_compatible(primary, author):
            return (cand.id, MetadataDeduplicationCase.THESIS_TITLE_YEAR)
    return None


def run(
    conn: Connection,
    queries: PublicationsMatchOrCreateQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
) -> None:
    try:
        docs = queries.fetch_orphan_in_perimeter_source_publications(conn)
        logger.info("%d source_publications in-perimeter sans publication", len(docs))

        created = 0
        skipped = 0
        for i, doc in enumerate(docs):
            if process_document(conn, queries, doc, dry_run, pub_repo=pub_repo):
                created += 1
            else:
                skipped += 1

            if (i + 1) % 500 == 0:
                if not dry_run:
                    conn.commit()
                logger.info("  %d/%d traités...", i + 1, len(docs))

        # Passe 2 : refresh des publications stale (au moins un source_publication modifié depuis le dernier refresh canonique). Couvre les re-traitements des normalizers qui mettent à jour des méta sans toucher au rattachement.
        stale_ids = queries.fetch_stale_publication_ids(conn)
        logger.info("%d publications stale à rafraîchir", len(stale_ids))
        refreshed = 0
        for i, pub_id in enumerate(stale_ids):
            try:
                refresh_from_sources(pub_id, repo=pub_repo)
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
                "DRY-RUN : %d publications à créer, %d ignorées, %d à rafraîchir",
                created,
                skipped,
                refreshed,
            )
            conn.rollback()
        else:
            conn.commit()
            logger.info(
                "Terminé : %d publications créées/rattachées, %d ignorées, %d rafraîchies",
                created,
                skipped,
                refreshed,
            )

    except Exception:
        conn.rollback()
        logger.exception("Erreur")
        raise
