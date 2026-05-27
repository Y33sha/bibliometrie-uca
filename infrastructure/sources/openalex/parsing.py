"""Parsing pur des works OpenAlex (sans I/O).

Partagé par l'adapter d'extraction (`extract_openalex`) et l'adapter
fetch-missing-doi (`fetch_missing_doi`) : ne dépend que du format JSON
OpenAlex, ni de la connexion ni de l'auth.
"""

from __future__ import annotations

from typing import Any

from domain.publications.identifiers import clean_doi


def extract_openalex_id(work: dict[str, Any]) -> str:
    """Extrait l'ID OpenAlex court (ex: `W2741809807`).

    L'API retourne l'ID sous forme d'URL complète
    (`https://openalex.org/W...`) ; on garde uniquement le préfixe court
    pour servir de `source_id` en staging.
    """
    return work["id"].replace("https://openalex.org/", "")


def extract_doi(work: dict[str, Any]) -> str | None:
    """Extrait le DOI nettoyé d'un work OpenAlex (sans préfixe URL)."""
    return clean_doi(work.get("doi"))
