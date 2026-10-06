"""Oneshot `backfill_initials_split` : une signature au nom réduit à des initiales rejoint l'identité de son découpage corrigé, et la synchronisation qui suit la garde."""

from sqlalchemy import text

from application.pipeline.normalize._authorships_batch import AuthorRecord, write_source_authorships
from domain.persons.signature_name import SignatureName
from infrastructure.fingerprint import fingerprint
from infrastructure.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
from interfaces.cli.oneshot.backfill_initials_split import backfill
from tests.integration.helpers.authorships import upsert_identity


def _signature(conn, raw: str, identity: str) -> tuple[int, int]:
    sp = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title) "
            "VALUES ('openalex', 'W-initiales', 't') RETURNING id"
        )
    ).scalar_one()
    sa = conn.execute(
        text(
            "INSERT INTO source_authorships "
            "(source, source_publication_id, author_position, raw_author_name, identity_id) "
            "VALUES ('openalex', :sp, 0, :raw, :iid) RETURNING id"
        ),
        {"sp": sp, "raw": raw, "iid": upsert_identity(conn, identity)},
    ).scalar_one()
    return sp, sa


def _split(conn, sa_id: int):
    return tuple(
        conn.execute(
            text(
                "SELECT aik.last_name_normalized, aik.first_name_normalized "
                "FROM source_authorships sa JOIN author_identifying_keys aik ON aik.id = sa.identity_id "
                "WHERE sa.id = :id"
            ),
            {"id": sa_id},
        ).one()
    )


def test_initiales_finales_passent_en_prenom(sa_sync_conn):
    # Identité au découpage du parseur sans la règle des initiales : nom « l », prénom « del buono ».
    _, sa = _signature(sa_sync_conn, "Del Buono L.", "del buono l")

    assert backfill(sa_sync_conn, apply=True) == 1
    assert _split(sa_sync_conn, sa) == ("del buono", "l")


def test_synchronisation_apres_backfill_garde_la_signature(sa_sync_conn):
    sp, sa = _signature(sa_sync_conn, "Del Buono L.", "del buono l")
    backfill(sa_sync_conn, apply=True)

    write_source_authorships(
        sa_sync_conn,
        PgAuthorshipsBatchQueries(),
        fingerprint,
        "openalex",
        sp,
        [AuthorRecord(0, SignatureName(raw="Del Buono L."))],
    )

    ids = (
        sa_sync_conn.execute(
            text("SELECT id FROM source_authorships WHERE source_publication_id = :sp"), {"sp": sp}
        )
        .scalars()
        .all()
    )
    assert ids == [sa]


def test_idempotent(sa_sync_conn):
    _signature(sa_sync_conn, "Del Buono L.", "del buono l")
    backfill(sa_sync_conn, apply=True)

    assert backfill(sa_sync_conn, apply=True) == 0
