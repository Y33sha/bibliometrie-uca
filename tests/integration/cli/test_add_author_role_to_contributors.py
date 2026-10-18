"""Oneshot `add_author_role_to_contributors` : rôle `author` des contributeurs HAL, d'après la qualité source relue dans le payload."""

from sqlalchemy import text

from interfaces.cli.oneshot.add_author_role_to_contributors import complete_notices
from tests.integration.helpers.authorships import upsert_split_identity
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication

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
        text("UPDATE publications SET authorships_dirty = false WHERE id = :p"), {"p": publication}
    )
    notice = insert_source_publication(conn, publication, source="hal", source_id="hal-1")
    signatures = [
        insert_signature(
            conn,
            notice,
            identity_id=upsert_split_identity(conn, last, first),
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
        {"notice": notice, "source": "hal", "source_id": "hal-1", "signature": s, "position": p}
        for p, s in enumerate(signatures)
        if p > 0
    ]

    assert complete_notices(conn, candidates, lambda source, source_id: _PAYLOAD) == (1, 0)

    roles = (
        conn.execute(
            text(
                "SELECT roles FROM source_authorships WHERE id = ANY(:ids) ORDER BY author_position"
            ),
            {"ids": signatures},
        )
        .scalars()
        .all()
    )
    assert roles == [["author"], ["author", "contributor"], ["contributor"]]
    counts = conn.execute(
        text("SELECT author_count, distinct_author_count FROM source_publications WHERE id = :n"),
        {"n": notice},
    ).one()
    assert tuple(counts) == (2, 2)
    assert conn.execute(
        text("SELECT authorships_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()


def test_un_payload_manquant_est_compte(sa_sync_conn):
    candidates = [
        {"notice": 1, "source": "hal", "source_id": "absent", "signature": 1, "position": 1}
    ]
    assert complete_notices(sa_sync_conn, candidates, lambda source, source_id: None) == (0, 1)
