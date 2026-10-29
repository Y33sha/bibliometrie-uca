"""Tout terme de recherche reçu en query string est borné en longueur.

Un terme part dans un motif `ILIKE '%…%'`, dont le coût croît avec sa longueur : sans borne, une requête fait parcourir la table sur un motif arbitrairement long, avec le plafond de fréquence pour seule limite.

Le contrat d'API publié déclare la borne de chaque paramètre. Le test le lit pour couvrir toutes les routes, sans liste tenue à la main.
"""

from typing import Any

from interfaces.api.app import app
from interfaces.api.params import MAX_SEARCH_LENGTH

# Nombre minimal de paramètres attendus : un parcours qui n'en trouverait aucun rendrait les assertions vides, donc vertes.
_PLANCHER = 20


def _parametres_de_recherche() -> list[tuple[str, str, dict[str, Any]]]:
    """Paramètres de recherche du contrat publié : chemin, nom et schéma déclaré."""
    return [
        (chemin, parametre["name"], parametre["schema"])
        for chemin, operations in app.openapi()["paths"].items()
        for operation in operations.values()
        for parametre in operation.get("parameters", [])
        if parametre["in"] == "query" and parametre["name"].endswith("search")
    ]


def _bornes_declarees(schema: dict[str, Any]) -> set[int | None]:
    """Bornes de longueur d'un schéma, y compris dans une union avec le type nul."""
    variantes = schema.get("anyOf", [schema])
    return {
        variante.get("maxLength")
        for variante in variantes
        if variante.get("type") == "string" or "anyOf" not in schema
    }


def test_le_parcours_trouve_les_parametres_de_recherche():
    assert len(_parametres_de_recherche()) >= _PLANCHER


def test_chaque_terme_de_recherche_est_borne():
    sans_borne = [
        (chemin, nom)
        for chemin, nom, schema in _parametres_de_recherche()
        if _bornes_declarees(schema) != {MAX_SEARCH_LENGTH}
    ]
    assert not sans_borne, (
        f"Termes de recherche sans borne de longueur : {sans_borne}. Les annoter avec le type "
        "partagé `SearchTerm` (`interfaces/api/params.py`)."
    )


def test_la_borne_couvre_une_adresse_d_affiliation_entiere():
    """La borne laisse passer une affiliation entière, recopiée telle quelle dans la recherche d'adresses."""
    affiliation = (
        "Université Clermont Auvergne, CNRS, Laboratoire de Mathématiques Blaise Pascal, "
        "UMR 6620, Campus Universitaire des Cézeaux, 3 place Vasarely, "
        "63178 Aubière CEDEX, France"
    )
    assert len(affiliation) <= MAX_SEARCH_LENGTH
