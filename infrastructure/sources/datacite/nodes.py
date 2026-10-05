"""Éléments communs aux accès à l'API DataCite : en-têtes de requête et DOI d'un nœud JSON:API."""

from collections.abc import Mapping

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_str
from infrastructure.sources.config import get_polite_pool_email
from infrastructure.sources.polite_pool import build_user_agent


def api_headers() -> dict[str, str]:
    """En-têtes d'une requête DataCite : `User-Agent` du polite pool, réponse JSON:API."""
    return {
        "User-Agent": build_user_agent(get_polite_pool_email()),
        "Accept": "application/vnd.api+json",
    }


def record_doi(record: Mapping[str, JsonValue]) -> str | None:
    """DOI normalisé d'un nœud JSON:API `data` : `attributes.doi`, sinon `id` (les deux portent le DOI). Passé par `clean_doi` (normalisation partagée). `None` si aucun des deux n'est présent ou exploitable."""
    attributes = record.get("attributes")
    doi_raw = as_str(as_mapping(attributes).get("doi")) or as_str(record.get("id")) or ""
    return clean_doi(doi_raw)
