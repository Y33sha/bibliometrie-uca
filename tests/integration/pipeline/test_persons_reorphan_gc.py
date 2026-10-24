"""Purge de la phase personnes : marquage des groupes à forme de nom ambiguë, suppression des personnes sans contribution du périmètre."""

from sqlalchemy import text

from infrastructure.db.queues import Queue
from pipeline.transformation.persons.purge import (
    delete_persons_out_of_perimeter,
    mark_ambiguous_nominal,
)
from tests.integration.helpers.contributions import insert_confirmed_source_contribution
from tests.integration.helpers.groups import group_person, insert_person_group
from tests.integration.helpers.persons import (
    insert_hr_record,
    insert_person,
    insert_person_identifier,
    insert_person_name_form,
    insert_rejected_contribution,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _source_contribution(conn, *, form):
    publication = insert_publication(conn, "t")
    source_record = insert_source_record(
        conn, publication, source_id=f"hal-{publication}", title="t"
    )
    return insert_source_contribution(
        conn,
        source_record,
        raw_author_name=form,
        author_name_normalized=form,
        in_perimeter=True,
    )


def _group(conn, *, form, person_id, mode="name", in_perimeter=True):
    """Contribution source de forme `form`, seule dans son groupe, groupe rattaché à la personne `person_id` par le mode `mode`. Renvoie l'`id` du groupe."""
    source_contribution = _source_contribution(conn, form=form)
    return insert_person_group(
        conn, source_contribution, person_id=person_id, mode=mode, in_perimeter=in_perimeter
    )


def _person_exists(conn, person_id):
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM persons WHERE id = :i)"), {"i": person_id}
    ).scalar_one()


def _publication_of(conn, group_id):
    return conn.execute(
        text("SELECT publication_id FROM source_contribution_groups WHERE id = :g"),
        {"g": group_id},
    ).scalar_one()


def test_seuls_les_groupes_nominaux_a_forme_ambigue_sont_marques(sa_sync_conn):
    conn = sa_sync_conn
    a = insert_person(conn, "Martin", first_name="Jean")
    b = insert_person(conn, "Martin", first_name="Jeanne")
    # « j martin » désigne A et B → ambiguë ; « jean martin » désigne seulement B.
    insert_person_name_form(conn, a, name_form="j martin")
    insert_person_name_form(conn, b, name_form="j martin")
    insert_person_name_form(conn, b, name_form="jean martin")

    by_name = _group(conn, form="j martin", person_id=a)
    by_compatible_name = _group(conn, form="j martin", person_id=a, mode="compatible_name")
    _group(conn, form="jean martin", person_id=b)  # forme univoque
    _group(conn, form="j martin", person_id=a, mode="manual")  # rattachement manuel
    _group(conn, form="j martin", person_id=a, mode="orcid")  # rattachement par identifiant

    assert mark_ambiguous_nominal(conn) == 2

    assert queued(conn, Queue.GROUP_RESOLUTION) == {by_name, by_compatible_name}
    assert group_person(conn, by_name)[0] == a


def test_une_forme_rejetee_ne_designe_pas_sa_personne(sa_sync_conn):
    conn = sa_sync_conn
    a = insert_person(conn, "Martin", first_name="Jean")
    b = insert_person(conn, "Martin", first_name="Jeanne")
    insert_person_name_form(conn, a, name_form="j martin")
    insert_person_name_form(conn, b, name_form="j martin", status="rejected")
    group = _group(conn, form="j martin", person_id=a)

    assert mark_ambiguous_nominal(conn) == 0
    assert group_person(conn, group)[0] == a


def test_un_rejet_pour_la_publication_leve_l_ambiguite(sa_sync_conn):
    """Comme la résolution, la purge écarte la personne rejetée pour la publication du groupe.

    Régression : la purge comptait toutes les personnes de la forme, et retirait à chaque run une personne que la résolution rattachait de nouveau.
    """
    conn = sa_sync_conn
    rejetee = insert_person(conn, "Tixier", first_name="Laurent")
    retenue = insert_person(conn, "Tixier", first_name="Lucie")
    insert_person_name_form(conn, rejetee, name_form="l tixier")
    insert_person_name_form(conn, retenue, name_form="l tixier")

    avec_rejet = _group(conn, form="l tixier", person_id=retenue)
    insert_rejected_contribution(conn, _publication_of(conn, avec_rejet), person_id=rejetee)
    sans_rejet = _group(conn, form="l tixier", person_id=retenue)

    assert mark_ambiguous_nominal(conn) == 1

    # Un seul candidat pour la publication du groupe avec rejet ; deux pour l'autre : forme ambiguë.
    assert queued(conn, Queue.GROUP_RESOLUTION) == {sans_rejet}


