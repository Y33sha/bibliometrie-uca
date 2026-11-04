"""Métadonnées des revues dans OpenAlex (`check_serials_in_openalex`) : identifiant OpenAlex, type et listes de chaque revue."""

import logging
from collections.abc import Sequence
from datetime import date

import pytest
from sqlalchemy import text

from domain.sources.openalex import OpenAlexSource, OpenAlexSourceList
from pipeline.transformation.publishing.serials.check_serials_in_openalex import (
    run_check_serials_in_openalex,
)
from tests.integration.helpers.serials import insert_serial, insert_serial_issn
from tests.integration.helpers.sources import insert_source_record

_LOG = logging.getLogger("test_check_serials_in_openalex")

_NATURE = OpenAlexSource(
    "S137773608",
    ("0028-0836", "1476-4687"),
    "journal",
    ("cwts-core", "doyens", "poland-200"),
    449150,
)
_JAMA = OpenAlexSource(
    "S172573765", ("0002-9955", "0098-7484", "1538-3598"), "journal", ("doyens",), 120000
)


class _OpenAlex:
    """OpenAlex simulé : sources connues, valeurs dont la requête échoue, requêtes reçues."""

    def __init__(self, *sources: OpenAlexSource, failing: Sequence[str] = ()) -> None:
        self.sources = sources
        self.failing = set(failing)
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def fetch(self, key: str, values: Sequence[str]) -> list[OpenAlexSource] | None:
        self.calls.append((key, tuple(values)))
        if self.failing & set(values):
            return None
        if key == "issn":
            return [s for s in self.sources if set(s.issns) & set(values)]
        return [s for s in self.sources if s.id in values]


def _run(conn, openalex: _OpenAlex, source_lists: list[OpenAlexSourceList] | None = None):
    return run_check_serials_in_openalex(
        conn,
        _LOG,
        fetch_sources=openalex.fetch,
        fetch_source_lists=lambda: source_lists,
        recheck_after_days=7,
    )


def _serial(conn, title: str, *issns: str, publications: int = 0, **columns) -> int:
    serial_id = insert_serial(conn, title, **columns)
    for issn in issns:
        insert_serial_issn(conn, serial_id, issn=issn)
    conn.execute(
        text("UPDATE serials SET publication_count = :n WHERE id = :id"),
        {"n": publications, "id": serial_id},
    )
    return serial_id


def _state(conn, serial_id: int):
    return conn.execute(
        text("""
            SELECT openalex_id, serial_type::text AS serial_type,
                   openalex_checked_at IS NOT NULL AS searched,
                   ARRAY(SELECT list_code FROM serial_list_entries
                         WHERE serial_id = :id ORDER BY list_code) AS lists
            FROM serials WHERE id = :id
        """),
        {"id": serial_id},
    ).one()


def _mark_searched_now(conn, serial_id: int) -> None:
    conn.execute(
        text("UPDATE serials SET openalex_checked_at = now() WHERE id = :id"), {"id": serial_id}
    )


@pytest.fixture
def conn(sa_sync_conn):
    return sa_sync_conn


def test_la_revue_recoit_sa_source_son_type_et_ses_listes_retenues(conn):
    nature = _serial(conn, "Nature", "0028-0836")
    _run(conn, _OpenAlex(_NATURE))
    state = _state(conn, nature)
    assert (state.openalex_id, state.serial_type, state.searched) == ("S137773608", "journal", True)
    assert state.lists == ["cwts-core", "doyens"]


def test_l_identifiant_partage_va_a_la_revue_la_plus_publiee_et_les_listes_aux_deux(conn):
    """Cas réel : OpenAlex réunit *JAMA* et son ancien titre, « Journal of the American Medical Association »."""
    old_title = _serial(conn, "Journal of the American Medical Association", "0002-9955")
    jama = _serial(conn, "JAMA", "0098-7484", "1538-3598", publications=33)
    _run(conn, _OpenAlex(_JAMA))
    assert (_state(conn, jama).openalex_id, _state(conn, old_title).openalex_id) == (
        "S172573765",
        None,
    )
    assert _state(conn, jama).lists == _state(conn, old_title).lists == ["doyens"]


def test_une_revue_non_cherchee_perd_l_identifiant_au_profit_d_une_revue_plus_publiee(conn):
    old_title = _serial(
        conn, "Journal of the American Medical Association", "0002-9955", openalex_id="S172573765"
    )
    _mark_searched_now(conn, old_title)
    jama = _serial(conn, "JAMA", "0098-7484", publications=33)
    _run(conn, _OpenAlex(_JAMA))
    assert (_state(conn, jama).openalex_id, _state(conn, old_title).openalex_id) == (
        "S172573765",
        None,
    )


