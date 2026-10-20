"""Moissonnage de DataCite par ORCID : tâche `extract_by_person.datacite`.

Interroge `GET /dois` sur les ORCID des créateurs (`creators.nameIdentifiers.nameIdentifier`).
"""

from __future__ import annotations

from collections.abc import Mapping

from domain.persons.identifiers import PersonIdentifierType, orcid_uri
from domain.types import JsonValue
from pipeline.ingestion.common.person_search import (
    Identifiers,
    PersonSearchExtractor,
    PersonSearchPage,
)
from pipeline.ingestion.datacite.api import DataciteClient
from pipeline.ingestion.datacite.fields import record_doi

# Documents par page. Une notice de grande collaboration compte un millier de créateurs (environ 200 Kio).
_PAGE_SIZE = 25


def build_orcid_query(orcids: list[str], first_year: int, last_year: int) -> str:
    """Requête `query` DataCite : DOI publiés de `first_year` à `last_year` dont un créateur a l'un des ORCID."""
    clauses = " OR ".join(f'"{orcid_uri(orcid)}"' for orcid in orcids)
    return (
        f"publicationYear:[{first_year} TO {last_year}] "
        f"AND creators.nameIdentifiers.nameIdentifier:({clauses})"
    )


class DatacitePersonExtractor(PersonSearchExtractor[DataciteClient]):
    """DOI DataCite des personnes RH, cherchés par ORCID."""

    SOURCE = "datacite"

    def fetch_page(
        self,
        identifiers: Identifiers,
        years: tuple[int, int],
        next_token: str | None,
        label: str,
    ) -> PersonSearchPage:
        page = self._client.fetch_page(
            build_orcid_query(identifiers[PersonIdentifierType.ORCID], *years),
            next_token,
            label,
            page_size=_PAGE_SIZE,
        )
        return PersonSearchPage(records=page.records, next_token=page.next_url)

    def record_identity(self, record: Mapping[str, JsonValue]) -> tuple[str, str | None] | None:
        doi = record_doi(record)
        return (doi, doi) if doi else None
