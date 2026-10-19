"""Oneshot `decode_latex_author_names` : accents LaTeX décodés dans les noms d'auteur du stock."""

from sqlalchemy import text

from interfaces.cli.oneshot.decode_latex_author_names import decode, decoded_names
from tests.integration.helpers.authorships import insert_confirmed_authorship, upsert_split_identity
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication


def test_le_nom_decode_change_d_identite_et_perd_sa_personne_sauf_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    publication = insert_publication(conn)
    conn.execute(
        text("UPDATE publications SET authorships_dirty = false WHERE id = :p"), {"p": publication}
    )
    notice = insert_source_publication(conn, publication, source="openalex", source_id="W1")
    garbled = insert_person(conn, "Bayart", first_name="Fr\\'ed\\'eric")
    latex, pinned = (
        insert_signature(
            conn,
            notice,
            source="openalex",
            author_position=position,
            raw_author_name=raw,
            identity_id=upsert_split_identity(conn, last, first),
            person_id=garbled,
            resolution_mode="name",
            roles=["author"],
        )
        for position, raw, last, first in (
            (0, "Bayart, Fr\\'ed\\'eric", "bayart", "fr ed eric"),
            (1, 'Sch\\"afer, Uli', "sch afer", "uli"),
        )
    )
    insert_confirmed_authorship(conn, pinned, person_id=garbled)

    rows, notices = decoded_names(conn)
    assert {r["id"] for r in rows} == {latex, pinned}
    decode(conn, rows, notices)

    names = {
        r.id: (r.raw_author_name, r.last_name_normalized, r.first_name_normalized, r.person_id)
        for r in conn.execute(
            text("""
                SELECT sa.id, sa.raw_author_name, k.last_name_normalized, k.first_name_normalized,
                       sa.person_id
                FROM source_authorships sa JOIN author_identifying_keys k ON k.id = sa.identity_id
                WHERE sa.id = ANY(:ids)
            """),
            {"ids": [latex, pinned]},
        )
    }
    assert names[latex] == ("Bayart, Frédéric", "bayart", "frederic", None)
    assert names[pinned] == ("Schäfer, Uli", "schafer", "uli", garbled)
    assert conn.execute(
        text("SELECT authorships_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()
