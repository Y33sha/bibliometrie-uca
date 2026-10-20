"""Réinitialisation nominale de la phase personnes : re-orphelinage des signatures à
forme de nom devenue ambiguë, puis GC des personnes vidées.
"""

from sqlalchemy import text

from pipeline.transformation.persons.identifier_arbitration import (
    null_identifier_source_contributions,
)
from pipeline.transformation.persons.purge import delete_empty_persons, reorphan_ambiguous_nominal
from pipeline.transformation.persons.store import PersonsStore
from tests.integration.helpers.contributions import insert_confirmed_source_contribution
from tests.integration.helpers.persons import (
    insert_hr_record,
    insert_person,
    insert_person_identifier,
    insert_person_name_form,
    insert_rejected_contribution,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _source_contribution(conn, *, form, person_id, mode, identifiers=None):
    publication = insert_publication(conn, "t")
    source_record = insert_source_record(
        conn, publication, source_id=f"hal-{publication}", title="t"
    )
    return insert_source_contribution(
        conn,
        source_record,
        raw_author_name=form,
        author_name_normalized=form,
        identifiers=identifiers,
        person_id=person_id,
        in_perimeter=True,
        resolution_mode=mode,
    )


def _row(conn, source_contribution_id):
    return conn.execute(
        text("SELECT person_id, resolution_mode FROM source_contributions WHERE id = :i"),
        {"i": source_contribution_id},
    ).one()


def _person_exists(conn, person_id):
    return conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM persons WHERE id = :i)"), {"i": person_id}
    ).scalar_one()


def test_reorphan_only_ambiguous_unpinned_nominal(sa_sync_conn):
    conn = sa_sync_conn
    a = insert_person(conn, "Martin", first_name="Jean")
    b = insert_person(conn, "Martin", first_name="Jeanne")
    # « j martin » désigne A et B → ambiguë ; « jean martin » ne désigne que B.
    insert_person_name_form(conn, a, name_form="j martin")
    insert_person_name_form(conn, b, name_form="j martin")
    insert_person_name_form(conn, b, name_form="jean martin")

    ambiguous = _source_contribution(conn, form="j martin", person_id=a, mode="name")
    unambiguous = _source_contribution(conn, form="jean martin", person_id=b, mode="name")
    pinned = _source_contribution(conn, form="j martin", person_id=a, mode="name")
    insert_confirmed_source_contribution(conn, pinned, person_id=a)
    by_identifier = _source_contribution(conn, form="j martin", person_id=a, mode="identifier")

    assert reorphan_ambiguous_nominal(conn) == 1

    assert _row(conn, ambiguous) == (None, None)  # forme ambiguë, nominale, non épinglée
    assert _row(conn, unambiguous).person_id == b  # forme non ambiguë
    assert _row(conn, pinned).person_id == a  # épinglé par l'admin
    assert _row(conn, by_identifier).person_id == a  # résolu par identifiant


def _publication_of(conn, source_contribution_id):
    return conn.execute(
        text(
            "SELECT sp.publication_id FROM source_contributions sa "
            "JOIN source_records sp ON sp.id = sa.source_record_id WHERE sa.id = :i"
        ),
        {"i": source_contribution_id},
    ).scalar_one()


def test_un_rejet_pour_la_publication_leve_l_ambiguite(sa_sync_conn):
    """Comme la cascade, la purge écarte la personne rejetée pour la publication de la signature.

    Régression : la purge comptait toutes les personnes de la forme, et remettait à NULL à chaque run une signature que la cascade rattachait de nouveau.
    """
    conn = sa_sync_conn
    rejetee = insert_person(conn, "Tixier", first_name="Laurent")
    retenue = insert_person(conn, "Tixier", first_name="Lucie")
    insert_person_name_form(conn, rejetee, name_form="l tixier")
    insert_person_name_form(conn, retenue, name_form="l tixier")

    avec_rejet = _source_contribution(conn, form="l tixier", person_id=retenue, mode="name")
    insert_rejected_contribution(conn, _publication_of(conn, avec_rejet), person_id=rejetee)
    sans_rejet = _source_contribution(conn, form="l tixier", person_id=retenue, mode="name")

    assert reorphan_ambiguous_nominal(conn) == 1

    assert _row(conn, avec_rejet).person_id == retenue  # un seul candidat pour sa publication
    assert _row(conn, sans_rejet) == (None, None)  # deux candidats : forme ambiguë


