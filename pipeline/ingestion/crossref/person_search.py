"""Moissonnage de Crossref par ORCID : tâche `harvest_by_person.crossref`.

Interroge `GET /works` avec le filtre `orcid`, une fois par ORCID du lot : Crossref réunit par OU les filtres de même nom. Les dates de publication bornent la recherche (`from-pub-date`, `until-pub-date`). La pagination suit le curseur (`next-cursor`). Polite pool par le `User-Agent`.
"""

from __future__ import annotations

from domain.persons.identifiers import PersonIdentifierType
from pipeline.ingestion.common.person_search import (
    Identifiers,
    PersonSearchHarvester,
    PersonSearchPage,
)
from pipeline.ingestion.crossref.api import CrossrefClient


def build_orcid_filter(orcids: list[str], first_year: int, last_year: int) -> str:
    """Valeur du paramètre `filter` : œuvres d'un des ORCID, parues de `first_year` à `last_year`."""
    return ",".join(
        [
            *(f"orcid:{orcid}" for orcid in orcids),
            f"from-pub-date:{first_year}",
            f"until-pub-date:{last_year}",
        ]
    )


class CrossrefPersonHarvester(PersonSearchHarvester[CrossrefClient]):
    """Œuvres Crossref des personnes RH, cherchées par ORCID."""

    SOURCE = "crossref"

    def fetch_page(
        self,
        identifiers: Identifiers,
        years: tuple[int, int],
        next_token: str | None,
        label: str,
    ) -> PersonSearchPage:
        orcids = identifiers[PersonIdentifierType.ORCID]
        return self._client.fetch_page(build_orcid_filter(orcids, *years), next_token, label)
