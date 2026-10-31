"""Rattachement des enregistrements sources à leur revue (`attach_serials`) : une revue par ISSN-L, à défaut par identifiant OpenAlex, à défaut par titre."""

import logging

import pytest
from sqlalchemy import text

from domain.merge import MergedEntity
from pipeline.transformation.publishing.serials.attach_serials import (
    run_attach_serials,
    run_sync_issns,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.redirects import redirect_of
from tests.integration.helpers.serials import (
    insert_publisher,
    insert_serial,
    insert_serial_issn,
)
from tests.integration.helpers.sources import insert_source_record

_LOG = logging.getLogger("test_attach_serials")


def _record(conn, source_id: str, *, source: str = "hal", **journal) -> int:
    """Insère un enregistrement source qui décrit la série `journal` (clés de `biblio.journal`)."""
    publisher_id = journal.pop("publisher_id", None)
    corrections = journal.pop("corrections", None)
    serial_id = journal.pop("serial_id", None)
    publication_id = journal.pop("publication_id", None)
    return insert_source_record(
        conn,
        source=source,
        source_id=source_id,
        publication_id=publication_id,
        publisher_id=publisher_id,
        serial_id=serial_id,
        corrections=corrections,
        biblio={"journal": journal} if journal else None,
    )


def _issns(*values: str, linking: str | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [{"issn": v} for v in values]
    if linking:
        rows.append({"issn": linking, "linking": True})
    return rows


def _serial_of(conn, source_record_id: int) -> int | None:
    return conn.execute(
        text("SELECT serial_id FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()


def _attach(conn) -> None:
    run_sync_issns(conn, _LOG)
    run_attach_serials(conn, _LOG)


@pytest.fixture
def conn(sa_sync_conn):
    return sa_sync_conn


def test_les_issn_d_un_meme_issn_l_vont_a_une_revue(conn):
    """Cas réel : Nature en papier et en ligne, réunis par l'ISSN-L du Sudoc."""
    paper = _record(conn, "a", title="Nature", issns=_issns("0028-0836"))
    online = _record(conn, "b", title="Nature (London)", issns=_issns("1476-4687"))
    insert_serial_issn(conn, None, issn="0028-0836", issnl="0028-0836", sudoc_checked=True)
    insert_serial_issn(conn, None, issn="1476-4687", issnl="0028-0836", sudoc_checked=True)
    _attach(conn)
    serial_id = _serial_of(conn, paper)
    assert serial_id is not None
    assert _serial_of(conn, online) == serial_id
    assert (
        conn.execute(
            text("SELECT count(DISTINCT serial_id) FROM serial_issns WHERE issnl = '0028-0836'")
        ).scalar_one()
        == 1
    )


def test_sans_notice_sudoc_l_issn_l_vient_d_openalex(conn):
    openalex = _record(
        conn,
        "W1",
        source="openalex",
        title="Nature",
        issns=_issns("1476-4687", linking="0028-0836"),
    )
    hal = _record(conn, "h1", title="Nature", issns=_issns("1476-4687"))
    _attach(conn)
    assert _serial_of(conn, hal) == _serial_of(conn, openalex) is not None


def test_issn_de_deux_issn_l_departages_par_le_titre(conn):
    """Cas réel : un article de « BMC Family Practice » donne aussi l'ISSN de son titre suivant."""
    family = insert_serial(conn, "BMC Family Practice")
    primary = insert_serial(conn, "BMC Primary Care")
    insert_serial_issn(conn, family, issn="1471-2296", issnl="1471-2296", sudoc_checked=True)
    insert_serial_issn(conn, primary, issn="2731-4553", issnl="2731-4553", sudoc_checked=True)
    record = _record(conn, "a", title="BMC Family Practice", issns=_issns("1471-2296", "2731-4553"))
    _attach(conn)
    assert _serial_of(conn, record) == family


def test_par_titre_la_seule_revue_a_issn_de_meme_titre(conn):
    """Chaque source nomme l'éditeur à sa façon : « INRAE », « Université de Bordeaux »."""
    serial_id = insert_serial(conn, "Frictions")
    insert_serial_issn(conn, serial_id, issn="1298-5724", issnl="1298-5724", sudoc_checked=True)
    issn = _record(
        conn,
        "a",
        title="Frictions",
        issns=_issns("1298-5724"),
        publisher_id=insert_publisher(conn, "INRAE"),
    )
    title_only = _record(
        conn, "b", title="Frictions", publisher_id=insert_publisher(conn, "Université de Bordeaux")
    )
    _attach(conn)
    assert _serial_of(conn, title_only) == _serial_of(conn, issn) == serial_id


def test_titre_sans_revue_a_issn_forme_une_revue_sans_issn(conn):
    """Cas réel : « Edition CdP », « Editions CdP » ou aucun éditeur pour la même série."""
    first = _record(conn, "a", title="Clinic", publisher_id=insert_publisher(conn, "Edition CdP"))
    second = _record(conn, "b", title="CLINIC", publisher_id=insert_publisher(conn, "Editions CdP"))
    no_publisher = _record(conn, "c", title="Clinic")
    _attach(conn)
    assert _serial_of(conn, first) == _serial_of(conn, second) == _serial_of(conn, no_publisher)
    assert _serial_of(conn, first) is not None


def test_titre_abrege_rejoint_la_revue_a_issn_de_sa_publication(conn):
    """Cas réel : HAL abrège « Journal of High Energy Physics » en « JHEP » ; OpenAlex donne l'ISSN."""
    jhep = insert_serial(conn, "Journal of High Energy Physics")
    insert_serial_issn(conn, jhep, issn="1029-8479", issnl="1029-8479", sudoc_checked=True)
    publication = insert_publication(conn, "Article")
    other = insert_publication(conn, "Autre article")
    _record(
        conn,
        "W1",
        source="openalex",
        title="J. High Energ. Phys.",
        issns=_issns("1029-8479"),
        publication_id=publication,
    )
    hal = _record(conn, "h1", title="JHEP", publication_id=publication)
    alone = _record(conn, "h2", title="JHEP", publication_id=other)
    _attach(conn)
    assert _serial_of(conn, hal) == jhep
    assert _serial_of(conn, alone) not in (None, jhep)


def test_decision_de_l_administration(conn):
    target = insert_serial(conn, "Nature")
    insert_serial_issn(conn, target, issn="0028-0836", issnl="0028-0836", sudoc_checked=True)
    conn.execute(
        text(
            "INSERT INTO serial_title_decisions (title_normalized, serial_id)"
            " VALUES ('nature london', :s)"
        ),
        {"s": target},
    )
    record = _record(conn, "a", title="Nature (London)")
    _attach(conn)
    assert _serial_of(conn, record) == target


def test_revue_videe_absorbee_avec_redirection(conn):
    """Le Sudoc réunit sous un ISSN-L l'ISSN d'une seconde revue : ses enregistrements sources rejoignent la première, qui l'absorbe."""
    kept = insert_serial(conn, "Nature")
    absorbed = insert_serial(conn, "Nature online")
    insert_serial_issn(conn, kept, issn="0028-0836", issnl="0028-0836", sudoc_checked=True)
    insert_serial_issn(conn, absorbed, issn="1476-4687", issnl="0028-0836", sudoc_checked=True)
    record = _record(conn, "a", title="Nature", issns=_issns("1476-4687"), serial_id=absorbed)
    _attach(conn)
    assert _serial_of(conn, record) == kept
    assert (
        conn.execute(
            text("SELECT count(*) FROM serials WHERE id = :id"), {"id": absorbed}
        ).scalar_one()
        == 0
    )
    assert redirect_of(conn, MergedEntity.SERIAL, absorbed) == kept


_CORRECTED = {"serial_id": {"raw": None, "corrected_by": "SERIAL_BY_DOI_NAMESPACE"}}


def _serial_and_raw(conn, source_record_id: int):
    return conn.execute(
        text(
            "SELECT serial_id, corrections->'serial_id'->>'raw' AS raw"
            " FROM source_records WHERE id = :id"
        ),
        {"id": source_record_id},
    ).one()


def test_revue_trouvee_devient_la_valeur_d_avant_correction(conn):
    """La correction par l'espace de noms DOI agit seulement sans revue d'avant correction : la revue trouvée l'emporte."""
    corrected = insert_serial(conn, "Revue posée par le DOI")
    record = _record(
        conn, "a", title="Revue de la source", serial_id=corrected, corrections=_CORRECTED
    )
    _attach(conn)
    row = _serial_and_raw(conn, record)
    assert row.serial_id != corrected
    assert int(row.raw) == row.serial_id


def test_sans_revue_trouvee_la_revue_corrigee_reste(conn):
    corrected = insert_serial(conn, "Revue posée par le DOI")
    record = insert_source_record(conn, source_id="a", serial_id=corrected, corrections=_CORRECTED)
    _attach(conn)
    row = _serial_and_raw(conn, record)
    assert (row.serial_id, row.raw) == (corrected, None)


def test_identifiant_openalex_et_modele_oa_d_openalex(conn):
    record = _record(
        conn,
        "W1",
        source="openalex",
        title="PLOS ONE",
        issns=_issns(linking="1932-6203"),
        openalex_id="S202381698",
        oa_model="full_oa",
    )
    _attach(conn)
    row = conn.execute(
        text("SELECT openalex_id, oa_model::text AS oa_model FROM serials WHERE id = :id"),
        {"id": _serial_of(conn, record)},
    ).one()
    assert tuple(row) == ("S202381698", "full_oa")


def test_modele_oa_saisi_a_la_main_garde(conn):
    serial_id = insert_serial(conn, "PLOS ONE", oa_model="subscription")
    conn.execute(
        text("UPDATE serials SET manual_fields = ARRAY['oa_model'] WHERE id = :id"),
        {"id": serial_id},
    )
    insert_serial_issn(conn, serial_id, issn="1932-6203", issnl="1932-6203", sudoc_checked=True)
    _record(
        conn,
        "W1",
        source="openalex",
        title="PLOS ONE",
        issns=_issns(linking="1932-6203"),
        oa_model="full_oa",
    )
    _attach(conn)
    assert (
        conn.execute(
            text("SELECT oa_model::text FROM serials WHERE id = :id"), {"id": serial_id}
        ).scalar_one()
        == "subscription"
    )


def test_idempotent(conn):
    _record(conn, "a", title="Nature", issns=_issns("0028-0836"))
    _record(conn, "b", title="Revue locale")
    _attach(conn)
    before = conn.execute(text("SELECT id, serial_id FROM source_records ORDER BY id")).all()
    run_attach_serials(conn, _LOG)
    assert (
        conn.execute(text("SELECT id, serial_id FROM source_records ORDER BY id")).all() == before
    )
