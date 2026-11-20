"""Tâche `persons.attach_homonyms` : contributions des publications rejetées rattachées à l'homonyme de la personne, sur vraie base."""

from sqlalchemy import text

from pipeline.transformation.persons.homonyms import attach_homonyms
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.persons import insert_person, insert_rejected_contribution
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _publication(conn, names):
    """Insère une publication à un enregistrement source HAL, hors périmètre, et renvoie la publication et une contribution par nom « prénom nom »."""
    publication = insert_publication(conn)
    source_record = insert_source_record(
        conn, publication, source="hal", source_id=f"hal-{publication}"
    )
    contributions = []
    for position, name in enumerate(names):
        source_contribution = insert_source_contribution(
            conn,
            source_record,
            author_position=position,
            raw_author_name=name,
            author_name_normalized=name.lower(),
            in_perimeter=False,
        )
        contributions.append(
            align_source_contributions(conn, publication, [(source_contribution, source_record)])
        )
    return publication, contributions


def _attribution(conn, contribution):
    return tuple(
        conn.execute(
            text("SELECT person_id, resolution_mode FROM contributions WHERE id = :g"),
            {"g": contribution},
        ).one()
    )


def _homonym(conn, person):
    return conn.execute(
        text("SELECT id, last_name, first_name, exclusion FROM persons WHERE homonym_of = :p"),
        {"p": person},
    ).one_or_none()


def test_la_contribution_au_nom_de_la_personne_rejetee_rejoint_son_homonyme(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Massard", first_name="Christophe")
    publication, (massard, durand) = _publication(conn, ["Christophe Massard", "Paul Durand"])
    insert_rejected_contribution(conn, publication, person_id=person)

    counts = attach_homonyms(conn)

    homonym = _homonym(conn, person)
    assert (homonym.last_name, homonym.first_name, homonym.exclusion) == (
        "Massard",
        "Christophe",
        "out_of_perimeter",
    )
    assert _attribution(conn, massard) == (homonym.id, "homonym")
    assert _attribution(conn, durand) == (None, None)
    assert counts["homonyms_created"] == 1


def test_un_second_passage_ne_change_rien(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Massard", first_name="Christophe")
    publication, _ = _publication(conn, ["Christophe Massard"])
    insert_rejected_contribution(conn, publication, person_id=person)
    attach_homonyms(conn)

    counts = attach_homonyms(conn)

    assert counts == {
        "homonyms_created": 0,
        "homonyms_deleted": 0,
        "homonym_contributions_attached": 0,
        "homonym_contributions_released": 0,
    }


def test_les_publications_rejetees_d_une_personne_rejoignent_un_seul_homonyme(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Massard", first_name="Christophe")
    first, (a,) = _publication(conn, ["Christophe Massard"])
    second, (b,) = _publication(conn, ["C. Massard"])
    for publication in (first, second):
        insert_rejected_contribution(conn, publication, person_id=person)

    attach_homonyms(conn)

    homonym = _homonym(conn, person)
    assert _attribution(conn, a) == _attribution(conn, b) == (homonym.id, "homonym")


def test_la_levee_du_rejet_detache_la_contribution_et_supprime_l_homonyme(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Massard", first_name="Christophe")
    publication, (massard,) = _publication(conn, ["Christophe Massard"])
    insert_rejected_contribution(conn, publication, person_id=person)
    attach_homonyms(conn)
    conn.execute(text("DELETE FROM rejected_contributions WHERE person_id = :p"), {"p": person})

    counts = attach_homonyms(conn)

    assert _attribution(conn, massard) == (None, None)
    assert _homonym(conn, person) is None
    assert (counts["homonym_contributions_released"], counts["homonyms_deleted"]) == (1, 1)


def test_deux_contributions_au_nom_de_la_personne_restent_sans_personne(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Massard", first_name="Christophe")
    publication, contributions = _publication(conn, ["Christophe Massard", "C. Massard"])
    insert_rejected_contribution(conn, publication, person_id=person)

    attach_homonyms(conn)

    assert [_attribution(conn, c) for c in contributions] == [(None, None), (None, None)]
    assert _homonym(conn, person) is None
