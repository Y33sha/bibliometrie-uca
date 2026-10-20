"""Moissonnage de DataCite par ORCID : requête, lots, documents écrits une fois par run, mode d'entrée."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.common.harvest import ExtractionConfigError
from pipeline.ingestion.datacite.api import DatacitePage
from pipeline.ingestion.datacite.person_search import DatacitePersonExtractor, build_orcid_query
from tests.helpers.extractors import arguments_du_run, extracteur

_LOT = DatacitePersonExtractor.BATCH_SIZE


def test_requete_sur_les_orcid_et_la_plage_d_annees():
    assert build_orcid_query(["0000-0001-2345-6789", "0000-0002-0000-000X"], 2017, 2026) == (
        "publicationYear:[2017 TO 2026] AND creators.nameIdentifiers.nameIdentifier:("
        '"https://orcid.org/0000-0001-2345-6789" OR "https://orcid.org/0000-0002-0000-000X")'
    )


def test_un_lot_par_tranche_d_orcid(identifiants_rh, ecritures):
    identifiants_rh([f"0000-0000-0000-{i:04d}" for i in range(_LOT + 1)])
    client = MagicMock()
    client.fetch_page.return_value = DatacitePage(records=[], next_url=None)

    extracteur(DatacitePersonExtractor, client).run(arguments_du_run())

    queries = [c.args[0] for c in client.fetch_page.call_args_list]
    assert len(queries) == 2
    assert all(q.startswith("publicationYear:[2024 TO 2025]") for q in queries)


def test_document_ramene_par_deux_lots_ecrit_une_fois(identifiants_rh, ecritures):
    identifiants_rh([f"0000-0000-0000-{i:04d}" for i in range(_LOT + 1)])
    client = MagicMock()
    client.fetch_page.side_effect = [
        DatacitePage(records=[{"id": "10.1/a"}, {"id": "10.1/b"}], next_url="https://next/1"),
        DatacitePage(records=[{"id": "10.1/c"}], next_url=None),
        DatacitePage(records=[{"id": "10.1/a"}, {"id": ""}], next_url=None),
    ]

    metrics = extracteur(DatacitePersonExtractor, client).run(arguments_du_run())

    assert [e.source_id for e in ecritures] == ["10.1/a", "10.1/b", "10.1/c"]
    assert {e.entry_mode for e in ecritures} == {StagingEntryMode.PERSON_IDENTIFIER}
    assert client.fetch_page.call_args_list[1].args[1] == "https://next/1"
    assert metrics.new == 3


def test_sans_orcid_la_source_n_est_pas_configuree(identifiants_rh):
    identifiants_rh([])
    with pytest.raises(ExtractionConfigError):
        extracteur(DatacitePersonExtractor, MagicMock()).run(arguments_du_run())
