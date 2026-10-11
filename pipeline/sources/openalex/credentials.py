"""Identifiants des requêtes OpenAlex, lus en configuration."""

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
