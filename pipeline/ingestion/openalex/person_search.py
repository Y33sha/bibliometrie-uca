"""Moissonnage d'OpenAlex par ORCID : tâche `harvest_by_person.openalex`.

La requête `/works` filtre sur l'ORCID déposé des auteurs (`raw_orcid`), avec les ORCID d'un lot réunis par OU, borné par `publication_year`. La pagination suit le curseur (`next_cursor`).

La normalisation retient seulement l'ORCID déposé (`_extract_openalex_orcid`). L'ORCID de l'auteur désambiguïsé par OpenAlex (`author.orcid`) ramène des works sans l'ORCID déposé de la personne.
"""

from __future__ import annotations

from typing import ClassVar

from domain.persons.identifiers import PersonIdentifierType
from pipeline.ingestion.common.pages import Page
from pipeline.ingestion.common.person_search import (
    Identifiers,
    PersonSearchHarvester,
)
from pipeline.ingestion.openalex.api import OpenalexClient, works_page


def build_orcid_filter(orcids: list[str], first_year: int, last_year: int) -> str:
    """Construit la valeur du paramètre `filter` : works où l'un des ORCID est déposé, parus de `first_year` à `last_year`."""
    return f"authorships.raw_orcid:{'|'.join(orcids)},publication_year:{first_year}-{last_year}"


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
    ) -> Page:
        orcids = identifiers[PersonIdentifierType.ORCID]
        data = self._client.fetch_filtered_page(
            build_orcid_filter(orcids, *years), next_token or "*", label
        )
        return works_page(data)
