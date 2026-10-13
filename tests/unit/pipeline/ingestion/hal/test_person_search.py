"""Moissonnage de HAL par identifiant de personne : filtre réunissant ORCID, idHAL et IdRef, pagination par cursorMark."""

from __future__ import annotations

from unittest.mock import MagicMock

from domain.persons.identifiers import PersonIdentifierType as T
from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.hal.person_search import HalPersonExtractor, build_identifiers_fq
from tests.helpers.extractors import arguments_du_run, extracteur


def _page(docs: list[dict], cursor: str) -> dict:
    return {"response": {"docs": docs}, "nextCursorMark": cursor}


def test_filtre_reunissant_les_types_d_identifiant():
    fq = build_identifiers_fq(
        {T.ORCID: ["0000-0001-2345-6789"], T.IDHAL: ["jean-dupont", "marie-durand"], T.IDREF: []}
    )
    assert fq == (
        'authORCIDIdExt_s:("0000-0001-2345-6789") OR authIdHal_s:("jean-dupont" OR "marie-durand")'
    )


def test_suit_le_marqueur_jusqu_a_sa_repetition(identifiants_rh, ecritures):
    identifiants_rh([{T.IDHAL: ["jean-dupont"], T.IDREF: ["070463980"]}])
    client = MagicMock()
    client.fetch_page_cursor.side_effect = [
        _page([{"halId_s": "hal-1", "doiId_s": "10.1/A"}, {"halId_s": "hal-2"}], "c1"),
        _page([{"halId_s": "hal-3"}], "c1"),
    ]

    extracteur(HalPersonExtractor, client).run(arguments_du_run())

    assert [(e.source_id, e.doi) for e in ecritures] == [
        ("hal-1", "10.1/a"),
        ("hal-2", None),
        ("hal-3", None),
    ]
    assert {e.entry_mode for e in ecritures} == {StagingEntryMode.PERSON_IDENTIFIER}
    query, fq, cursor = client.fetch_page_cursor.call_args_list[0].args
    assert query == "producedDateY_i:[2024 TO 2025]"
    assert fq == 'authIdHal_s:("jean-dupont") OR authIdRefIdExt_s:("070463980")'
    assert [c.args[2] for c in client.fetch_page_cursor.call_args_list] == ["*", "c1"]