def test_detach_source_contributions_by_id_protects_confirmed(sa_sync_conn):
    conn = sa_sync_conn
    p = insert_person(conn, "Zhang", first_name="Wei")
    cross = _source_contribution(conn, form="wei zhang", person_id=p, mode="cross_source")
    nominal = _source_contribution(conn, form="wei zhang", person_id=p, mode="name")
    pinned_cross = _source_contribution(conn, form="wei zhang", person_id=p, mode="cross_source")
    insert_confirmed_source_contribution(conn, pinned_cross, person_id=p)

    # Détache le lot demandé, mais jamais un épinglage admin.
    assert PersonsStore(conn).detach_source_contributions([cross, pinned_cross]) == 1

    assert _row(conn, cross) == (None, None)  # détachée
    assert _row(conn, pinned_cross).person_id == p  # épinglée admin, protégée
    assert _row(conn, nominal).person_id == p  # hors du lot, intacte


def test_null_identifier_source_contributions_targets_old_owner_only(sa_sync_conn):
    conn = sa_sync_conn
    old = insert_person(conn, "Martin", first_name="Jean")
    other = insert_person(conn, "Dupont", first_name="Marie")
    ids = {"idref": "111"}
    affected = _source_contribution(
        conn, form="jean martin", person_id=old, mode="identifier", identifiers=ids
    )
    nominal = _source_contribution(
        conn, form="jean martin", person_id=old, mode="name", identifiers=ids
    )
    pinned = _source_contribution(
        conn, form="jean martin", person_id=old, mode="identifier", identifiers=ids
    )
    insert_confirmed_source_contribution(conn, pinned, person_id=old)
    other_owner = _source_contribution(
        conn, form="marie dupont", person_id=other, mode="identifier", identifiers=ids
    )
    other_value = _source_contribution(
        conn, form="jean martin", person_id=old, mode="identifier", identifiers={"idref": "222"}
    )

    assert null_identifier_source_contributions(conn, "idref", "111", old) == 1

    assert _row(conn, affected) == (None, None)  # portée sur l'ancien propriétaire, identifiant
    assert _row(conn, nominal).person_id == old  # nominale : ne dépend pas de la valeur
    assert _row(conn, pinned).person_id == old  # épinglée admin
    assert _row(conn, other_owner).person_id == other  # autre propriétaire
    assert _row(conn, other_value).person_id == old  # autre valeur


def test_delete_empty_persons_spares_signed_and_rh(sa_sync_conn):
    conn = sa_sync_conn
    empty = insert_person(conn, "Ghost", first_name="G")
    signed = insert_person(conn, "Real", first_name="R")
    _source_contribution(conn, form="real r", person_id=signed, mode="name")
    rh = insert_person(conn, "Prof", first_name="P")
    insert_hr_record(conn, rh)

    delete_empty_persons(conn)

    assert _person_exists(conn, empty) is False
    assert _person_exists(conn, signed) is True
    assert _person_exists(conn, rh) is True


def test_delete_empty_persons_spares_persons_with_a_decision(sa_sync_conn):
    """Rejet, non-doublon ou exclusion conservent une personne vide ; une confirmation d'identifiant non."""
    conn = sa_sync_conn
    rejected = insert_person(conn, "Rejet", first_name="R")
    insert_rejected_contribution(conn, insert_publication(conn), person_id=rejected)
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

    delete_empty_persons(conn)

    for kept in (rejected, distinct_a, distinct_b, excluded):
        assert _person_exists(conn, kept) is True
    assert _person_exists(conn, confirmed_orcid) is False
