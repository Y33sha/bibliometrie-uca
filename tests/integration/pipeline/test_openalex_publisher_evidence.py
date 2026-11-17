"""Indices d'affiliation OpenAlex d'une contribution : seul compte l'enregistrement OpenAlex éditeur, au DOI de la publication, quand la contribution y a une contribution source (`propagate_contribution_attributes_sql`)."""

from sqlalchemy import Connection, text

from domain.documents.identifiers import DOI
from infrastructure.db.queues import Queue
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.alignment import (
    align_source_contributions,
    recompose_contribution_attributes,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_PUBLICATION_DOI = "10.1000/article"
_PREPRINT_DOI = "10.48550/arxiv.2401.00001"


def _contribution(conn: Connection, publication: int, records: list[tuple[str, str, str, bool]]):
    """Aligne en une contribution les contributions sources des enregistrements `(source, identifiant, DOI, du périmètre)`, recompose ses attributs et renvoie son `id`."""
    pairs = []
    for source, source_id, doi, in_perimeter in records:
        source_record = insert_source_record(
            conn, publication, source=source, source_id=source_id, doi=doi
        )
        source_contribution = insert_source_contribution(
            conn,
            source_record,
            source=source,
            raw_author_name="Anne Martin",
            in_perimeter=in_perimeter,
        )
        pairs.append((source_contribution, source_record))
    contribution = align_source_contributions(conn, publication, pairs)
    recompose_contribution_attributes(conn)
    return contribution


def _evidence(conn: Connection, contribution: int) -> list[str]:
    return conn.execute(
        text("SELECT perimeter_evidence::text[] FROM contributions WHERE id = :id"),
        {"id": contribution},
    ).scalar_one()


def test_l_adresse_d_une_prepublication_openalex_est_ecartee(sa_sync_conn):
    publication = insert_publication(sa_sync_conn, doi=_PUBLICATION_DOI)
    contribution = _contribution(
        sa_sync_conn,
        publication,
        [("openalex", "W1", _PUBLICATION_DOI, False), ("openalex", "W2", _PREPRINT_DOI, True)],
    )

    assert _evidence(sa_sync_conn, contribution) == []


def test_sans_enregistrement_openalex_editeur_la_prepublication_compte(sa_sync_conn):
    publication = insert_publication(sa_sync_conn, doi=_PUBLICATION_DOI)
    contribution = _contribution(
        sa_sync_conn, publication, [("openalex", "W2", _PREPRINT_DOI, True)]
    )

    assert _evidence(sa_sync_conn, contribution) == ["address"]


def test_les_autres_sources_et_l_indice_rh_restent(sa_sync_conn):
    publication = insert_publication(sa_sync_conn, doi=_PUBLICATION_DOI)
    contribution = _contribution(
        sa_sync_conn,
        publication,
        [
            ("openalex", "W1", _PUBLICATION_DOI, False),
            ("openalex", "W2", _PREPRINT_DOI, False),
            ("hal", "hal-1", _PUBLICATION_DOI, True),
        ],
    )
    sa_sync_conn.execute(
        text("""
            UPDATE source_contributions sc SET perimeter_evidence = '{hr_record}'
            FROM source_records sr
            WHERE sr.id = sc.source_record_id AND sr.source_id = 'W2'
        """)
    )
    recompose_contribution_attributes(sa_sync_conn)

    assert _evidence(sa_sync_conn, contribution) == ["address", "hr_record"]


def test_un_changement_de_doi_remet_les_contributions_en_recomposition(sa_sync_conn):
    publication_id = insert_publication(sa_sync_conn, doi=_PREPRINT_DOI)
    contribution = _contribution(
        sa_sync_conn, publication_id, [("openalex", "W2", _PREPRINT_DOI, True)]
    )
    store = PublicationStore(sa_sync_conn)
    publication = store.find_by_id(publication_id)
    assert publication is not None
    publication.doi = DOI(_PUBLICATION_DOI)

    store.save([publication])

    assert contribution in queued(sa_sync_conn, Queue.CONTRIBUTION_ATTRIBUTES)
