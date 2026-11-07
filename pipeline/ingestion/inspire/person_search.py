"""Moissonnage d'INSPIRE-HEP par ORCID : tâche `harvest_by_person.inspire`.

La recherche cible les ORCID des auteurs (`authors.ids.value`), sur les années du moissonnage.
"""

from __future__ import annotations

from domain.persons.identifiers import PersonIdentifierType
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.common.person_search import (
    Identifiers,
    PersonSearchHarvester,
)
from pipeline.ingestion.inspire.api import InspireClient


def build_orcid_query(orcids: list[str], first_year: int, last_year: int) -> str:
    """Construit la requête INSPIRE : fiches datées de `first_year` à `last_year`, avec un auteur identifié par l'un des ORCID."""
    clauses = " or ".join(f'authors.ids.value:"{orcid}"' for orcid in orcids)
    return f"({clauses}) and date {first_year}->{last_year}"


class InspirePersonHarvester(PersonSearchHarvester[InspireClient]):
    """Fiches INSPIRE-HEP des personnes RH, cherchées par ORCID."""

    SOURCE = "inspire"
    DOCUMENT = "fiche"
    FEMININE = True

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
        )
