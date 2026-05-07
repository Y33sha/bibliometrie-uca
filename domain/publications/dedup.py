"""Règles de déduplication / création des publications.

Module pensé pour accueillir progressivement la cascade de matching
(DOI > NNT > title+year+journal) et les invariants associés. On
commence par la brique la plus simple : l'invariant de métadonnées
minimales requises pour qu'une publication ait une valeur métier.
"""


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
