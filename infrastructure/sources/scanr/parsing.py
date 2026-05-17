"""Pure functions de parsing pour l'extraction ScanR.

Vit à côté de `extract_scanr.py` (wiring HTTP / pagination
search_after). Ne fait aucun I/O.
"""

from __future__ import annotations

from infrastructure.api_limits import SCANR_PER_PAGE
from infrastructure.sources.common import clean_doi


def build_query(year: int, affiliation_ids: list[str], search_after: list | None = None) -> dict:
    """Construit la requête Elasticsearch pour ScanR.

    `bool.must` filtre l'année (term exact), `bool.should` matche au
    moins une affiliation (clause OR via `minimum_should_match: 1`).
    Le tri par `id.keyword` ASC permet la pagination `search_after`.
    """
    query: dict = {
        "size": SCANR_PER_PAGE,
        "track_total_hits": True,
        "query": {
            "bool": {
                "must": [{"term": {"year": year}}],
                "should": [{"term": {"affiliations.id.keyword": aid}} for aid in affiliation_ids],
                "minimum_should_match": 1,
            }
        },
        "sort": [{"id.keyword": "asc"}],
    }
    if search_after:
        query["search_after"] = search_after
    return query


def extract_scanr_id(doc: dict) -> str:
    """Extrait l'identifiant ScanR (champ `id` du document)."""
    return doc.get("id", "")


def extract_doi(doc: dict) -> str | None:
    """Extrait le premier DOI nettoyé depuis `externalIds`."""
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "doi":
            return clean_doi(ext.get("id"))
    return None
