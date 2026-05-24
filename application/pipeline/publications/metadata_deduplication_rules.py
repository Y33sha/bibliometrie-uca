"""Implémentations concrètes des règles de déduplication par métadonnées.

Chaque fonction `match_<cas>` correspond à un membre de l'énumération `domain.publications.deduplication.MetadataDeduplicationCase`. Les fonctions prefetch les données nécessaires (via le port `PublicationsMatchOrCreateQueries` et le repo `PublicationRepository`) puis appliquent la règle, retournant `(publication_id, MetadataDeduplicationCase) | None`.

Les règles métier elles-mêmes (critères énoncés en clair) sont documentées sur chaque membre de l'enum côté domain ; ce module porte uniquement l'implémentation (prefetch + matching).

Les fonctions exposées ici sont consommées par `application.pipeline.publications.match_or_create_publications.process_document` (cascade à la création) et par les migrations Alembic data qui rattrapent rétroactivement les doublons existants sur le corpus.
"""

from sqlalchemy import Connection

from application.ports.pipeline.publications_match_or_create import (
    PublicationsMatchOrCreateQueries,
)
from application.ports.repositories.publication_repository import PublicationRepository
from domain.publications.deduplication import MetadataDeduplicationCase
from domain.sources.theses import thesis_authors_compatible


def match_thesis_by_title_year(
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
    candidate_ids = pub_repo.find_thesis_by_title(title_normalized, pub_year)
    if not candidate_ids:
        return None
    author = queries.fetch_thesis_primary_author_from_source_publication(
        conn, source_publication_id
    )
    for cand_id in candidate_ids:
        primary = queries.fetch_thesis_primary_author(conn, cand_id)
        if not author or thesis_authors_compatible(primary, author):
            return (cand_id, MetadataDeduplicationCase.THESIS_TITLE_YEAR)
    return None
