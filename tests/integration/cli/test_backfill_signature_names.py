"""Oneshot `backfill_signature_names` : les signatures existantes rejoignent leur identité découpée, et la renormalisation qui suit les garde."""

import json

from sqlalchemy import text

from application.pipeline.normalize._authorships_batch import write_source_authorships
from application.pipeline.normalize.normalize_crossref import build_crossref_author_records
from infrastructure.fingerprint import fingerprint
from infrastructure.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
from interfaces.cli.oneshot.backfill_signature_names import backfill_source
from tests.integration.helpers.authorships import upsert_identity

_CROSSREF = {"author": [{"given": "Jean", "family": "Dupont", "ORCID": "0000-0001-0000-0001"}]}


class _RawStore:
    def __init__(self, payloads: dict[tuple[str, str], dict]) -> None:
        self._payloads = payloads

    def get(self, source: str, source_id: str) -> bytes:
        return json.dumps(self._payloads[(source, source_id)]).encode()


def _signature(conn, source: str, source_id: str, raw: str, ids: dict | None) -> tuple[int, int]:
    sp = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title) "
            "VALUES (:s, :sid, 't') RETURNING id"
        ),
        {"s": source, "sid": source_id},
    ).scalar_one()
    sa = conn.execute(
        text(
            "INSERT INTO source_authorships "
            "(source, source_publication_id, author_position, raw_author_name, identity_id) "
            "VALUES (:s, :sp, 0, :raw, :iid) RETURNING id"
        ),
        {"s": source, "sp": sp, "raw": raw, "iid": upsert_identity(conn, raw.lower(), ids)},
    ).scalar_one()
    return sp, sa


def _signature_state(conn, sa_id: int):
    return conn.execute(
        text("""
            SELECT sa.raw_author_name, sa.raw_last_name, sa.raw_first_name,
                   aik.last_name_normalized, aik.first_name_normalized, aik.person_identifiers
            FROM source_authorships sa JOIN author_identifying_keys aik ON aik.id = sa.identity_id
            WHERE sa.id = :id
        """),
        {"id": sa_id},
    ).one()


def _backfill(conn, source: str, store: _RawStore):
    return backfill_source(conn, conn, store, source, apply=True, commit=lambda: None)


def test_nom_de_la_source_relu_dans_le_payload(sa_sync_conn):
    _, sa = _signature(
        sa_sync_conn, "crossref", "10.1/a", "Jean Dupont", {"orcid": "0000-0001-0000-0001"}
    )
    _backfill(sa_sync_conn, "crossref", _RawStore({("crossref", "10.1/a"): _CROSSREF}))

    assert tuple(_signature_state(sa_sync_conn, sa)) == (
        None,
        "Dupont",
        "Jean",
        "dupont",
        "jean",
        {"orcid": "0000-0001-0000-0001"},
    )


def test_renormalisation_apres_backfill_garde_la_signature(sa_sync_conn):
    sp, sa = _signature(
        sa_sync_conn, "crossref", "10.1/b", "Jean Dupont", {"orcid": "0000-0001-0000-0001"}
    )
    _backfill(sa_sync_conn, "crossref", _RawStore({("crossref", "10.1/b"): _CROSSREF}))

    write_source_authorships(
        sa_sync_conn,
        PgAuthorshipsBatchQueries(),
        fingerprint,
        "crossref",
        sp,
        build_crossref_author_records(_CROSSREF),
    )

    ids = (
        sa_sync_conn.execute(
            text("SELECT id FROM source_authorships WHERE source_publication_id = :sp"), {"sp": sp}
        )
        .scalars()
        .all()
    )
    assert ids == [sa]


def test_chaine_brute_decoupee_par_le_parseur(sa_sync_conn):
    _, sa = _signature(sa_sync_conn, "openalex", "W1", "Dupont, Marie", None)
    _backfill(sa_sync_conn, "openalex", _RawStore({}))

    assert tuple(_signature_state(sa_sync_conn, sa)) == (
        "Dupont, Marie",
        None,
        None,
        "dupont",
        "marie",
        None,
    )


def test_payload_absent_chaine_stockee_decoupee(sa_sync_conn):
    _, sa = _signature(sa_sync_conn, "wos", "WOS:1", "Doe, Jane", None)
    stats = _backfill(sa_sync_conn, "wos", _RawStore({}))

    assert stats["notices sans payload"] == 1
    assert tuple(_signature_state(sa_sync_conn, sa))[:5] == ("Doe, Jane", None, None, "doe", "jane")


def test_idempotent(sa_sync_conn):
    _, sa = _signature(
        sa_sync_conn, "crossref", "10.1/c", "Jean Dupont", {"orcid": "0000-0001-0000-0001"}
    )
    store = _RawStore({("crossref", "10.1/c"): _CROSSREF})
    _backfill(sa_sync_conn, "crossref", store)
    first = tuple(_signature_state(sa_sync_conn, sa))
    _backfill(sa_sync_conn, "crossref", store)

    assert tuple(_signature_state(sa_sync_conn, sa)) == first
