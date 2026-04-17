"""Constantes et utilitaires partagés pour l'extraction OpenAlex."""

from extraction.common import clean_doi, compute_hash

BASE_URL = "https://api.openalex.org/works"

# Paramètres d'authentification — initialisés par le premier script lancé
_api_key = None
_email = ""


def init_auth(api_key: str | None = None, email: str = ""):
    """Initialise les paramètres d'authentification OpenAlex."""
    global _api_key, _email
    _api_key = api_key
    _email = email


def auth_params() -> dict:
    """Retourne les paramètres d'authentification pour une requête OpenAlex."""
    params = {"include_xpac": "true"}
    if _api_key:
        params["api_key"] = _api_key
    elif _email:
        params["mailto"] = _email
    return params


SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "publication_date",
        "type",
        "language",
        "primary_location",
        "locations",
        "authorships",
        "open_access",
        "cited_by_count",
        "biblio",
        "is_retracted",
        "topics",
        "keywords",
        "abstract_inverted_index",
    ]
)


def extract_openalex_id(work: dict) -> str:
    """Extrait l'ID OpenAlex court (ex: W2741809807)."""
    return work["id"].replace("https://openalex.org/", "")


def extract_doi(work: dict) -> str | None:
    """Extrait le DOI nettoyé (sans préfixe URL)."""
    return clean_doi(work.get("doi"))


def compute_meta_hash(raw_data: dict) -> str:
    """Hash des métadonnées hors authorships.

    Permet de détecter les changements réels (OA status, titre, etc.)
    sans être perturbé par la troncature à 100 auteurs de l'API bulk.
    """
    filtered = {k: v for k, v in raw_data.items() if k != "authorships"}
    return compute_hash(filtered)
