"""Règles de déduplication / création des publications.

Domain services purs autour de la déduplication : invariants de métadonnées minimales, résolution de conflit DOI entre deux documents.
"""

from dataclasses import dataclass

_CHAPTER_DOC_TYPES: frozenset[str] = frozenset({"book_chapter", "book-chapter", "chapter"})
_BOOK_DOC_TYPES: frozenset[str] = frozenset({"book"})


def has_minimal_publication_metadata(title: str | None, pub_year: int | None) -> bool:
    """Indique si la publication candidate a les métadonnées minimales
    nécessaires à sa création/déduplication.

    Invariant : titre non vide ET année renseignée. Sans ces deux
    champs :

    - le pivot de matching/déduplication par cascade
      ``DOI > NNT > title+year+journal`` est trop faible (pas de
      fallback titre+année possible) ;
    - la valeur métier est nulle (pas de référence biblio
      consultable, pas d'année pour les statistiques).

    Une `pub_year` à 0 est considérée comme absente (cas pathologique
    qui ne devrait pas remonter en BDD : `bool(0) is False`).
    """
    return bool(title) and bool(pub_year)


@dataclass(frozen=True, slots=True)
class DoiConflictResolution:
    """Décision pure pour un conflit DOI entre deux documents.

    - `accepted_doi` : DOI à utiliser pour le nouveau document (None =
      ne pas lui attribuer ce DOI).
    - `merge_with_id` : id de la publication existante à fusionner avec
      (None = pas de fusion).
    - `clear_existing_doi` : True si le DOI doit être retiré de la
      publication existante (effet de bord à appliquer par l'appelant).
    """

    accepted_doi: str | None
    merge_with_id: int | None
    clear_existing_doi: bool


def resolve_doi_conflict(
    new_doi: str,
    new_doc_type: str,
    new_title_normalized: str,
    existing_doc_type: str | None,
    existing_title_normalized: str | None,
    existing_id: int,
) -> DoiConflictResolution:
    """Règle pure : gère les conflits de DOI entre chapitres et ouvrages.

    Quand un DOI existe déjà sur une publication d'un type incompatible
    (chapitre vs ouvrage), le DOI est retiré de l'un ou des deux côtés
    au lieu de fusionner. Dans tous les autres cas, les types sont
    considérés compatibles et on fusionne.
    """
    ex_type = existing_doc_type or ""

    # Chapitre vs ouvrage : le DOI est celui de l'ouvrage, pas du chapitre
    if new_doc_type in _CHAPTER_DOC_TYPES and ex_type in _BOOK_DOC_TYPES:
        return DoiConflictResolution(
            accepted_doi=None, merge_with_id=None, clear_existing_doi=False
        )

    if new_doc_type in _BOOK_DOC_TYPES and ex_type in _CHAPTER_DOC_TYPES:
        return DoiConflictResolution(
            accepted_doi=new_doi, merge_with_id=None, clear_existing_doi=True
        )

    # Deux chapitres avec titres différents : DOI erroné des deux côtés
    if new_doc_type in _CHAPTER_DOC_TYPES and ex_type in _CHAPTER_DOC_TYPES:
        ex_title = existing_title_normalized or ""
        if new_title_normalized != ex_title:
            return DoiConflictResolution(
                accepted_doi=None, merge_with_id=None, clear_existing_doi=True
            )
        return DoiConflictResolution(
            accepted_doi=new_doi, merge_with_id=existing_id, clear_existing_doi=False
        )

    # Cas normal : même DOI, types compatibles → fusion
    return DoiConflictResolution(
        accepted_doi=new_doi, merge_with_id=existing_id, clear_existing_doi=False
    )
