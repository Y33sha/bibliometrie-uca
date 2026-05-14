"""Helpers de tests pour la cascade `match-or-create` de publications.

`find_or_create_for_tests` reproduit la cascade équivalente à ce qu'appliquait l'ancien `application.publications.find_or_create` (retiré du code prod) : prefetch DOI avec `resolve_doi_conflict`, prefetch NNT, décision via `decide_publication_match`, création si pas de match. Conservé ici parce que la cascade est testée à l'unité (decideurs purs) et en intégration via `match_or_create_publications.process_document` (qui consomme des rows SQL), mais aucune des deux ne couvre la cascade depuis une `Publication` candidate construite à la main — ce que les tests legacy de dédup font systématiquement.
"""

from application.publications import resolve_doi_conflict
from domain.normalize import normalize_text
from domain.ports.publication_repository import PublicationRepository
from domain.publications.deduplication import decide_publication_match
from domain.publications.identifiers import DOI
from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT, clean_publication_title
from domain.publications.publication import Publication


def find_or_create_for_tests(
    pub: Publication,
    *,
    nnt: str | None = None,
    allow_create: bool = True,
    repo: PublicationRepository,
) -> tuple[Publication | None, bool]:
    """Cascade matching-création utilisée par les tests d'intégration.

    Reproduit l'ancien `application.publications.find_or_create`. Cascade DOI (avec `resolve_doi_conflict` chapter/book) → NNT → création.
    """
    if not pub.has_minimal_metadata():
        return None, False

    cleaned_title = clean_publication_title(pub.title) or ""
    if cleaned_title != pub.title:
        pub.title = cleaned_title
        pub.title_normalized = normalize_text(cleaned_title)

    doi_merge_with_id: int | None = None
    if pub.doi is not None:
        existing_by_doi = repo.find_by_doi(str(pub.doi))
        if existing_by_doi:
            new_doi_str, doi_merge_with_id = resolve_doi_conflict(
                str(pub.doi),
                pub.doc_type or "",
                pub.title_normalized or "",
                existing_by_doi,
                repo=repo,
            )
            pub.doi = DOI(new_doi_str) if new_doi_str else None

    nnt_match_id: int | None = None
    if nnt:
        existing_by_nnt = repo.find_by_nnt(nnt)
        if existing_by_nnt:
            nnt_match_id = existing_by_nnt.id

    decision = decide_publication_match(
        doi_merge_with_id=doi_merge_with_id,
        nnt_match_id=nnt_match_id,
    )

    if decision.action == "match":
        assert decision.publication_id is not None
        return repo.find_by_id(decision.publication_id), False

    if not allow_create:
        return None, False

    pub.id = repo.create(
        title=pub.title,
        title_normalized=pub.title_normalized or normalize_text(pub.title),
        doc_type=pub.doc_type or "other",
        pub_year=pub.pub_year,
        doi=str(pub.doi) if pub.doi else None,
        oa_status=pub.oa_status or OA_STATUS_UNKNOWN_DEFAULT,
        journal_id=pub.journal_id,
        container_title=pub.container_title,
        language=pub.language,
    )
    return pub, True


__all__ = ["find_or_create_for_tests"]
