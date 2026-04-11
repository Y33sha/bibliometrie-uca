"""Constantes et utilitaires partagés pour l'extraction OpenAlex."""

from extraction.common import clean_doi, compute_hash

BASE_URL = "https://api.openalex.org/works"

SELECT_FIELDS = ",".join([
    "id", "doi", "title", "display_name", "publication_year",
    "publication_date", "type", "language", "primary_location",
    "locations", "authorships", "open_access", "cited_by_count",
    "biblio", "is_retracted",
    "topics", "keywords", "abstract_inverted_index",
])


def extract_openalex_id(work: dict) -> str:
    """Extrait l'ID OpenAlex court (ex: W2741809807)."""
    return work["id"].replace("https://openalex.org/", "")


def extract_doi(work: dict) -> str | None:
    """Extrait le DOI nettoyé (sans préfixe URL)."""
    return clean_doi(work.get("doi"))


def compute_meta_hash(raw_data: dict) -> str:
    """Hash des métadonnées hors authorships.

    Permet de détecter les changements réels (OA status, titre, etc.)
    sans être perturbé par la troncature à 100 auteurs de l'API bulk.
    """
    filtered = {k: v for k, v in raw_data.items() if k != "authorships"}
    return compute_hash(filtered)
