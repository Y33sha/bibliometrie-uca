"""Moissonnage de ScanR par identifiant de personne : tâche `harvest_by_person.scanr`.

Interroge l'index Elasticsearch avec une clause `should` qui réunit l'IdRef des auteurs (`authors.person`, sous la forme `idref<IdRef>`) et leur ORCID (`authors.denormalized.orcid`), bornée par l'année. La pagination suit `search_after`, sur le tri par identifiant.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import ClassVar

from domain.persons.identifiers import PersonIdentifierType
from domain.types import JsonValue, as_mapping, as_sequence, at_path
from pipeline.ingestion.api_params import SCANR_PER_PAGE
from pipeline.ingestion.common.person_search import (
    Identifiers,
    PersonSearchHarvester,
    PersonSearchPage,
)
from pipeline.ingestion.scanr.api import ScanrClient


def build_identifiers_query(
    identifiers: Identifiers, first_year: int, last_year: int, search_after: list[JsonValue] | None
) -> Mapping[str, JsonValue]:
    """Requête Elasticsearch d'une page : documents parus de `first_year` à `last_year` dont un auteur a l'un des identifiants."""
    should: list[JsonValue] = []
    if idrefs := identifiers.get(PersonIdentifierType.IDREF):
        should.append({"terms": {"authors.person.keyword": [f"idref{v}" for v in idrefs]}})
    if orcids := identifiers.get(PersonIdentifierType.ORCID):
        should.append({"terms": {"authors.denormalized.orcid.keyword": list(orcids)}})
    query: dict[str, JsonValue] = {
        "size": SCANR_PER_PAGE,
        "track_total_hits": False,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"year": {"gte": first_year, "lte": last_year}}},
                    {"bool": {"should": should, "minimum_should_match": 1}},
                ]
            }
        },
        "sort": [{"id.keyword": "asc"}],
    }
    if search_after:
        query["search_after"] = search_after
    return query


class ScanrPersonHarvester(PersonSearchHarvester[ScanrClient]):
    """Documents ScanR des personnes RH, cherchés par IdRef et ORCID."""

    SOURCE = "scanr"
    BATCH_SIZE: ClassVar[int] = 30

    def fetch_page(
        self,
        identifiers: Identifiers,
        years: tuple[int, int],
        next_token: str | None,
        label: str,  # noqa: ARG002
    ) -> PersonSearchPage:
        search_after = json.loads(next_token) if next_token else None
        data = self._client.fetch_page(build_identifiers_query(identifiers, *years, search_after))
        hits = [as_mapping(h) for h in as_sequence(at_path(data, "hits").get("hits"))]
        records = [as_mapping(h.get("_source")) for h in hits]
        # Le jeton de la page suivante est la clé de tri du dernier document, sérialisée.
        following = json.dumps(hits[-1].get("sort")) if hits else None
        return PersonSearchPage(records=records, next_token=following)
