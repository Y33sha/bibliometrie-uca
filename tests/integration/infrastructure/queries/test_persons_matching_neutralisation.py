"""Le rattachement des contributions ignore les identifiants neutralisés par une contribution source, et la requalification réécrit les neutralisations `misplaced`."""

from sqlalchemy import text

from infrastructure.db.queues import Queue
from pipeline.transformation.persons.contribution_resolution import load_candidate_contributions
from pipeline.transformation.persons.identifier_arbitration import (
    fetch_identifier_votes,
    write_misplaced_neutralizations,
)
from tests.integration.helpers.alignment import align_unaligned, recompose_contribution_attributes
from tests.integration.helpers.contributions import upsert_contributor_information
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_ORCID = "0000-0001-2345-6789"


def _source_contribution(conn, neutralized, *, name="dupont jean", source_id="c-neutralisation"):
    """Insère une contribution source crossref du périmètre avec un ORCID et les neutralisations `neutralized`. Renvoie `(contribution source, informations du contributeur)`."""
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
        in_perimeter=True,
        neutralized_identifiers=neutralized,
    )
    return source_contribution_id, upsert_contributor_information(conn, name, {"orcid": _ORCID})


def _carte(conn, source_contribution_id):
    return conn.execute(
        text("SELECT neutralized_identifiers FROM source_contributions WHERE id = :id"),
        {"id": source_contribution_id},
    ).scalar_one()


def _orcid_projete(conn):
    align_unaligned(conn)
    recompose_contribution_attributes(conn)
    [member] = [
        m
        for by_contribution in load_candidate_contributions(conn).values()
        for members in by_contribution.values()
        for m in members
        if m.name.display() == "Jean Neutralisation"
    ]
    return member.identifiers.get("orcid")


def test_orcid_neutralise_absent_de_la_projection(sa_sync_conn):
    _source_contribution(sa_sync_conn, {"orcid": "shared"})
    assert _orcid_projete(sa_sync_conn) is None


def test_orcid_non_neutralise_present_dans_la_projection(sa_sync_conn):
    _source_contribution(sa_sync_conn, None)
    assert _orcid_projete(sa_sync_conn) == _ORCID


def test_vote_sans_les_contributions_sources_neutralisees_pour_partage(sa_sync_conn):
    """Une contribution source qui partage la valeur dans son enregistrement source ne vote pas ; une contribution source qui la contient par erreur vote."""
    _source_contribution(sa_sync_conn, None, name="dupont jean", source_id="c-vote-1")
    _source_contribution(
        sa_sync_conn, {"orcid": "shared"}, name="martin pierre", source_id="c-vote-2"
    )
    _source_contribution(
        sa_sync_conn, {"orcid": "misplaced"}, name="durand paul", source_id="c-vote-3"
    )
    align_unaligned(sa_sync_conn)
    votes = fetch_identifier_votes(sa_sync_conn, "orcid")
    assert votes[_ORCID] == {"dupont jean": 1, "durand paul": 1}


def test_requalification_pose_puis_efface_misplaced(sa_sync_conn):
    """La neutralisation `misplaced` suit le calcul de l'exécution : posée quand les informations du contributeur sont désignées, effacée sinon. La fonction renvoie chaque contribution source qui la reçoit, avec les types d'identifiants reçus."""
    source_contribution_id, contributor_information_id = _source_contribution(
        sa_sync_conn, None, name="t dado", source_id="c-requalification"
    )

    assert write_misplaced_neutralizations(
        sa_sync_conn, {contributor_information_id: ["orcid"]}
    ) == {source_contribution_id: ["orcid"]}
    assert _carte(sa_sync_conn, source_contribution_id) == {"orcid": "misplaced"}

    assert write_misplaced_neutralizations(sa_sync_conn, {}) == {}
    assert _carte(sa_sync_conn, source_contribution_id) is None


def test_requalification_marque_la_publication_a_realigner(sa_sync_conn):
    """Les contributions d'auteurs lisent les identifiants non neutralisés : une neutralisation qui change met la publication en file pour les recalculer."""
    source_contribution_id, contributor_information_id = _source_contribution(
        sa_sync_conn, None, source_id="c-réaligne"
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
