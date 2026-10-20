"""User-Agent courtois (polite pool) pour les API identifiant l'appelant par header.

Crossref, DataCite, doi.org et DOAJ reconnaissent le polite pool via le header `User-Agent` porteur d'un mailto. OpenAlex et Unpaywall passent par un paramètre de requête (`mailto` / `email`), mécanisme propre à chaque API traité chez son adapter. L'adresse vient de l'environnement du processus.
"""

from infrastructure.settings import settings


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


def build_user_agent(email: str) -> str:
    """Construit le `User-Agent` polite pool : `BibliometrieUCA-pipeline/1.0 (mailto:<email>)`."""
    return f"BibliometrieUCA-pipeline/1.0 (mailto:{email})"
