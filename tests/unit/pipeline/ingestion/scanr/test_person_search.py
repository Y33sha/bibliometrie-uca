"""Moissonnage de ScanR par identifiant de personne : clause réunissant IdRef et ORCID, pagination search_after."""

from __future__ import annotations

from unittest.mock import MagicMock

from domain.persons.identifiers import PersonIdentifierType as T
from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.scanr.person_search import ScanrPersonHarvester, build_identifiers_query
from tests.helpers.harvesters import arguments_du_run, moissonneur


def _hit(scanr_id: str) -> dict:
    return {"_source": {"id": scanr_id}, "sort": [scanr_id]}


def test_clause_reunissant_idref_et_orcid():
    query = build_identifiers_query(
        {T.IDREF: ["08397086X"], T.ORCID: ["0000-0002-6454-271X"]}, 2017, 2026, None
    )
    filters = query["query"]["bool"]["filter"]
    assert filters[0] == {"range": {"year": {"gte": 2017, "lte": 2026}}}
    assert filters[1]["bool"]["should"] == [
        {"terms": {"authors.person.keyword": ["idref08397086X"]}},
        {"terms": {"authors.denormalized.orcid.keyword": ["0000-0002-6454-271X"]}},
    ]
    assert "search_after" not in query


def test_suit_la_cle_de_tri_jusqu_a_la_page_vide(identifiants_rh, ecritures):
    identifiants_rh([{T.IDREF: ["08397086X"]}])
    client = MagicMock()
    client.fetch_page.side_effect = [
        {"hits": {"hits": [_hit("doi10.1/a"), _hit("hal-2")]}},
        {"hits": {"hits": []}},
    ]

    moissonneur(ScanrPersonHarvester, client).run(arguments_du_run())

    assert [e.source_id for e in ecritures] == ["doi10.1/a", "hal-2"]
    assert {e.entry_mode for e in ecritures} == {StagingEntryMode.PERSON_IDENTIFIER}
    second = client.fetch_page.call_args_list[1].args[0]
    assert second["search_after"] == ["hal-2"]
