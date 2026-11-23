"""Phase `suspect_attributions` : clusters isolés des personnes à fiche RH, publications proches des publications rejetées, sur vraie base."""

import logging

from sqlalchemy import text

from pipeline.transformation.persons.suspect_attributions import detect
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.alignment import (
    add_aligned_source_contribution,
    align_source_contributions,
)
from tests.integration.helpers.contributions import (
    insert_contribution,
    upsert_split_contributor_information,
)
from tests.integration.helpers.persons import (
    insert_hr_period,
    insert_hr_record,
    insert_person,
    insert_rejected_contribution,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_serial
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import insert_structure

_LOGGER = logging.getLogger(__name__)


def _contribution(conn, publication_id, person_id, mode="manual"):
    contribution_id = insert_contribution(conn, publication_id, person_id=person_id)
    conn.execute(
        text(
            "UPDATE contributions SET resolution_mode = CAST(:m AS resolution_mode) WHERE id = :g"
        ),
        {"m": mode, "g": contribution_id},
    )
    return contribution_id


def _suspects(conn):
    return conn.execute(
        text(
            "SELECT contribution_id, person_id, reason::text, cluster FROM suspect_contributions ORDER BY 1"
        )
    ).all()


def _isolated_cluster(conn):
    """Sème une personne à fiche RH : trois publications ancrées dans une revue, trois autres dans une autre revue. Renvoie (personne, [(publication, contribution)] du cluster isolé)."""
    person = insert_person(conn, "Morel", first_name="Laurent")
    insert_hr_record(conn, person)
    own_serial = insert_serial(conn, "Biologie cellulaire")
    other_serial = insert_serial(conn, "Électrotechnique")
    for _ in range(3):
        _contribution(conn, insert_publication(conn, serial_id=own_serial), person, "orcid")
    isolated = []
    for _ in range(3):
        publication = insert_publication(conn, serial_id=other_serial)
        isolated.append((publication, _contribution(conn, publication, person, "idref")))
    return person, isolated


def test_un_cluster_isole_d_une_personne_a_fiche_rh_est_signale(sa_sync_conn):
    person, isolated = _isolated_cluster(sa_sync_conn)

    metrics = detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == [(c, person, "cluster", 1) for _, c in isolated]
    assert metrics.extras["suspect_in_clusters"] == 3


def test_une_adresse_du_laboratoire_rh_confirme_la_publication(sa_sync_conn):
    """Les publications à l'adresse du laboratoire de la fiche RH sortent du cluster, qui passe sous la taille minimale."""
    person, isolated = _isolated_cluster(sa_sync_conn)
    laboratory = insert_structure(sa_sync_conn, "LAB")
    insert_hr_period(sa_sync_conn, person, structure_id=laboratory)
    address = insert_address(sa_sync_conn, "Laboratoire, Clermont-Ferrand")
    insert_address_structure(sa_sync_conn, address, structure_id=laboratory)
    publication, contribution = isolated[0]
    source_record = insert_source_record(
        sa_sync_conn, publication, source="crossref", source_id="c1"
    )
    source_contribution = insert_source_contribution(sa_sync_conn, source_record, source="crossref")
    insert_source_contribution_address(sa_sync_conn, source_contribution, address_id=address)
    add_aligned_source_contribution(sa_sync_conn, contribution, source_contribution, source_record)

    detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == []


def _resembling_rejected(conn, *, exclusion=None):
    """Sème une personne, une publication rejetée pour elle et une publication qui partage un coauteur avec le rejet. Renvoie (personne, contribution de la publication proche du rejet)."""
    person = insert_person(conn, "Durand", first_name="Marie", exclusion=exclusion)
    colleague, other_colleague, namesake_coauthor = (
        insert_person(conn, name) for name in ("Collègue", "Autre", "Coauteur")
    )
    for coauthor in (colleague, other_colleague):
        publication = insert_publication(conn)
        _contribution(conn, publication, person, "orcid")
        _contribution(conn, publication, coauthor)

    rejected = insert_publication(conn)
    source_record = insert_source_record(conn, rejected, source_id="hal-rejet")
    namesake = insert_source_contribution(
        conn,
        source_record,
        raw_last_name="Durand",
        raw_first_name="Marie",
        contributor_information_id=upsert_split_contributor_information(conn, "durand", "marie"),
    )
    align_source_contributions(conn, rejected, [(namesake, source_record)])
    _contribution(conn, rejected, namesake_coauthor)
    insert_rejected_contribution(conn, rejected, person_id=person)

    resembling = insert_publication(conn)
    suspect = _contribution(conn, resembling, person, "name")
    _contribution(conn, resembling, namesake_coauthor)
    genuine = insert_publication(conn)
    _contribution(conn, genuine, person, "name")
    _contribution(conn, genuine, colleague)
    return person, suspect


def test_une_publication_proche_des_publications_rejetees_est_signalee(sa_sync_conn):
    person, suspect = _resembling_rejected(sa_sync_conn)

    detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == [(suspect, person, "rejected_publications", None)]


def test_une_personne_exclue_n_est_pas_examinee(sa_sync_conn):
    """Une personne hors périmètre n'est pas signalée : ses attributions sortent du périmètre."""
    _resembling_rejected(sa_sync_conn, exclusion="out_of_perimeter")

    detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == []


def test_le_calcul_remplace_les_signalements_precedents(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Robin", first_name="Frédéric")
    contribution = _contribution(sa_sync_conn, insert_publication(sa_sync_conn), person, "idref")
    sa_sync_conn.execute(
        text("INSERT INTO suspect_contributions VALUES (:c, :p, 'rejected_publications', NULL)"),
        {"c": contribution, "p": person},
    )

    detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == []
