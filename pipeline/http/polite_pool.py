"""Adresse du polite pool et `User-Agent` des requêtes sortantes.

Crossref, DataCite et doi.org reconnaissent le polite pool via le header `User-Agent` porteur d'un mailto. OpenAlex et Unpaywall passent par un paramètre de requête (`mailto` / `email`), mécanisme propre à chaque API traité chez son adapter. L'adresse vient de l'environnement du processus.
"""

from infrastructure.settings import settings

_PRODUCT = "BibliometrieUCA-pipeline/1.0"


def get_polite_pool_email_optional() -> str | None:
    """Adresse annoncée en polite pool, ou `None` si elle n'est pas configurée (sans lever).

    Pour les consommateurs qui la traitent comme facultative : OpenAlex, dont l'accès au polite pool peut aussi passer par une clé d'API. Ceux qui l'exigent utilisent `get_polite_pool_email`.
    """
    return settings.polite_pool_email or None


def get_polite_pool_email() -> str:
    """Adresse annoncée en polite pool aux API externes (Crossref, DataCite, Unpaywall, …).

    Lève si elle n'est pas configurée. Une adresse inventée expose à un blocage côté serveur.
    """
    email = get_polite_pool_email_optional()
    if email is not None:
        return email
    raise RuntimeError(
        "POLITE_POOL_EMAIL manquant dans l'environnement — requis pour le polite pool "
        "des API (Crossref, DataCite, Unpaywall, etc.)."
    )


def polite_user_agent() -> str:
    """`User-Agent` porteur de l'adresse du polite pool : `BibliometrieUCA-pipeline/1.0 (mailto:<email>)`.

    Pour les API qui identifient l'appelant par l'adresse : Crossref, DataCite, doi.org. Lève si l'adresse n'est pas configurée.
    """
    return f"{_PRODUCT} (mailto:{get_polite_pool_email()})"


def default_user_agent() -> str:
    """`User-Agent` des API publiques : porteur de l'adresse du polite pool si elle est configurée, le seul nom du produit sinon."""
    email = get_polite_pool_email_optional()
    return f"{_PRODUCT} (mailto:{email})" if email else _PRODUCT