def test_une_personne_sans_groupe_du_perimetre_est_supprimee(sa_sync_conn):
    """Une personne rattachée seulement à des groupes hors périmètre est supprimée, et ses groupes perdent leur personne. Un groupe du périmètre, une fiche RH ou une décision humaine la conservent."""
    conn = sa_sync_conn
    hors = insert_person(conn, "Demougeot", first_name="Celine")
    hors_groups = [
        _group(conn, form="celine demougeot", person_id=hors, mode=mode, in_perimeter=False)
        for mode in ("orcid", "name")
    ]
    mixte = insert_person(conn, "Mixte", first_name="M")
    _group(conn, form="m mixte", person_id=mixte, mode="orcid", in_perimeter=False)
    _group(conn, form="m mixte", person_id=mixte, mode="orcid")
    rh = insert_person(conn, "Prof", first_name="P")
    insert_hr_record(conn, rh)
    rh_group = _group(conn, form="p prof", person_id=rh, mode="orcid", in_perimeter=False)
    exclue = insert_person(conn, "Exclue", first_name="E")
    conn.execute(text("UPDATE persons SET exclusion = 'not_a_person' WHERE id = :p"), {"p": exclue})
    _group(conn, form="e exclue", person_id=exclue, mode="orcid", in_perimeter=False)

    delete_persons_out_of_perimeter(conn)

    assert [group_person(conn, g) for g in hors_groups] == [(None, None), (None, None)]
    assert _person_exists(conn, hors) is False
    for kept in (mixte, rh, exclue):
        assert _person_exists(conn, kept) is True
    assert group_person(conn, rh_group)[0] == rh


def test_une_fiche_rh_ou_un_groupe_du_perimetre_conserve_la_personne(sa_sync_conn):
    conn = sa_sync_conn
    empty = insert_person(conn, "Ghost", first_name="G")
    signed = insert_person(conn, "Real", first_name="R")
    _group(conn, form="real r", person_id=signed)
    rh = insert_person(conn, "Prof", first_name="P")
    insert_hr_record(conn, rh)

    delete_persons_out_of_perimeter(conn)

    assert _person_exists(conn, empty) is False
    assert _person_exists(conn, signed) is True
    assert _person_exists(conn, rh) is True


def test_une_decision_humaine_conserve_la_personne(sa_sync_conn):
    """Rejet, épinglage, non-doublon ou exclusion conservent une personne sans contribution ; une confirmation d'identifiant non."""
    conn = sa_sync_conn
    rejected = insert_person(conn, "Rejet", first_name="R")
    insert_rejected_contribution(conn, insert_publication(conn), person_id=rejected)
    pinned = insert_person(conn, "Epingle", first_name="E")
    insert_confirmed_source_contribution(
        conn,
        _source_contribution(conn, form="e epingle"),
        person_id=pinned,
    )
    distinct_a = insert_person(conn, "Distinct", first_name="A")
    distinct_b = insert_person(conn, "Distinct", first_name="B")
    conn.execute(
        text("INSERT INTO distinct_persons (person_id_a, person_id_b) VALUES (:a, :b)"),
        {"a": min(distinct_a, distinct_b), "b": max(distinct_a, distinct_b)},
    )
    excluded = insert_person(conn, "Exclue", first_name="E")
    conn.execute(
        text("UPDATE persons SET exclusion = 'not_a_person' WHERE id = :p"), {"p": excluded}
    )
    confirmed_orcid = insert_person(conn, "Orcid", first_name="O")
    insert_person_identifier(
        conn, confirmed_orcid, id_type="orcid", id_value="0000-0002-1825-0097", status="confirmed"
    )

    delete_persons_out_of_perimeter(conn)

    for kept in (rejected, pinned, distinct_a, distinct_b, excluded):
        assert _person_exists(conn, kept) is True
    assert _person_exists(conn, confirmed_orcid) is False


def test_une_personne_supprimee_libere_ses_groupes(sa_sync_conn):
    conn = sa_sync_conn
    empty = insert_person(conn, "Ghost", first_name="G")
    group = conn.execute(
        text(
            "INSERT INTO source_contribution_groups (publication_id, person_id, resolution_mode)"
            " VALUES (:p, :person, 'name') RETURNING id"
        ),
        {"p": insert_publication(conn, "t"), "person": empty},
    ).scalar_one()

    delete_persons_out_of_perimeter(conn)

    assert _person_exists(conn, empty) is False
    assert group_person(conn, group) == (None, None)
