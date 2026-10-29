"""Identifiants d'accès aux API des sources, lus dans l'environnement du processus comme les autres secrets de l'application."""

from infrastructure.settings import settings
from pipeline.http.polite_pool import get_polite_pool_email_optional


def get_openalex_api_key() -> str | None:
    """Clé d'API OpenAlex, ou `None` si elle n'est pas configurée."""
    return settings.openalex_api_key.get_secret_value() or None


def get_wos_api_key() -> str:
    """Clé d'API Web of Science, chaîne vide si elle n'est pas configurée."""
    return settings.wos_api_key.get_secret_value()


def get_scanr_credentials() -> tuple[str, str]:
    """Identifiants de l'API ScanR, `("", "")` si l'un des deux manque."""
    user, password = settings.scanr_username, settings.scanr_password.get_secret_value()
    if user and password:
        return user, password
    return "", ""


def source_credentials_missing(source: str) -> str | None:
    """Motif de l'absence des identifiants d'API d'une source, ou `None` si la source est utilisable.

    `access_source` la consulte avant tout appel à une API tierce, et saute avec un avertissement un accès qui a un motif. HAL, theses.fr, doi.org et DOAJ sont des API publiques. L'adresse polite pool compte comme un identifiant : Crossref, DataCite et Unpaywall l'exigent, et OpenAlex l'accepte à défaut de clé d'API.
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
