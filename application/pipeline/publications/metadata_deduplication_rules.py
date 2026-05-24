"""Implémentations concrètes des règles de déduplication par métadonnées, pour la cascade à la création.

Chaque fonction `match_<cas>` correspond à un membre de l'énumération `domain.publications.deduplication.MetadataDeduplicationCase`. Les fonctions prefetch les données nécessaires (via le port `PublicationsMatchOrCreateQueries` et le repo `PublicationRepository`) puis appliquent la règle, retournant `(publication_id, MetadataDeduplicationCase) | None`.

Les règles métier elles-mêmes (critères énoncés en clair) sont documentées sur chaque membre de l'enum côté domain ; ce module porte uniquement l'implémentation (prefetch + matching).

Le rattrapage rétroactif des doublons déjà en base est porté par une migration Alembic data dédiée par règle (SQL pur, indépendante de ce module).
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


def match_proceedings_by_title_year_authorcount(
    conn: Connection,
    *,
    queries: PublicationsMatchOrCreateQueries,
    source_publication_id: int,
    title_normalized: str,
    pub_year: int,
    doi: str | None,
    pub_repo: PublicationRepository,
) -> tuple[int, MetadataDeduplicationCase] | None:
    """Cherche une publication canonique de type proceedings compatible avec
    le `source_publication` courant : même titre normalisé long, même année,
    même nombre d'auteurs non-excluded, pas de DOI conflictuel.

    Le compteur d'auteurs côté pub canonique candidate est le `MAX` par
    source (la source la plus exhaustive représente le « vrai » nombre),
    cohérent avec la SQL d'inventaire validée et avec l'affichage de la
    page hal-problems duplicate-pubs.
    """
    candidates = pub_repo.find_proceedings_by_title_year(title_normalized, pub_year)
    if not candidates:
        return None
    sp_count = queries.fetch_source_authorship_count(conn, source_publication_id)
    for cand_id, cand_doi in candidates:
        if doi is not None and cand_doi is not None:
            continue
        cand_count = queries.fetch_max_source_authorship_count_per_publication(conn, cand_id)
        if cand_count == sp_count:
            return (cand_id, MetadataDeduplicationCase.PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT)
    return None
