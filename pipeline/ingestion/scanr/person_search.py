"""Moissonnage de ScanR par identifiant de personne : tâche `harvest_by_person.scanr`.

La requête à l'index Elasticsearch contient une clause `should` réunissant l'IdRef des auteurs (`authors.person`, sous la forme `idref<IdRef>`) et leur ORCID (`authors.denormalized.orcid`), bornée par l'année. La pagination suit `search_after`, sur le tri par identifiant.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from domain.persons.identifiers import PersonIdentifierType
from domain.types import JsonValue
from pipeline.ingestion.api_params import SCANR_PER_PAGE
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.common.person_search import (
    Identifiers,
    PersonSearchHarvester,
)
from pipeline.ingestion.scanr.api import ScanrClient, hits_page, search_after


def build_identifiers_query(
    identifiers: Identifiers, first_year: int, last_year: int, search_after: list[JsonValue] | None
) -> Mapping[str, JsonValue]:
    """Construit la requête Elasticsearch d'une page : documents parus de `first_year` à `last_year`, avec un auteur identifié par l'un des identifiants."""
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
    ) -> Page:
        query = build_identifiers_query(identifiers, *years, search_after(next_token))
        return hits_page(self._client.fetch_page(query))
