"""Oneshot `normalize_contributor_identifiers` : identifiants de `contributor_information` sous la forme de `compact_identifiers`."""

from sqlalchemy import text

from interfaces.cli.oneshot.normalize_contributor_identifiers import apply, fetch_rows, plan
from tests.integration.helpers.contributions import upsert_contributor_information
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _run(conn):
    return apply(conn, plan(fetch_rows(conn)))


def _identifiers(conn, contributor_information_id):
    return conn.execute(
        text("SELECT identifiers FROM contributor_information WHERE id = :i"),
        {"i": contributor_information_id},
    ).scalar_one_or_none()


def _source_contribution(conn, source_contribution_id):
    return conn.execute(
        text("""
            SELECT contributor_information_id, neutralized_identifiers
            FROM source_contributions WHERE id = :i
        """),
        {"i": source_contribution_id},
    ).one()


def test_hal_person_id_passe_en_chaine(sa_sync_conn):
    information = upsert_contributor_information(
        sa_sync_conn, "jean dupont", {"hal_person_id": 42, "idhal": "jean-dupont"}
    )

    _run(sa_sync_conn)

    assert _identifiers(sa_sync_conn, information) == {
        "hal_person_id": "42",
        "idhal": "jean-dupont",
    }


def test_ligne_devenue_identique_a_une_autre_est_fusionnee(sa_sync_conn):
    source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
    kept = upsert_contributor_information(sa_sync_conn, "jean dupont", {"idref": "099757427"})
    merged = upsert_contributor_information(
        sa_sync_conn, "jean dupont", {"idref": "https://www.idref.fr/099757427/id"}
    )
    contribution = insert_source_contribution(
        sa_sync_conn, source_record, contributor_information_id=merged
    )

    _run(sa_sync_conn)

    assert _source_contribution(sa_sync_conn, contribution).contributor_information_id == kept
    assert _identifiers(sa_sync_conn, merged) is None


def test_valeur_mal_formee_ecartee_leve_la_neutralisation_pour_partage(sa_sync_conn):
    publication = insert_publication(sa_sync_conn)
    sa_sync_conn.execute(
        text("UPDATE publications SET contributions_dirty = false WHERE id = :p"),
        {"p": publication},
    )
    source_record = insert_source_record(sa_sync_conn, publication)
    contributions = [
        insert_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=position,
            author_name_normalized=name,
            identifiers={"idref": "16239546500", "orcid": orcid},
            neutralized_identifiers={"idref": "shared", "orcid": "shared"},
        )
        for position, (name, orcid) in enumerate(
            [("jean dupont", "0000-0001-2345-6789"), ("marie curie", "0000-0002-2345-6789")]
        )
    ]

    _run(sa_sync_conn)

    assert [
        _source_contribution(sa_sync_conn, c).neutralized_identifiers for c in contributions
    ] == [None, None]
    assert sa_sync_conn.execute(
        text("SELECT contributions_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()
