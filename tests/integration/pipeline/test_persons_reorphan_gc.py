"""Purge de la phase personnes : re-orphelinage des groupes à forme de nom ambiguë, suppression des personnes sans contribution du périmètre. Détachement des contributions sources par lot et par identifiant."""

from sqlalchemy import text

from pipeline.transformation.persons.identifier_arbitration import (
    null_identifier_source_contributions,
)
from pipeline.transformation.persons.purge import (
    delete_persons_out_of_perimeter,
    reorphan_ambiguous_nominal,
)
from pipeline.transformation.persons.store import PersonsStore
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
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _source_contribution(conn, *, form, person_id, mode, identifiers=None, in_perimeter=True):
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
        in_perimeter=in_perimeter,
        resolution_mode=mode,
    )


def _group(conn, *, form, person_id, mode="name", in_perimeter=True):
    """Contribution source de forme `form`, seule dans son groupe, groupe rattaché à la personne `person_id` par le mode `mode`. Renvoie l'`id` du groupe."""
    source_contribution = _source_contribution(conn, form=form, person_id=None, mode=None)
    return insert_person_group(
        conn, source_contribution, person_id=person_id, mode=mode, in_perimeter=in_perimeter
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


def _publication_of(conn, group_id):
    return conn.execute(
        text("SELECT publication_id FROM source_contribution_groups WHERE id = :g"),
        {"g": group_id},
    ).scalar_one()


def test_seuls_les_groupes_nominaux_a_forme_ambigue_sont_re_orphelines(sa_sync_conn):
    conn = sa_sync_conn
    a = insert_person(conn, "Martin", first_name="Jean")
    b = insert_person(conn, "Martin", first_name="Jeanne")
    # « j martin » désigne A et B → ambiguë ; « jean martin » désigne seulement B.
    insert_person_name_form(conn, a, name_form="j martin")
    insert_person_name_form(conn, b, name_form="j martin")
    insert_person_name_form(conn, b, name_form="jean martin")

    by_name = _group(conn, form="j martin", person_id=a)
    by_compatible_name = _group(conn, form="j martin", person_id=a, mode="compatible_name")
    unambiguous = _group(conn, form="jean martin", person_id=b)
    manual = _group(conn, form="j martin", person_id=a, mode="manual")
    by_identifier = _group(conn, form="j martin", person_id=a, mode="orcid")

    assert reorphan_ambiguous_nominal(conn) == 2

    assert group_person(conn, by_name) == (None, None)
    assert group_person(conn, by_compatible_name) == (None, None)
    assert group_person(conn, unambiguous)[0] == b  # forme univoque
    assert group_person(conn, manual)[0] == a  # rattachement manuel
    assert group_person(conn, by_identifier)[0] == a  # rattachement par identifiant


def test_une_forme_rejetee_ne_designe_pas_sa_personne(sa_sync_conn):
    conn = sa_sync_conn
    a = insert_person(conn, "Martin", first_name="Jean")
    b = insert_person(conn, "Martin", first_name="Jeanne")
    insert_person_name_form(conn, a, name_form="j martin")
    insert_person_name_form(conn, b, name_form="j martin", status="rejected")
    group = _group(conn, form="j martin", person_id=a)

    assert reorphan_ambiguous_nominal(conn) == 0
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

    assert reorphan_ambiguous_nominal(conn) == 1

    assert group_person(conn, avec_rejet)[0] == retenue  # un seul candidat pour sa publication
    assert group_person(conn, sans_rejet) == (None, None)  # deux candidats : forme ambiguë


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


def test_une_contribution_source_hors_groupe_ne_conserve_pas_sa_personne(sa_sync_conn):
    """Une contribution source du périmètre rattachée à la personne, hors de ses groupes, ne la conserve pas."""
    conn = sa_sync_conn
    person = insert_person(conn, "Ghost", first_name="G")
    _source_contribution(conn, form="g ghost", person_id=person, mode="name")

    delete_persons_out_of_perimeter(conn)

    assert _person_exists(conn, person) is False


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
        _source_contribution(conn, form="e epingle", person_id=None, mode=None),
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
