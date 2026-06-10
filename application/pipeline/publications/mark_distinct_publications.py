"""Passe : marque les publications **distinctes** (garde des fusions).

Pour chaque groupe de publications partageant une clé de fusion (DOI, …),
applique `detect_distinct_case` à chaque paire et inscrit les paires distinctes
dans `distinct_publications`. Cette table est ensuite consultée comme garde par
les passes de fusion (et par les pages doublons admin).

S'exécute **avant** les passes de fusion. Idempotente : `mark_distinct` ignore
les paires déjà connues.

L'orchestrateur dépend du port `DistinctPublicationsQueries`.
"""

import logging
from itertools import combinations

from sqlalchemy import Connection

from application.ports.pipeline.distinct_publications import DistinctPublicationsQueries
from application.ports.repositories.publication_repository import PublicationRepository
from domain.publications.distinct_publications import detect_distinct_case


def run_mark_distinct(
    conn: Connection,
    queries: DistinctPublicationsQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
    commit: bool = True,
) -> int:
    """Marque les paires distinctes parmi les publications partageant un DOI.

    Retourne le nombre de paires nouvellement marquées (en dry-run, le nombre
    de paires qui le seraient).
    """
    groups = queries.find_publications_sharing_doi(conn)
    logger.info("DOI partagés par ≥2 publications : %d", len(groups))

    marked = 0
    for group in groups:
        for a, b in combinations(group.publications, 2):
            case = detect_distinct_case(
                doc_type_a=a.doc_type,
                title_normalized_a=a.title_normalized,
                doc_type_b=b.doc_type,
                title_normalized_b=b.title_normalized,
            )
            if case is None:
                continue
            if dry_run:
                marked += 1
                logger.info("  [DRY] distinct (%s) : %d ⇔ %d", case.value, a.id, b.id)
                continue
            if pub_repo.mark_distinct(a.id, b.id) is not None:
                marked += 1
                logger.info("  distinct (%s) : %d ⇔ %d", case.value, a.id, b.id)

    if commit and not dry_run:
        conn.commit()
    logger.info(
        "Terminé : %d paire(s) marquée(s) distinctes%s",
        marked,
        " (dry-run)" if dry_run else "",
    )
    return marked
