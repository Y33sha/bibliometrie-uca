"""Indices d'appartenance au périmètre d'une publication : ceux de ses auteurs, et ceux liés au document."""

import pytest
from sqlalchemy import text

from pipeline.transformation.publications.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import insert_persons_perimeter


def _evidence(conn, publication_id: int) -> list[str]:
    return conn.execute(
        text("SELECT perimeter_evidence::text[] FROM publications WHERE id = :id"),
        {"id": publication_id},
    ).scalar_one()


def test_seuls_les_auteurs_font_entrer_une_publication(sa_sync_conn):
    insert_persons_perimeter(sa_sync_conn)
    thesis = insert_publication(sa_sync_conn, "Thèse soutenue ailleurs", doc_type="thesis")
    article = insert_publication(sa_sync_conn, "Article")
    jury, auteur = insert_person(sa_sync_conn, "Jury"), insert_person(sa_sync_conn, "Auteur")
    insert_contribution(
        sa_sync_conn, thesis, person_id=jury, in_perimeter=True, roles=["jury_member"]
    )
    insert_contribution(
        sa_sync_conn, article, person_id=auteur, in_perimeter=True, roles=["author"]
    )

    refresh_publications_perimeter_evidence(sa_sync_conn)

    assert _evidence(sa_sync_conn, thesis) == []
    assert _evidence(sa_sync_conn, article) == ["address"]


@pytest.mark.parametrize(
    ("source", "doc_type", "role", "evidence"),
    [
        ("theses", "thesis", "jury_member", "thesis_institution"),
        ("ops", "patent", "inventor", "patent_applicant"),
    ],
)
def test_indice_lie_au_document(sa_sync_conn, source, doc_type, role, evidence):
    """Un indice d'appartenance au périmètre lié au document passe à la publication, depuis une contribution source de tout rôle, sans personne."""
    insert_persons_perimeter(sa_sync_conn)
    publication = insert_publication(sa_sync_conn, "Document", doc_type=doc_type)
    source_record = insert_source_record(sa_sync_conn, publication, source=source, source_id="1")
    source_contribution = insert_source_contribution(
        sa_sync_conn, source_record, source=source, author_position=None, roles=[role]
    )
    sa_sync_conn.execute(
        text(
            "UPDATE source_contributions SET perimeter_evidence = CAST(:e AS perimeter_evidence[])"
            " WHERE id = :id"
        ),
        {"e": [evidence], "id": source_contribution},
    )

    refresh_publications_perimeter_evidence(sa_sync_conn)

    assert _evidence(sa_sync_conn, publication) == [evidence]
