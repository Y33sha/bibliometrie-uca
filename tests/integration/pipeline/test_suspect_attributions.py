"""Phase `suspect_attributions` : clusters isolés des personnes à fiche RH, publications proches des publications rejetées, sur vraie base."""

import logging

from sqlalchemy import text

from pipeline.transformation.persons.suspect_attributions import detect
from tests.integration.helpers.alignment import (
    add_aligned_source_contribution,
    align_source_contributions,
)
from tests.integration.helpers.contributions import (
    insert_contribution,
    upsert_split_contributor_information,
)
from tests.integration.helpers.persons import (
    insert_hr_record,
    insert_person,
    insert_person_identifier,
    insert_rejected_contribution,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_serial
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_record,
)

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


def _isolated_cluster(conn, mode="idref"):
    """Sème une personne à fiche RH : trois publications ancrées dans une revue, trois autres dans une autre revue, rattachées par `mode`. Renvoie (personne, [(publication, contribution)] du cluster isolé)."""
    person = insert_person(conn, "Morel", first_name="Laurent")
    insert_hr_record(conn, person)
    own_serial = insert_serial(conn, "Biologie cellulaire")
    other_serial = insert_serial(conn, "Électrotechnique")
    for _ in range(3):
        _contribution(conn, insert_publication(conn, serial_id=own_serial), person, "orcid")
    isolated = []
    for _ in range(3):
        publication = insert_publication(conn, serial_id=other_serial)
        isolated.append((publication, _contribution(conn, publication, person, mode)))
    return person, isolated


_ORCID = "0000-0002-1825-0097"


def _orcid_given_by(conn, person, isolated, sources):
    """Donne l'ORCID confirmé de la personne aux contributions du cluster isolé, par une contribution source de chaque source de `sources`."""
    insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
    for publication, contribution in isolated:
        for source in sources:
            source_record = insert_source_record(
                conn, publication, source=source, source_id=f"{source}-{publication}"
            )
            source_contribution = insert_source_contribution(
                conn, source_record, source=source, identifiers={"orcid": _ORCID}
            )
            add_aligned_source_contribution(conn, contribution, source_contribution, source_record)


def test_un_orcid_donne_par_hal_seulement_est_signalable(sa_sync_conn):
    """HAL donne l'ORCID du compte relié par HAL à la contribution : le rattachement vaut un idHAL."""
    person, isolated = _isolated_cluster(sa_sync_conn, mode="orcid")
    _orcid_given_by(sa_sync_conn, person, isolated, ["hal"])

    detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == [(c, person, "cluster", 1) for _, c in isolated]


def test_un_orcid_donne_aussi_par_une_autre_source_ancre_la_publication(sa_sync_conn):
    person, isolated = _isolated_cluster(sa_sync_conn, mode="orcid")
    _orcid_given_by(sa_sync_conn, person, isolated, ["hal", "openalex"])

    detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == []


def test_un_cluster_isole_d_une_personne_a_fiche_rh_est_signale(sa_sync_conn):
    person, isolated = _isolated_cluster(sa_sync_conn)

    metrics = detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == [(c, person, "cluster", 1) for _, c in isolated]
    assert metrics.extras["suspect_in_clusters"] == 3


def test_une_publication_a_adresse_du_perimetre_n_est_pas_signalee(sa_sync_conn):
    """La publication à adresse du périmètre sort du cluster, qui passe sous la taille minimale."""
    _, isolated = _isolated_cluster(sa_sync_conn)
    publication, contribution = isolated[0]
    source_record = insert_source_record(
        sa_sync_conn, publication, source="crossref", source_id="c1"
    )
    source_contribution = insert_source_contribution(
        sa_sync_conn, source_record, source="crossref", in_perimeter=True
    )
    add_aligned_source_contribution(sa_sync_conn, contribution, source_contribution, source_record)

    detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == []


def _authored(conn, coauthors, *, person=None, mode="name"):
    """Sème une publication signée « Marie Durand » et les coauteurs `coauthors` (nom, prénom), dans un enregistrement source HAL. La contribution de Marie Durand est rattachée à `person` par `mode`, ou laissée sans personne. Renvoie (publication, contribution de Marie Durand)."""
    publication = insert_publication(conn)
    source_record = insert_source_record(conn, publication, source_id=f"hal-{publication}")
    names = [("Durand", "Marie"), *coauthors]
    source_contributions = [
        insert_source_contribution(
            conn,
            source_record,
            author_position=position,
            raw_last_name=last,
            raw_first_name=first,
            contributor_information_id=upsert_split_contributor_information(
                conn, last.lower(), first.lower()
            ),
        )
        for position, (last, first) in enumerate(names)
    ]
    contribution = align_source_contributions(
        conn, publication, [(source_contributions[0], source_record)]
    )
    if person is not None:
        conn.execute(
            text(
                "UPDATE contributions SET person_id = :p, resolution_mode = CAST(:m AS resolution_mode) WHERE id = :g"
            ),
            {"p": person, "m": mode, "g": contribution},
        )
    return publication, contribution


def _resembling_rejected(conn, *, exclusion=None):
    """Sème une personne, une publication rejetée pour elle et une publication qui partage un coauteur avec le rejet. Renvoie (personne, contribution de la publication proche du rejet)."""
    person = insert_person(conn, "Durand", first_name="Marie", exclusion=exclusion)
    for colleague in (("Collègue", "Jean"), ("Autre", "Paul")):
        _authored(conn, [colleague], person=person, mode="orcid")
    rejected, _ = _authored(conn, [("Homonyme", "Coauteur")])
    insert_rejected_contribution(conn, rejected, person_id=person)
    _, suspect = _authored(conn, [("Homonyme", "Coauteur")], person=person)
    _authored(conn, [("Collègue", "Jean")], person=person)
    return person, suspect


def test_un_rejet_dont_la_publication_est_purgee_compte_encore(sa_sync_conn):
    """L'enregistrement source rejeté a perdu sa publication : ses coauteurs nommés forment encore le profil des rejets."""
    person, suspect = _resembling_rejected(sa_sync_conn)
    sa_sync_conn.execute(
        text(
            "UPDATE source_records SET publication_id = NULL WHERE publication_id IN ("
            "SELECT sr.publication_id FROM rejected_contributions rc "
            "JOIN source_records sr ON sr.source = rc.source AND sr.source_id = rc.source_id)"
        )
    )

    detect(sa_sync_conn, _LOGGER)

    assert _suspects(sa_sync_conn) == [(suspect, person, "rejected_publications", None)]


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
