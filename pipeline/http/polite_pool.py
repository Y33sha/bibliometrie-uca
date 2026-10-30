"""Adresse du polite pool et `User-Agent` des requêtes sortantes.

Crossref, DataCite et doi.org lisent l'adresse dans le `User-Agent`, OpenAlex et Unpaywall dans un paramètre de requête (`mailto`, `email`) posé par leur adaptateur. L'adresse vient de l'environnement du processus.
"""

from infrastructure.settings import settings

_PRODUCT = "BibliometrieUCA-pipeline/1.0"


def get_polite_pool_email_optional() -> str | None:
    """Renvoie l'adresse annoncée en polite pool, ou `None` si elle n'est pas configurée. Sert à OpenAlex, dont l'accès au polite pool peut aussi passer par une clé d'API."""
    return settings.polite_pool_email or None


def get_polite_pool_email() -> str:
    """Renvoie l'adresse annoncée en polite pool aux API externes (Crossref, DataCite, Unpaywall, …).

    Lève `RuntimeError` si l'adresse manque. Une adresse inventée expose à un blocage côté serveur.
    """
    email = get_polite_pool_email_optional()
    if email is not None:
        return email
    raise RuntimeError(
        "POLITE_POOL_EMAIL manquant dans l'environnement — requis pour le polite pool "
        "des API (Crossref, DataCite, Unpaywall, etc.)."
    )


def polite_user_agent() -> str:
    """Renvoie le `User-Agent` avec l'adresse du polite pool : `BibliometrieUCA-pipeline/1.0 (mailto:<email>)`. Lève `RuntimeError` si l'adresse manque."""
    return f"{_PRODUCT} (mailto:{get_polite_pool_email()})"


def default_user_agent() -> str:
    """Renvoie le `User-Agent` des API publiques : avec l'adresse du polite pool si elle est configurée, sinon le seul nom du produit."""
    email = get_polite_pool_email_optional()
    return f"{_PRODUCT} (mailto:{email})" if email else _PRODUCT
