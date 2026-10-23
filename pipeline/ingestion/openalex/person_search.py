"""Moissonnage d'OpenAlex par ORCID : tâche `harvest_by_person.openalex`.

Interroge `/works` avec le filtre `authorships.author.orcid`, qui réunit par OU les ORCID d'un lot, borné par `publication_year`. La pagination suit le curseur (`next_cursor`).
"""

from __future__ import annotations

from typing import ClassVar

from domain.persons.identifiers import PersonIdentifierType
from domain.types import as_mapping, as_sequence, as_str, at_path
from pipeline.ingestion.common.person_search import (
    Identifiers,
    PersonSearchHarvester,
    PersonSearchPage,
)
from pipeline.ingestion.openalex.api import OpenalexClient


def build_orcid_filter(orcids: list[str], first_year: int, last_year: int) -> str:
    """Valeur du paramètre `filter` : works d'un des ORCID, parus de `first_year` à `last_year`."""
    return f"authorships.author.orcid:{'|'.join(orcids)},publication_year:{first_year}-{last_year}"


class OpenalexPersonHarvester(PersonSearchHarvester[OpenalexClient]):
    """Works OpenAlex des personnes RH, cherchés par ORCID."""

    SOURCE = "openalex"
    # OpenAlex accepte jusqu'à 100 valeurs réunies par OU dans un filtre.
    BATCH_SIZE: ClassVar[int] = 50

    def fetch_page(
        self,
        identifiers: Identifiers,
        years: tuple[int, int],
        next_token: str | None,
        label: str,
    ) -> PersonSearchPage:
        orcids = identifiers[PersonIdentifierType.ORCID]
        data = self._client.fetch_filtered_page(
            build_orcid_filter(orcids, *years), next_token or "*", label
        )
        records = [as_mapping(w) for w in as_sequence(data.get("results"))]
        following = as_str(at_path(data, "meta").get("next_cursor"))
        return PersonSearchPage(records=records, next_token=following if records else None)
