"""Oneshot `add_author_role_to_contributors` : rôle `author` des contributeurs HAL, d'après la qualité source relue dans le payload."""

from sqlalchemy import text

from interfaces.cli.oneshot.add_author_role_to_contributors import complete_source_records
from tests.integration.helpers.contributions import upsert_split_contributor_information
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_PAYLOAD = {
    "authQuality_s": ["aut", "ctb", "sad"],
    "authFullNameFormIDPersonIDIDHal_fs": [
        "Jean Dupont_FacetSep_1-0_FacetSep_",
        "Paul Martin_FacetSep_2-0_FacetSep_",
        "Anne Durand_FacetSep_3-0_FacetSep_",
    ],
}


def test_un_contributeur_ctb_devient_auteur(sa_sync_conn):
    conn = sa_sync_conn
    publication = insert_publication(conn)
    conn.execute(
        text("UPDATE publications SET contributions_dirty = false WHERE id = :p"),
        {"p": publication},
    )
    source_record = insert_source_record(conn, publication, source="hal", source_id="hal-1")
    source_contributions = [
        insert_source_contribution(
            conn,
            source_record,
            contributor_information_id=upsert_split_contributor_information(conn, last, first),
            author_position=position,
            roles=roles,
        )
        for position, (last, first, roles) in enumerate(
            [
                ("dupont", "jean", ["author"]),
                ("martin", "paul", ["contributor"]),
                ("durand", "anne", ["contributor"]),
            ]
        )
    ]
    candidates = [
        {
            "source_record": source_record,
            "source": "hal",
            "source_id": "hal-1",
            "source_contribution": s,
            "position": p,
        }
        for p, s in enumerate(source_contributions)
        if p > 0
    ]

    assert complete_source_records(conn, candidates, lambda source, source_id: _PAYLOAD) == (1, 0)

    roles = (
        conn.execute(
            text(
                "SELECT roles FROM source_contributions WHERE id = ANY(:ids) ORDER BY author_position"
            ),
            {"ids": source_contributions},
        )
        .scalars()
        .all()
    )
    assert roles == [["author"], ["author", "contributor"], ["contributor"]]
    counts = conn.execute(
        text("SELECT author_count, distinct_author_count FROM source_records WHERE id = :n"),
        {"n": source_record},
    ).one()
    assert tuple(counts) == (2, 2)
    assert conn.execute(
        text("SELECT contributions_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()


def test_un_payload_manquant_est_compte(sa_sync_conn):
    candidates = [
        {
            "source_record": 1,
            "source": "hal",
            "source_id": "absent",
            "source_contribution": 1,
            "position": 1,
        }
    ]
    assert complete_source_records(sa_sync_conn, candidates, lambda source, source_id: None) == (
        0,
        1,
    )
