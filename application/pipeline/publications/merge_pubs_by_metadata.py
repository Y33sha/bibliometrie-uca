"""Fusionne les publications dupliquées par métadonnées (thèse / proceedings).

Transpose en fusion pub↔pub les règles `MetadataDeduplicationCase` (jadis
appliquées au matching SP→publication) : deux publications au même
`title_normalized` + `pub_year` et de même famille de doc_type sont fusionnées
si les critères doc_type-spécifiques tiennent.

- **thèse** (`thesis`/`ongoing_thesis`) : compatibilité de l'auteur primary
  (`thesis_authors_compatible`) ; si l'un des deux est inconnu, accepté.
- **proceedings** : titre normalisé long (> 30 car.) + même nombre d'auteurs
  (`MAX` par source de chaque côté).

Le cas « deux DOI non-nuls différents » n'est pas filtré ici : la garde de
`merge_publications_by_key` le refuse de toute façon (œuvres distinctes).

L'orchestrateur dépend du port `MetadataMergeQueries`. Le point d'entrée CLI est
dans `interfaces/cli/pipeline/merge_pubs_by_metadata.py`.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.publications.merge_by_key import merge_publications_by_key
from application.ports.pipeline.metadata_merge import (
    MetadataMergeCandidatePair,
    MetadataMergeQueries,
)
from application.ports.repositories.publication_repository import PublicationRepository
from domain.normalize import normalize_name
from domain.sources.theses import thesis_authors_compatible

_THESIS_DOC_TYPES = frozenset({"thesis", "ongoing_thesis"})
_PROCEEDINGS_MIN_TITLE_LEN = 30


def _thesis_pair_merges(
    conn: Connection, queries: MetadataMergeQueries, pair: MetadataMergeCandidatePair
) -> bool:
    author_a = queries.fetch_thesis_primary_author(conn, pair.id_a)
    author_b = queries.fetch_thesis_primary_author(conn, pair.id_b)
    # Auteur inconnu d'un côté → accepté (comportement historique du matching).
    if author_a is None or author_b is None:
        return True
    # `thesis_authors_compatible` normalise `primary` mais attend le `claimed`
    # déjà normalisé ; les deux auteurs viennent ici de la BDD (bruts), on
    # normalise donc le second.
    claimed = (normalize_name(author_b[0]), normalize_name(author_b[1]))
    return thesis_authors_compatible(author_a, claimed)


def _proceedings_pair_merges(
    conn: Connection, queries: MetadataMergeQueries, pair: MetadataMergeCandidatePair
) -> bool:
    if len(pair.title_normalized) <= _PROCEEDINGS_MIN_TITLE_LEN:
        return False
    count_a = queries.fetch_max_source_authorship_count_per_publication(conn, pair.id_a)
    count_b = queries.fetch_max_source_authorship_count_per_publication(conn, pair.id_b)
    return count_a == count_b


def run_merge(
    conn: Connection,
    queries: MetadataMergeQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
) -> None:
    try:
        pairs = queries.find_metadata_merge_candidate_pairs(conn)
        logger.info(f"Paires candidates par métadonnées : {len(pairs)}")

        groups: list[tuple[str, list[int]]] = []
        for pair in pairs:
            is_thesis = pair.doc_type_a in _THESIS_DOC_TYPES
            merges = (
                _thesis_pair_merges(conn, queries, pair)
                if is_thesis
                else _proceedings_pair_merges(conn, queries, pair)
            )
            if merges:
                kind = "thèse" if is_thesis else "proceedings"
                label = f"{kind} «{pair.title_normalized[:40]}» {pair.id_a}↔{pair.id_b}"
                groups.append((label, [pair.id_a, pair.id_b]))

        if not groups:
            logger.info("Rien à fusionner.")
            return

        merged, errors = merge_publications_by_key(
            conn, groups, logger=logger, pub_repo=pub_repo, dry_run=dry_run
        )

        if not dry_run:
            conn.commit()
            logger.info("Commit OK.")

        logger.info(f"  {merged} fusionnées, {errors} erreurs")
        if dry_run:
            logger.info("[DRY RUN] Aucune modification.")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur : {e}")
        raise
