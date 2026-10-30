"""Identifiants d'accès aux API des sources, lus dans l'environnement du processus comme les autres secrets de l'application."""

from infrastructure.settings import settings
from pipeline.http.polite_pool import get_polite_pool_email_optional


def get_openalex_api_key() -> str | None:
    """Renvoie la clé d'API OpenAlex, ou `None` si elle est absente de la configuration."""
    return settings.openalex_api_key.get_secret_value() or None


def get_wos_api_key() -> str:
    """Renvoie la clé d'API Web of Science, ou une chaîne vide si elle est absente de la configuration."""
    return settings.wos_api_key.get_secret_value()


def get_scanr_credentials() -> tuple[str, str]:
    """Renvoie l'utilisateur et le mot de passe de l'API ScanR, ou `("", "")` si l'un des deux manque."""
    user, password = settings.scanr_username, settings.scanr_password.get_secret_value()
    if user and password:
        return user, password
    return "", ""


def source_credentials_missing(source: str) -> str | None:
    """Renvoie le motif de l'absence des identifiants d'API d'une source, ou `None` si la source est utilisable.

    `access_source` appelle cette fonction avant tout appel à une API tierce. Un accès avec motif est sauté, avec un avertissement. HAL, theses.fr, doi.org et DOAJ sont des API publiques. L'adresse polite pool compte comme un identifiant : Crossref, DataCite et Unpaywall l'exigent, OpenAlex l'accepte à défaut de clé d'API.
    """
    if source in ("hal", "theses"):
        return None
    if source == "openalex":
        if get_openalex_api_key() or get_polite_pool_email_optional():
            return None
        return "ni clé d'API ni adresse polite pool (OPENALEX_API_KEY / POLITE_POOL_EMAIL)"
    if source == "wos":
        return None if get_wos_api_key() else "clé d'API absente (WOS_API_KEY)"
    if source == "scanr":
        user, password = get_scanr_credentials()
        if user and password:
            return None
        return "identifiants absents (SCANR_USERNAME / SCANR_PASSWORD)"
    if source in ("crossref", "datacite", "unpaywall"):
        if get_polite_pool_email_optional():
            return None
        return "adresse polite pool absente (POLITE_POOL_EMAIL)"
    return None
