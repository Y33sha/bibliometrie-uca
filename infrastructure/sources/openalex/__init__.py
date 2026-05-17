"""Constantes et utilitaires de configuration pour l'extraction OpenAlex.

L'URL de base de l'API vit dans la config DB (`api_base_urls.openalex`),
lue via `infrastructure.sources.config.get_api_base_urls(cur)["openalex"]`.

Le parsing pur (build_params, extract_*, compute_meta_hash) vit dans
`parsing.py` et est couvert par tests unitaires. Ce module ne garde que
l'état d'auth (mutable via `init_auth`) et la liste des champs
demandés à l'API (`SELECT_FIELDS`, analogue d'`HAL_FIELDS`).
"""

# Paramètres d'authentification — initialisés par le premier script lancé
_api_key = None
_email = ""


def init_auth(api_key: str | None = None, email: str = "") -> None:
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
