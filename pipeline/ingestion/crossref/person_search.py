"""Moissonnage de Crossref par ORCID : tâche `extract_by_person.crossref`.

Interroge `GET /works` avec le filtre `orcid`, une fois par ORCID du lot : Crossref réunit par OU les filtres de même nom. Les dates de publication bornent la recherche (`from-pub-date`, `until-pub-date`). La pagination suit le curseur (`next-cursor`). Polite pool par le `User-Agent`.
"""

from __future__ import annotations

from collections.abc import Mapping

from domain.persons.identifiers import PersonIdentifierType
from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.http.http_retry import http_request_with_retry
from pipeline.http.polite_pool import build_user_agent, get_polite_pool_email
from pipeline.ingestion.common.person_search import (
    Identifiers,
    PersonSearchExtractor,
    PersonSearchPage,
)

# Documents par page. Une notice de grande collaboration pèse environ 500 Kio, et Crossref refuse une réponse de plus de 100 Mio.
_ROWS = 50


def build_orcid_filter(orcids: list[str], first_year: int, last_year: int) -> str:
    """Valeur du paramètre `filter` : œuvres d'un des ORCID, parues de `first_year` à `last_year`."""
    return ",".join(
        [
            *(f"orcid:{orcid}" for orcid in orcids),
            f"from-pub-date:{first_year}",
            f"until-pub-date:{last_year}",
        ]
    )


class CrossrefClient:
    """Client de `GET /works`."""

    def __init__(self, base_url: str) -> None:
        self._url = f"{base_url}/works"
        self._headers = {"User-Agent": build_user_agent(get_polite_pool_email())}

    def fetch_page(self, filters: str, cursor: str | None, label: str) -> PersonSearchPage:
        """Une page des œuvres que désigne `filters` : la première quand `cursor` est `None`. Une page vide clôt la pagination."""
        data = as_mapping(
            http_request_with_retry(
                "GET",
                self._url,
                params={"filter": filters, "rows": _ROWS, "cursor": cursor or "*"},
                headers=self._headers,
                timeout=120,
                label=label,
            )
        )
        message = as_mapping(data.get("message"))
        records = [as_mapping(item) for item in as_sequence(message.get("items"))]
        following = as_str(message.get("next-cursor"))
        return PersonSearchPage(records=records, next_token=following if records else None)


class CrossrefPersonExtractor(PersonSearchExtractor[CrossrefClient]):
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

    def record_identity(self, record: Mapping[str, JsonValue]) -> tuple[str, str | None] | None:
        doi = clean_doi(as_str(record.get("DOI")))
        return (doi, doi) if doi else None
