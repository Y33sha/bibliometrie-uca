"""Les adresses électroniques du référentiel des personnels sont absentes de toute réponse de l'API.

`hr_records.email` sert seulement à départager les homonymes au rattachement des contributions sources. Les tests confrontent à cette règle le contrat d'API et les couches qui le servent.
"""

import re

from infrastructure import PROJECT_ROOT
from interfaces.api.app import app

EMAIL_LIKE = re.compile(r"\b(e?[-_]?mails?|courriels?)\b", re.IGNORECASE)
"""Motif qui nomme une adresse électronique, aux frontières de mot : « maillon » est exclu."""

SERVING_LAYERS = (
    "infrastructure/read_models",
    "interfaces/api",
)
"""Couches qui composent une réponse de lecture : modèles de réponse, SQL qui les remplit, surface HTTP."""


def test_aucun_champ_du_contrat_d_api_ne_porte_une_adresse():
    """Le schéma OpenAPI décrit tout ce que l'API renvoie : aucune propriété n'y nomme une adresse électronique."""
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
    """Aucun fichier des couches de lecture (SQL, DTO, router) ne mentionne une adresse électronique."""
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
