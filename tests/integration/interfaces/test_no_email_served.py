"""Les adresses électroniques du référentiel des personnels ne sortent par aucune lecture.

`persons_rh.email` est renseigné pour départager les homonymes au rattachement des signatures. Cet usage est interne au traitement : aucune réponse de l'API n'a à porter cette valeur. Le contrat d'API et les couches qui le servent sont confrontés à cette règle, plutôt que de la laisser tenir à l'attention de qui ajoute un champ.
"""

import re

from infrastructure import PROJECT_ROOT
from interfaces.api.app import app

EMAIL_LIKE = re.compile(r"\b(e?[-_]?mails?|courriels?)\b", re.IGNORECASE)
"""Ce qui nomme une adresse électronique, aux frontières de mot près : « maillon » n'en est pas une."""

SERVING_LAYERS = (
    "application/ports/read_models",
    "infrastructure/read_models",
    "interfaces/api",
)
"""Couches qui composent une réponse de lecture : les contrats, le SQL qui les remplit, la surface HTTP."""


def test_aucun_champ_du_contrat_d_api_ne_porte_une_adresse():
    """Le schéma OpenAPI décrit tout ce que l'API rend : aucune propriété n'y nomme une adresse électronique."""
    schemas = app.openapi()["components"]["schemas"]
    fautifs = [
        f"{nom}.{propriete}"
        for nom, schema in schemas.items()
        for propriete in schema.get("properties", {})
        if EMAIL_LIKE.search(propriete)
    ]
    assert not fautifs, "Le contrat d'API expose une ou des adresses électroniques : " + ", ".join(
        fautifs
    )


def test_aucune_couche_de_lecture_ne_nomme_la_colonne():
    """La colonne n'est lue nulle part sur le chemin d'une réponse — ni en SQL, ni dans un DTO, ni dans un router."""
    fautifs = [
        f"{chemin.relative_to(PROJECT_ROOT)}:{numero}"
        for couche in SERVING_LAYERS
        for chemin in (PROJECT_ROOT / couche).rglob("*.py")
        for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), start=1)
        if EMAIL_LIKE.search(ligne)
    ]
    assert not fautifs, "Une couche de lecture mentionne une adresse électronique : " + ", ".join(
        fautifs
    )
