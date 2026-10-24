"""Arbitrage des identifiants de personne au niveau des groupes, sur vraie base : vote des groupes sur les conflits d'attribution, libération des groupes après un transfert ou une neutralisation `misplaced`."""

import logging

from sqlalchemy import text

from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from tests.integration.helpers.groups import insert_group
from tests.integration.helpers.persons import insert_person, insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_LOG = logging.getLogger("test")
_ORCID = "0000-0002-1825-0097"


def _group(conn, person, mode, *, name="jean martin", source="crossref", orcid=_ORCID):
    """Groupe d'une contribution source, seul auteur d'une publication, rattaché à `person` par `mode`. La contribution source contient l'ORCID `orcid`."""
    publication = insert_publication(conn)
    source_record = insert_source_record(
        conn, publication, source=source, source_id=f"{source}-{publication}"
    )
    source_contribution = insert_source_contribution(
        conn,
        source_record,
        source=source,
        raw_author_name=name,
        author_name_normalized=name,
        identifiers={"orcid": orcid},
    )
    group = insert_group(conn, publication, [(source_contribution, source_record)])
    conn.execute(
        text(
            "UPDATE source_contribution_groups"
            " SET person_id = :p, resolution_mode = CAST(:m AS group_resolution_mode) WHERE id = :g"
        ),
        {"p": person, "g": group, "m": mode},
    )
    return group


def _groups(conn, count, person, mode, **kwargs):
    return [_group(conn, person, mode, **kwargs) for _ in range(count)]


def _arbitrate(conn):
    return arbitrate_identifier_conflicts(conn, _LOG, repo=PgPersonRepository(conn))


def _orcid_owner(conn):
    return conn.execute(
        text("SELECT person_id FROM person_identifiers WHERE id_type = 'orcid' AND id_value = :v"),
        {"v": _ORCID},
    ).scalar_one()


def _person_of(conn, group):
    return tuple(
        conn.execute(
            text("SELECT person_id, resolution_mode FROM source_contribution_groups WHERE id = :g"),
            {"g": group},
        ).one()
    )


def _persons(conn, owner_name=("Martin", "Jean"), other_name=("Martin", "Jeanne")):
    """Titulaire de l'ORCID en `pending`, et une autre personne."""
    owner = insert_person(conn, owner_name[0], first_name=owner_name[1])
    other = insert_person(conn, other_name[0], first_name=other_name[1])
    insert_person_identifier(conn, owner, id_type="orcid", id_value=_ORCID, status="pending")
    return owner, other


class TestConflicts:
    def test_la_majorite_des_voix_transfere_et_libere_les_groupes_du_titulaire(self, sa_sync_conn):
        """Le titulaire a quatre voix (deux groupes rattachés par l'ORCID, un groupe manuel, un groupe rattaché par IdRef), l'autre personne cinq : l'ORCID passe à l'autre personne. Seuls les groupes du titulaire rattachés par l'ORCID perdent leur personne."""
        conn = sa_sync_conn
        owner, other = _persons(conn)
        by_orcid = _groups(conn, 2, owner, "orcid")
        manual = _group(conn, owner, "manual")
        by_idref = _group(conn, owner, "idref")
        _groups(conn, 5, other, "name")

        assert _arbitrate(conn)["transferred"] == 1

        assert _orcid_owner(conn) == other
        assert [_person_of(conn, g) for g in by_orcid] == [(None, None), (None, None)]
        assert _person_of(conn, manual) == (owner, "manual")
        assert _person_of(conn, by_idref) == (owner, "idref")

    def test_les_groupes_rattaches_par_l_identifiant_votent(self, sa_sync_conn):
        """Trois groupes du titulaire rattachés par l'ORCID contre un groupe de l'autre personne rattaché par le nom : le titulaire garde l'ORCID. Un rattachement par identifiant suppose que le nom corrobore la personne."""
        conn = sa_sync_conn
        owner, other = _persons(conn)
        _groups(conn, 3, owner, "orcid")
        _group(conn, other, "name")

        assert _arbitrate(conn)["transferred"] == 0

        assert _orcid_owner(conn) == owner

    def test_la_majorite_du_titulaire_garde_l_identifiant(self, sa_sync_conn):
        conn = sa_sync_conn
        owner, other = _persons(conn)
        _groups(conn, 2, owner, "name")
        by_orcid = _group(conn, owner, "orcid")
        _group(conn, other, "name")

        assert _arbitrate(conn)["transferred"] == 0

        assert _orcid_owner(conn) == owner
        assert _person_of(conn, by_orcid) == (owner, "orcid")

    def test_un_orcid_d_une_source_non_fiable_ne_vote_pas(self, sa_sync_conn):
        conn = sa_sync_conn
        owner, other = _persons(conn)
        _groups(conn, 3, other, "name", source="wos")

        assert _arbitrate(conn)["transferred"] == 0

        assert _orcid_owner(conn) == owner


def test_un_groupe_rattache_par_un_identifiant_mal_place_perd_sa_personne(sa_sync_conn):
    """Quatre « jean martin » portent l'ORCID, trois « pierre dupont » aussi : leur ORCID est mal placé. Le groupe de « pierre dupont » rattaché par l'ORCID perd sa personne ; les groupes manuel et rattaché par le nom la gardent."""
    conn = sa_sync_conn
    martin = insert_person(conn, "Martin", first_name="Jean")
    dupont = insert_person(conn, "Dupont", first_name="Pierre")
    _groups(conn, 4, martin, "name")
    by_orcid = _group(conn, dupont, "orcid", name="pierre dupont")
    manual = _group(conn, dupont, "manual", name="pierre dupont")
    by_name = _group(conn, dupont, "name", name="pierre dupont")

    result = _arbitrate(conn)

    assert (result["neutralized"], result["released_groups"]) == (3, 1)
    assert _person_of(conn, by_orcid) == (None, None)
    assert _person_of(conn, manual) == (dupont, "manual")
    assert _person_of(conn, by_name) == (dupont, "name")
