"""La cascade personnes ignore les identifiants qu'une signature neutralise, et la requalification réécrit les neutralisations `misplaced`."""

import json

from sqlalchemy import text

from domain.persons.matching import ResolutionMode
from infrastructure.pipeline.persons.matching import PgPersonsMatchingQueries
from tests.integration.helpers.authorships import upsert_identity

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
    pub = conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, 'article') RETURNING id"
        )
    ).scalar_one()
    sd = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES ('crossref', :sid, 'X', :p) RETURNING id"
        ),
        {"sid": source_id, "p": pub},
    ).scalar_one()
    identity_id = upsert_identity(
        conn, author_name_normalized=name, person_identifiers={"orcid": _ORCID}
    )
    signature_id = conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, in_perimeter, raw_author_name,
                 identity_id, neutralized_identifiers, person_id, resolution_mode)
            VALUES ('crossref', :sd, 0, TRUE, 'Jean Neutralisation', :iid, CAST(:neu AS jsonb),
                    :pid, CAST(:mode AS resolution_mode))
            RETURNING id
        """),
        {
            "sd": sd,
            "iid": identity_id,
            "neu": json.dumps(neutralized) if neutralized else None,
            "pid": person_id,
            "mode": resolution_mode,
        },
    ).scalar_one()
    return signature_id, identity_id


def _person(conn):
    return conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES ('Dado', 'T', 'dado', 't') RETURNING id"
        )
    ).scalar_one()


def _carte(conn, signature_id):
    return conn.execute(
        text("SELECT neutralized_identifiers FROM source_authorships WHERE id = :id"),
        {"id": signature_id},
    ).scalar_one()


def _orcid_projete(conn):
    rows = PgPersonsMatchingQueries().fetch_unlinked_authorships(conn)
    [row] = [r for r in rows if r.full_name == "Jean Neutralisation"]
    return row.orcid


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
    votes = PgPersonsMatchingQueries().fetch_identifier_votes(sa_sync_conn, "orcid")
    assert votes[_ORCID] == {"dupont jean": 1, "durand paul": 1}


def test_requalification_pose_puis_efface_misplaced(sa_sync_conn):
    """La neutralisation `misplaced` suit le calcul de l'exécution : posée quand l'identité est désignée, effacée sinon. Une signature résolue par identifiant qui la gagne est rendue pour détachement."""
    signature_id, identity_id = _signature(
        sa_sync_conn,
        None,
        name="t dado",
        source_id="c-requalification",
        person_id=_person(sa_sync_conn),
        resolution_mode=ResolutionMode.IDENTIFIER.value,
    )
    queries = PgPersonsMatchingQueries()

    assert queries.write_misplaced_neutralizations(sa_sync_conn, {identity_id: ["orcid"]}) == [
        signature_id
    ]
    assert _carte(sa_sync_conn, signature_id) == {"orcid": "misplaced"}

    assert queries.write_misplaced_neutralizations(sa_sync_conn, {}) == []
    assert _carte(sa_sync_conn, signature_id) is None


def test_shared_prime_sur_misplaced(sa_sync_conn):
    signature_id, identity_id = _signature(
        sa_sync_conn, {"orcid": "shared"}, source_id="c-shared-prime"
    )
    PgPersonsMatchingQueries().write_misplaced_neutralizations(
        sa_sync_conn, {identity_id: ["orcid"]}
    )
    assert _carte(sa_sync_conn, signature_id) == {"orcid": "shared"}