def test_une_revue_non_cherchee_garde_l_identifiant_face_a_une_revue_moins_publiee(conn):
    jama = _serial(conn, "JAMA", "0098-7484", publications=33, openalex_id="S172573765")
    _mark_searched_now(conn, jama)
    old_title = _serial(conn, "Journal of the American Medical Association", "0002-9955")
    _run(conn, _OpenAlex(_JAMA))
    assert (_state(conn, jama).openalex_id, _state(conn, old_title).openalex_id) == (
        "S172573765",
        None,
    )
    assert _state(conn, old_title).lists == ["doyens"]


def test_la_revue_absente_d_openalex_perd_son_identifiant(conn):
    serial_id = _serial(conn, "Revue locale", "2999-0008", openalex_id="S1")
    _run(conn, _OpenAlex())
    state = _state(conn, serial_id)
    assert (state.openalex_id, state.searched, state.lists) == (None, True, [])


def test_un_lot_en_echec_laisse_la_revue_a_chercher(conn):
    serial_id = _serial(conn, "Nature", "0028-0836", openalex_id="S137773608")
    _run(conn, _OpenAlex(_NATURE, failing=["0028-0836"]))
    state = _state(conn, serial_id)
    assert (state.openalex_id, state.searched) == ("S137773608", False)


def test_une_revue_cherchee_recemment_attend_le_delai(conn):
    serial_id = _serial(conn, "Nature", "0028-0836")
    _mark_searched_now(conn, serial_id)
    openalex = _OpenAlex(_NATURE)
    _run(conn, openalex)
    assert openalex.calls == []
    assert _state(conn, serial_id).openalex_id is None


def test_la_recherche_reecrit_les_appartenances(conn):
    serial_id = _serial(conn, "Nature", "0028-0836")
    conn.execute(
        text("INSERT INTO serial_list_entries (serial_id, list_code) VALUES (:id, 'medline')"),
        {"id": serial_id},
    )
    _run(conn, _OpenAlex(_NATURE))
    assert _state(conn, serial_id).lists == ["cwts-core", "doyens"]


def test_le_type_saisi_a_la_main_reste(conn):
    serial_id = _serial(conn, "Nature", "0028-0836", serial_type="media")
    conn.execute(
        text("UPDATE serials SET manual_fields = ARRAY['serial_type'] WHERE id = :id"),
        {"id": serial_id},
    )
    _run(conn, _OpenAlex(_NATURE))
    assert _state(conn, serial_id).serial_type == "media"


def test_la_revue_sans_issn_prend_la_source_de_ses_enregistrements_openalex_sans_issn(conn):
    serial_id = _serial(conn, "ESAFORM 2021")
    for source_id, journal in (
        ("W1", {"title": "ESAFORM 2021", "openalex_id": "S5"}),
        ("W2", {"title": "ESAFORM 2021", "openalex_id": "S5"}),
        ("W3", {"title": "ESAFORM 2021", "openalex_id": "S6"}),
        (
            "W4",
            {"title": "ESAFORM", "openalex_id": "S7", "issns": [{"issn": "1234-5679"}]},
        ),
        ("W5", {"title": "ESAFORM", "openalex_id": "S7", "issns": [{"issn": "1234-5679"}]}),
        ("W6", {"title": "ESAFORM", "openalex_id": "S7", "issns": [{"issn": "1234-5679"}]}),
    ):
        insert_source_record(
            conn,
            source="openalex",
            source_id=source_id,
            serial_id=serial_id,
            biblio={"journal": journal},
        )
    conference = OpenAlexSource("S5", (), "conference", (), 120)
    openalex = _OpenAlex(conference)
    _run(conn, openalex)
    state = _state(conn, serial_id)
    assert (state.openalex_id, state.serial_type) == ("S5", "proceedings")
    assert openalex.calls == [("openalex", ("S5",))]


def test_les_listes_recoivent_organisme_url_et_edition(conn):
    _serial(conn, "Nature", "0028-0836")
    doyens = OpenAlexSourceList(
        "doyens",
        "Conférence des doyens",
        "https://conferencedesdoyensdemedecine.org/",
        date(2026, 10, 1),
    )
    _run(conn, _OpenAlex(_NATURE), [doyens])
    row = conn.execute(
        text("SELECT maintainer, url, edition FROM serial_lists WHERE code = 'doyens'")
    ).one()
    assert tuple(row) == (
        "Conférence des doyens",
        "https://conferencedesdoyensdemedecine.org/",
        date(2026, 10, 1),
    )
