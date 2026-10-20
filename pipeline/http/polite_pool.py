"""User-Agent courtois (polite pool) pour les API identifiant l'appelant par header.

Crossref, DataCite, doi.org et DOAJ reconnaissent le polite pool via le header `User-Agent` porteur d'un mailto. OpenAlex et Unpaywall passent par un paramètre de requête (`mailto` / `email`), mécanisme propre à chaque API traité chez son adapter.
"""


def build_user_agent(email: str) -> str:
    """Construit le `User-Agent` polite pool : `BibliometrieUCA-pipeline/1.0 (mailto:<email>)`."""
    return f"BibliometrieUCA-pipeline/1.0 (mailto:{email})"
