"""Moissonnage de Crossref par ORCID : filtre, pagination par curseur, documents écrits une fois par run."""

from __future__ import annotations

import httpx2

from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.crossref.api import CrossrefClient
from pipeline.ingestion.crossref.person_search import (
    CrossrefPersonHarvester,
    build_orcid_filter,
)
from tests.helpers.harvesters import arguments_du_run, moissonneur

_WORKS = "https://api.crossref.org/works"


def _page(dois: list[str], cursor: str) -> httpx2.Response:
    return httpx2.Response(
        200, json={"message": {"items": [{"DOI": d} for d in dois], "next-cursor": cursor}}
    )


def test_filtre_sur_les_orcid_et_la_plage_d_annees():
    assert build_orcid_filter(["0000-0001-2345-6789", "0000-0002-0000-000X"], 2017, 2026) == (
        "orcid:0000-0001-2345-6789,orcid:0000-0002-0000-000X,from-pub-date:2017,until-pub-date:2026"
    )


def test_suit_le_curseur_jusqu_a_la_page_vide(http_mock, identifiants_rh, ecritures):
    identifiants_rh(["0000-0001-2345-6789"])
    route = http_mock.get(_WORKS).mock(
        side_effect=[_page(["10.1/A", "10.1/b"], "c1"), _page(["10.1/c"], "c2"), _page([], "c3")]
    )
    client = CrossrefClient(API_BASE_URLS["crossref"])

    metrics = moissonneur(CrossrefPersonHarvester, client).run(arguments_du_run())

    assert [call.url.params["cursor"] for call in route.calls] == ["*", "c1", "c2"]
    assert route.calls[0].url.params["filter"] == (
        "orcid:0000-0001-2345-6789,from-pub-date:2024,until-pub-date:2025"
    )
    assert [e.source_id for e in ecritures] == ["10.1/a", "10.1/b", "10.1/c"]
    assert {e.entry_mode for e in ecritures} == {StagingEntryMode.PERSON_IDENTIFIER}
    assert metrics.new == 3
