"""La cascade personnes ignore les identifiants qu'une contribution source neutralise, et la requalification réécrit les neutralisations `misplaced`."""

from sqlalchemy import text

from domain.persons.matching import ResolutionMode
from infrastructure.db.queues import Queue
from pipeline.transformation.persons.identifier_arbitration import (
    MisplacedNeutralizations,
    fetch_identifier_votes,
    write_misplaced_neutralizations,
)
from pipeline.transformation.persons.loading import fetch_unlinked_contributions
from tests.integration.helpers.contributions import upsert_contributor_information
from tests.integration.helpers.groups import group_ungrouped
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_ORCID = "0000-0001-2345-6789"


def _source_contribution(
    conn,
    neutralized,
    *,
    name="dupont jean",
    source_id="c-neutralisation",
    person_id=None,
    resolution_mode=None,
):
    """Contribution source crossref du périmètre avec un ORCID et la carte `neutralized`. Retourne `(contribution source, informations du contributeur)`."""
    source_record = insert_source_record(
        conn, insert_publication(conn), source="crossref", source_id=source_id
    )
    source_contribution_id = insert_source_contribution(
        conn,
        source_record,
        source="crossref",
        raw_author_name="Jean Neutralisation",
        author_name_normalized=name,
        identifiers={"orcid": _ORCID},
        person_id=person_id,
        in_perimeter=True,
        resolution_mode=resolution_mode,
        neutralized_identifiers=neutralized,
    )
    return source_contribution_id, upsert_contributor_information(conn, name, {"orcid": _ORCID})


def _carte(conn, source_contribution_id):
    return conn.execute(
        text("SELECT neutralized_identifiers FROM source_contributions WHERE id = :id"),
        {"id": source_contribution_id},
    ).scalar_one()


def _orcid_projete(conn):
    group_ungrouped(conn)
    rows = fetch_unlinked_contributions(conn)
    [row] = [r for r in rows if r.name.display() == "Jean Neutralisation"]
    return row.identifiers.get("orcid")


def test_orcid_neutralise_absent_de_la_projection(sa_sync_conn):
    _source_contribution(sa_sync_conn, {"orcid": "shared"})
    assert _orcid_projete(sa_sync_conn) is None


def test_orcid_non_neutralise_present_dans_la_projection(sa_sync_conn):
    _source_contribution(sa_sync_conn, None)
    assert _orcid_projete(sa_sync_conn) == _ORCID


def test_vote_sans_les_contributions_sources_neutralisees_pour_partage(sa_sync_conn):
    """Une contribution source qui partage la valeur dans son document ne vote pas ; une contribution source qui la contient par erreur vote."""
    _source_contribution(sa_sync_conn, None, name="dupont jean", source_id="c-vote-1")
    _source_contribution(
        sa_sync_conn, {"orcid": "shared"}, name="martin pierre", source_id="c-vote-2"
    )
    _source_contribution(
        sa_sync_conn, {"orcid": "misplaced"}, name="durand paul", source_id="c-vote-3"
    )
    group_ungrouped(sa_sync_conn)
    votes = fetch_identifier_votes(sa_sync_conn, "orcid")
    assert votes[_ORCID] == {"dupont jean": 1, "durand paul": 1}


def test_requalification_pose_puis_efface_misplaced(sa_sync_conn):
    """La neutralisation `misplaced` suit le calcul de l'exécution : posée quand les informations du contributeur sont désignées, effacée sinon. Une contribution source résolue par identifiant qui la gagne est rendue pour détachement."""
    source_contribution_id, contributor_information_id = _source_contribution(
        sa_sync_conn,
        None,
        name="t dado",
        source_id="c-requalification",
        person_id=insert_person(sa_sync_conn, "Dado", first_name="T"),
        resolution_mode=ResolutionMode.IDENTIFIER.value,
    )

    assert write_misplaced_neutralizations(
        sa_sync_conn, {contributor_information_id: ["orcid"]}
    ) == MisplacedNeutralizations(neutralized=1, to_detach=[source_contribution_id])
    assert _carte(sa_sync_conn, source_contribution_id) == {"orcid": "misplaced"}

    assert write_misplaced_neutralizations(sa_sync_conn, {}) == MisplacedNeutralizations(
        neutralized=0, to_detach=[]
    )
    assert _carte(sa_sync_conn, source_contribution_id) is None


def test_requalification_marque_la_publication_a_regrouper(sa_sync_conn):
    """Les groupes d'auteurs lisent les identifiants non neutralisés : une neutralisation qui change les remet à calculer."""
    source_contribution_id, contributor_information_id = _source_contribution(
        sa_sync_conn, None, source_id="c-regroupe"
    )
    publication_id = sa_sync_conn.execute(
        text(
            "SELECT sr.publication_id FROM source_contributions sc "
            "JOIN source_records sr ON sr.id = sc.source_record_id WHERE sc.id = :id"
        ),
        {"id": source_contribution_id},
    ).scalar_one()
    clear(sa_sync_conn, Queue.PUBLICATION_CONTRIBUTIONS)

    write_misplaced_neutralizations(sa_sync_conn, {contributor_information_id: ["orcid"]})

    assert queued(sa_sync_conn, Queue.PUBLICATION_CONTRIBUTIONS) == {publication_id}


def test_shared_prime_sur_misplaced(sa_sync_conn):
    source_contribution_id, contributor_information_id = _source_contribution(
        sa_sync_conn, {"orcid": "shared"}, source_id="c-shared-prime"
    )
    write_misplaced_neutralizations(sa_sync_conn, {contributor_information_id: ["orcid"]})
    assert _carte(sa_sync_conn, source_contribution_id) == {"orcid": "shared"}
