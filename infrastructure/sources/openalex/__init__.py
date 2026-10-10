"""Constantes et utilitaires de configuration pour l'extraction OpenAlex.

L'URL de base de l'API est un invariant exposé par `infrastructure.sources.api_params.API_BASE_URLS["openalex"]`.

Le parsing pur des works (`extract_openalex_id`, `extract_doi`) vit dans `parsing.py` et est couvert par tests unitaires. Ce module ne garde que les paramètres d'authentification (`credential_params`, `auth_params`) et la liste des champs demandés à l'API (`SELECT_FIELDS`, analogue d'`HAL_FIELDS`).
"""

from infrastructure.sources.config import get_openalex_api_key, get_polite_pool_email_optional


def credential_params() -> dict[str, str]:
    """Identifiants d'une requête OpenAlex : la clé d'API, sinon l'adresse du polite pool, l'une et l'autre facultatives."""
    if api_key := get_openalex_api_key():
        return {"api_key": api_key}
    if email := get_polite_pool_email_optional():
        return {"mailto": email}
    return {}


def auth_params() -> dict[str, str]:
    """Paramètres d'une requête OpenAlex sur les works : identifiants, et inclusion des works hors corpus principal (`include_xpac`)."""
    return {"include_xpac": "true", **credential_params()}


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
        "fwci",
        "citation_normalized_percentile",
        "biblio",
        "is_retracted",
        "topics",
        "keywords",
        "abstract_inverted_index",
    ]
)
