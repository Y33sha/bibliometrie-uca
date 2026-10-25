"""Moissonnage de HAL par identifiant de personne : tâche `harvest_by_person.hal`.

Interroge l'API de recherche avec un filtre Solr qui réunit les ORCID (`authORCIDIdExt_s`), idHAL (`authIdHal_s`) et IdRef (`authIdRefIdExt_s`) des personnes du lot, borné par l'année de production. La pagination suit `cursorMark`.
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
from pipeline.ingestion.hal.api import HalClient
from pipeline.ingestion.hal.harvest import build_query

# Champ Solr de chaque type d'identifiant.
_FIELDS = {
    PersonIdentifierType.ORCID: "authORCIDIdExt_s",
    PersonIdentifierType.IDHAL: "authIdHal_s",
    PersonIdentifierType.IDREF: "authIdRefIdExt_s",
}


def build_identifiers_fq(identifiers: Identifiers) -> str:
    """Filtre Solr : un auteur a l'un des identifiants, tous types réunis par OU."""
    clauses = [
        f"{_FIELDS[id_type]}:({' OR '.join(f'"{v}"' for v in values)})"
        for id_type, values in identifiers.items()
        if id_type in _FIELDS and values
    ]
    return " OR ".join(clauses)


class HalPersonHarvester(PersonSearchHarvester[HalClient]):
    """Enregistrements HAL des personnes qui ont une fiche RH, cherchées par ORCID, idHAL et IdRef."""

    SOURCE = "hal"
    BATCH_SIZE: ClassVar[int] = 30

    def fetch_page(
        self,
        identifiers: Identifiers,
        years: tuple[int, int],
        next_token: str | None,
        label: str,  # noqa: ARG002
    ) -> PersonSearchPage:
        cursor = next_token or "*"
        data = self._client.fetch_page_cursor(
            build_query(list(years)), build_identifiers_fq(identifiers), cursor
        )
        records = [as_mapping(d) for d in as_sequence(at_path(data, "response").get("docs"))]
        following = as_str(data.get("nextCursorMark"))
        # Solr rend le marqueur reçu une fois les résultats épuisés.
        done = not records or not following or following == cursor
        return PersonSearchPage(records=records, next_token=None if done else following)
