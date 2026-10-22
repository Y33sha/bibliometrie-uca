"""Tâche `persons.resolve_groups` : rattachement des groupes sans personne, sur vraie base."""

from sqlalchemy import text

from pipeline.transformation.persons.groups import resolve_groups
from tests.integration.helpers.groups import insert_group
from tests.integration.helpers.persons import insert_person, insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_ORCID = "0000-0002-1825-0097"


def _group(conn, publication, members):
    """Groupe des contributions sources `(source, nom, identifiants, du périmètre)` de la publication."""
    pairs = []
    for index, (source, name, identifiers, in_perimeter) in enumerate(members):
        source_record = insert_source_record(
            conn, publication, source=source, source_id=f"{source}-{publication}-{index}"
        )
        source_contribution = insert_source_contribution(
            conn,
            source_record,
            source=source,
            raw_author_name=name,
            author_name_normalized=name.lower(),
            identifiers=identifiers,
            in_perimeter=in_perimeter,
        )
        pairs.append((source_contribution, source_record))
    return insert_group(conn, publication, pairs)


def _person(conn, group):
    return tuple(
        conn.execute(
            text("SELECT person_id, resolution_mode FROM source_contribution_groups WHERE id = :g"),
            {"g": group},
        ).one()
    )


def test_un_identifiant_d_un_membre_rattache_le_groupe_hors_perimetre(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="Jean")
    insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
    group = _group(
        conn,
        insert_publication(conn),
        [("crossref", "Jean Martin", {"orcid": _ORCID}, False), ("wos", "J. Martin", None, False)],
    )

    resolve_groups(conn)

    assert _person(conn, group) == (person, "orcid")


def test_un_nom_inconnu_du_perimetre_ne_cree_pas_de_personne(sa_sync_conn):
    conn = sa_sync_conn
    group = _group(conn, insert_publication(conn), [("hal", "Claire Durand", None, True)])

    counts = resolve_groups(conn)

    assert _person(conn, group) == (None, None)
    assert counts["create"] == 1


def test_une_personne_deja_rattachee_dans_la_publication_n_est_pas_reprise(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="Jean")
    publication = insert_publication(conn)
    attached = _group(conn, publication, [("hal", "Jean Martin", None, True)])
    conn.execute(
        text(
            "UPDATE source_contribution_groups SET person_id = :p, resolution_mode = 'manual'"
            " WHERE id = :g"
        ),
        {"p": person, "g": attached},
    )
    repeated = _group(conn, publication, [("openalex", "Jean Martin", None, True)])

    resolve_groups(conn)

    assert _person(conn, attached) == (person, "manual")
    assert _person(conn, repeated) == (None, None)
