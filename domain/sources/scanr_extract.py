"""Constantes et helpers purs pour l'extraction ScanR.

Tout ce qui peut être consommé par l'orchestrateur applicatif sans
toucher à `infrastructure` : timing de rate-limit, construction de
requête Elasticsearch, parsing des hits.

`SCANR_PER_PAGE` est dupliqué ici (et reste dans
`infrastructure.sources.api_limits` pour les consommateurs infra-only).
"""

from __future__ import annotations

from typing import Any

from domain.publications.identifiers import clean_doi

# ── Rate-limit / pagination ────────────────────────────────────────

SCANR_DELAY = 0.3
"""Pause entre deux requêtes consécutives à ScanR (s).

Elasticsearch public, courtoisie.
"""

SCANR_PER_PAGE = 200
"""Taille des batchs scroll/search_after."""


# ── Requête Elasticsearch ─────────────────────────────────────────


def build_query(
    year: int,
    affiliation_ids: list[str],
    search_after: list[Any] | None = None,
) -> dict[str, Any]:
    """Construit la requête Elasticsearch pour ScanR.

    `bool.must` filtre l'année (term exact), `bool.should` matche au
    moins une affiliation (clause OR via `minimum_should_match: 1`).
    Le tri par `id.keyword` ASC permet la pagination `search_after`.
    """
    query: dict[str, Any] = {
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


# ── Parsing de documents ───────────────────────────────────────────


def extract_scanr_id(doc: dict[str, Any]) -> str:
    """Extrait l'identifiant ScanR (champ `id` du document)."""
    return doc.get("id", "")


def extract_doi(doc: dict[str, Any]) -> str | None:
    """Extrait le premier DOI nettoyé depuis `externalIds`."""
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "doi":
            return clean_doi(ext.get("id"))
    return None
