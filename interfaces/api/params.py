"""Query params déclarés à l'identique par plusieurs routers.

Un paramètre partagé se déclare ici une fois, avec ses bornes ; le type annoté porte la validation et part dans le contrat OpenAPI.
"""

from collections.abc import Mapping
from typing import Annotated

from fastapi import Query
from pydantic import AfterValidator

# Nombre de sujets que rendent les nuages de mots (éditeur, revue, laboratoire, personne).
TOP_SUBJECTS_LIMIT = 30

TopSubjectsLimit = Annotated[int, Query(ge=1, le=200)]

MAX_SEARCH_LENGTH = 500
"""Longueur maximale d'un terme de recherche.

Le terme part dans un motif `ILIKE '%…%'`, dont le coût croît avec sa longueur : sans borne, une requête fait balayer la table sur un motif arbitrairement long, et le plafond de fréquence est la seule digue. La valeur laisse passer ce qu'une personne cherche réellement, jusqu'à une adresse d'affiliation entière recopiée dans la recherche d'adresses, et arrête le reste.
"""


def reject_control_characters(value: str) -> str:
    """Refuse une valeur portant un caractère de contrôle, l'octet NUL en tête.

    PostgreSQL n'accepte pas l'octet NUL dans un champ texte, et le driver refuse la valeur à l'adaptation des paramètres : sans ce contrôle, une recherche qui en porte un traverse la route et casse au moment de la requête, hors de portée du contrat d'API. Les autres caractères de contrôle sont refusés avec lui — aucun ne désigne un texte cherché.

    La tabulation, le retour chariot et le saut de ligne restent admis : un terme recopié depuis un document en porte.
    """
    intrus = sorted({c for c in value if (c < " " or c == "\x7f") and c not in "\t\r\n"})
    if intrus:
        codes = ", ".join(f"U+{ord(c):04X}" for c in intrus)
        raise ValueError(f"Caractères de contrôle interdits : {codes}.")
    return value


TextParam = Annotated[str, AfterValidator(reject_control_characters)]
"""Valeur textuelle libre reçue d'un appelant, refusée si elle porte un caractère de contrôle.

Sert les paramètres qui reçoivent du texte sans vocabulaire fermé ni format imposé. Le refus emprunte le code de la validation native, la valeur étant écartée par le contrat de la route.
"""

SearchTerm = Annotated[TextParam, Query(max_length=MAX_SEARCH_LENGTH)]
"""Terme de recherche textuelle, borné en longueur. Sa valeur par défaut appartient à la route, la chaîne vide valant absence de recherche."""

# Taille de page retenue par les listes qui n'en reçoivent pas.
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
