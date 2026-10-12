"""La cascade personnes ignore les identifiants qu'une signature neutralise, et la requalification réécrit les neutralisations `misplaced`."""

from sqlalchemy import text

from domain.persons.matching import ResolutionMode
from pipeline.transformation.persons.matching import (
    MisplacedNeutralizations,
    PersonsMatchingQueries,
)
from tests.integration.helpers.authorships import upsert_identity
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication

_ORCID = "0000-0001-2345-6789"


def _signature(
    conn,
    neutralized,
    *,
    name="dupont jean",
    source_id="c-neutralisation",
    person_id=None,
    resolution_mode=None,
):
    """Signature crossref du périmètre portant un ORCID et la carte `neutralized`. Retourne `(signature, identité)`."""
    sd = insert_source_publication(
        conn, insert_publication(conn), source="crossref", source_id=source_id
    )
    signature_id = insert_signature(
        conn,
        sd,
        source="crossref",
        raw_author_name="Jean Neutralisation",
        author_name_normalized=name,
        person_identifiers={"orcid": _ORCID},
        person_id=person_id,
        in_perimeter=True,
        resolution_mode=resolution_mode,
        neutralized_identifiers=neutralized,
    )
    return signature_id, upsert_identity(conn, name, {"orcid": _ORCID})


def _carte(conn, signature_id):
    return conn.execute(
        text("SELECT neutralized_identifiers FROM source_authorships WHERE id = :id"),
        {"id": signature_id},
    ).scalar_one()


def _orcid_projete(conn):
    rows = PersonsMatchingQueries().fetch_unlinked_authorships(conn)
    [row] = [r for r in rows if r.name.display() == "Jean Neutralisation"]
    return row.identifiers.get("orcid")


def test_orcid_neutralise_absent_de_la_projection(sa_sync_conn):
    _signature(sa_sync_conn, {"orcid": "shared"})
    assert _orcid_projete(sa_sync_conn) is None


def test_orcid_non_neutralise_present_dans_la_projection(sa_sync_conn):
    _signature(sa_sync_conn, None)
    assert _orcid_projete(sa_sync_conn) == _ORCID


def test_vote_sans_les_signatures_neutralisees_pour_partage(sa_sync_conn):
    """Une signature qui partage la valeur dans son document ne vote pas ; une signature qui la porte par erreur vote."""
    _signature(sa_sync_conn, None, name="dupont jean", source_id="c-vote-1")
    _signature(sa_sync_conn, {"orcid": "shared"}, name="martin pierre", source_id="c-vote-2")
    _signature(sa_sync_conn, {"orcid": "misplaced"}, name="durand paul", source_id="c-vote-3")
    votes = PersonsMatchingQueries().fetch_identifier_votes(sa_sync_conn, "orcid")
    assert votes[_ORCID] == {"dupont jean": 1, "durand paul": 1}


def test_requalification_pose_puis_efface_misplaced(sa_sync_conn):
    """La neutralisation `misplaced` suit le calcul de l'exécution : posée quand l'identité est désignée, effacée sinon. Une signature résolue par identifiant qui la gagne est rendue pour détachement."""
    signature_id, identity_id = _signature(
        sa_sync_conn,
        None,
        name="t dado",
        source_id="c-requalification",
        person_id=insert_person(sa_sync_conn, "Dado", first_name="T"),
        resolution_mode=ResolutionMode.IDENTIFIER.value,
    )
    queries = PersonsMatchingQueries()

    assert queries.write_misplaced_neutralizations(
        sa_sync_conn, {identity_id: ["orcid"]}
    ) == MisplacedNeutralizations(neutralized=1, to_detach=[signature_id])
    assert _carte(sa_sync_conn, signature_id) == {"orcid": "misplaced"}

    assert queries.write_misplaced_neutralizations(sa_sync_conn, {}) == MisplacedNeutralizations(
        neutralized=0, to_detach=[]
    )
    assert _carte(sa_sync_conn, signature_id) is None


def test_shared_prime_sur_misplaced(sa_sync_conn):
    signature_id, identity_id = _signature(
        sa_sync_conn, {"orcid": "shared"}, source_id="c-shared-prime"
    )
    PersonsMatchingQueries().write_misplaced_neutralizations(sa_sync_conn, {identity_id: ["orcid"]})
    assert _carte(sa_sync_conn, signature_id) == {"orcid": "shared"}
