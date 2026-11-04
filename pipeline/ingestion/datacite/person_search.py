"""Moissonnage de DataCite par ORCID : tâche `harvest_by_person.datacite`.

La requête `GET /dois` cible les ORCID des créateurs (`creators.nameIdentifiers.nameIdentifier`).
"""

from __future__ import annotations

from domain.persons.identifiers import PersonIdentifierType, orcid_uri
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.common.person_search import (
    Identifiers,
    PersonSearchHarvester,
)
from pipeline.ingestion.datacite.api import DataciteClient

_PAGE_SIZE = 25
"""Documents par page. Un document de grande collaboration compte un millier de créateurs (environ 200 Kio)."""


def build_orcid_query(orcids: list[str], first_year: int, last_year: int) -> str:
    """Construit la requête `query` DataCite : DOI publiés de `first_year` à `last_year`, avec un créateur identifié par l'un des ORCID."""
    clauses = " OR ".join(f'"{orcid_uri(orcid)}"' for orcid in orcids)
    return (
        f"publicationYear:[{first_year} TO {last_year}] "
        f"AND creators.nameIdentifiers.nameIdentifier:({clauses})"
    )


class DatacitePersonHarvester(PersonSearchHarvester[DataciteClient]):
    """DOI DataCite des personnes RH, cherchés par ORCID."""

    SOURCE = "datacite"

    def fetch_page(
        self,
        identifiers: Identifiers,
        years: tuple[int, int],
        next_token: str | None,
        label: str,
    ) -> Page:
        return self._client.fetch_page(
            build_orcid_query(identifiers[PersonIdentifierType.ORCID], *years),
            next_token,
            label,
            page_size=_PAGE_SIZE,
        )
