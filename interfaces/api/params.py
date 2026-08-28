"""Query params déclarés à l'identique par plusieurs routers.

Un paramètre partagé se déclare ici une fois, avec ses bornes ; le type annoté porte la validation et part dans le contrat OpenAPI.
"""

from collections.abc import Mapping
from typing import Annotated

from fastapi import Query

# Nombre de sujets que rendent les nuages de mots (éditeur, revue, laboratoire, personne).
TOP_SUBJECTS_LIMIT = 30

TopSubjectsLimit = Annotated[int, Query(ge=1, le=200)]

# Plafond du décalage qu'une lecture paginée peut demander, aligné sur celui des exports : aucune
# lecture ne rend ni ne saute plus de 500 000 lignes. Un rang de page sans borne ferait trier à la
# base l'ensemble du résultat pour n'en rendre aucune ligne, au prix le plus élevé qu'une lecture
# ouverte puisse coûter. Le plafond passe au-delà du plus gros corpus servi, si bien qu'aucune
# ligne ne devient inatteignable.
MAX_PAGINATION_OFFSET = 500_000

_DEFAULT_PER_PAGE = 50


def requested_offset(query_params: Mapping[str, str]) -> int | None:
    """Décalage qu'une requête demande — `(page - 1) * per_page` —, ou `None` faute de pagination lisible.

    Rend `None` quand la requête ne porte pas de rang de page, et quand les valeurs sont illisibles ou hors bornes : leur refus appartient à la validation de la route, qui le formule dans les termes du contrat d'API.
    """
    if "page" not in query_params:
        return None
    try:
        page = int(query_params["page"])
        per_page = int(query_params.get("per_page", _DEFAULT_PER_PAGE))
    except ValueError:
        return None
    if page < 1 or per_page < 1:
        return None
    return (page - 1) * per_page
