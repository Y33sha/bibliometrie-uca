"""Moissonnage d'OpenAlex par ORCID : filtre, lots de 50, identifiant OpenAlex en staging, auteurs tronqués."""

from __future__ import annotations

from unittest.mock import MagicMock

from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.openalex.person_search import OpenalexPersonExtractor, build_orcid_filter
from tests.helpers.extractors import arguments_du_run, extracteur

_LOT = OpenalexPersonExtractor.BATCH_SIZE


def _page(works: list[dict], cursor: str | None) -> dict:
    return {"results": works, "meta": {"next_cursor": cursor}}


def test_filtre_sur_les_orcid_et_la_plage_d_annees():
    assert build_orcid_filter(["0000-0001-2345-6789", "0000-0002-0000-000X"], 2017, 2026) == (
        "authorships.author.orcid:0000-0001-2345-6789|0000-0002-0000-000X,"
        "publication_year:2017-2026"
    )


def test_un_lot_par_tranche_de_50_orcid(identifiants_rh, ecritures):
    identifiants_rh([f"0000-0000-0000-{i:04d}" for i in range(_LOT + 1)])
    client = MagicMock()
    client.fetch_filtered_page.return_value = _page([], None)

    extracteur(OpenalexPersonExtractor, client).run(arguments_du_run())

    filters = [c.args[0] for c in client.fetch_filtered_page.call_args_list]
    assert len(filters) == 2
    assert filters[0].count("|") == _LOT - 1
    assert all(f.endswith("publication_year:2024-2025") for f in filters)


def test_work_ecrit_sous_son_identifiant_openalex(identifiants_rh, ecritures):
    identifiants_rh(["0000-0001-2345-6789"])
    tronque = {
        "id": "https://openalex.org/W2",
        "doi": "https://doi.org/10.1/B",
        "authorships": [{}] * 100,
    }
    client = MagicMock()
    client.fetch_filtered_page.side_effect = [
        _page([{"id": "https://openalex.org/W1", "doi": None}], "c1"),
        _page([tronque, {"id": "https://openalex.org/W1"}, {}], "c2"),
        _page([], None),
    ]

    extracteur(OpenalexPersonExtractor, client).run(arguments_du_run())

    assert [(e.source_id, e.doi) for e in ecritures] == [("W1", None), ("W2", "10.1/b")]
    assert [e.authors_truncated for e in ecritures] == [False, True]
    assert {e.entry_mode for e in ecritures} == {StagingEntryMode.PERSON_IDENTIFIER}
    assert [c.args[1] for c in client.fetch_filtered_page.call_args_list] == ["*", "c1", "c2"]
