"""Query params déclarés à l'identique par plusieurs routers.

Un paramètre partagé se déclare ici une fois, avec ses bornes ; le type annoté porte la validation et part dans le contrat OpenAPI.
"""

from typing import Annotated

from fastapi import Query

# Nombre de sujets que rendent les nuages de mots (éditeur, revue, laboratoire, personne).
TOP_SUBJECTS_LIMIT = 30

TopSubjectsLimit = Annotated[int, Query(ge=1, le=200)]
