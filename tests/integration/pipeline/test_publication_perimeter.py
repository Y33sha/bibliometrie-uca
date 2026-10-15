"""Indices d'une publication : ceux de ses auteurs, et la soutenance d'une thèse dans l'établissement."""

import json

from sqlalchemy import text

from pipeline.transformation.publications.reconciliation.publication_perimeter import (
    refresh_publications_perimeter_evidence,
)
from pipeline.transformation.structures.perimeter import refresh_perimeter_structures
from tests.integration.helpers.authorships import insert_authorship
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_publication
from tests.integration.helpers.structures import insert_persons_perimeter

_PPN = "196200032"


def _evidence(conn, publication_id: int) -> list[str]:
    return conn.execute(
        text("SELECT perimeter_evidence::text[] FROM publications WHERE id = :id"),
        {"id": publication_id},
    ).scalar_one()


def test_seuls_les_auteurs_font_entrer_une_publication(sa_sync_conn):
    insert_persons_perimeter(sa_sync_conn)
    these = insert_publication(sa_sync_conn, "Thèse soutenue ailleurs", doc_type="thesis")
    article = insert_publication(sa_sync_conn, "Article")
    jury, auteur = insert_person(sa_sync_conn, "Jury"), insert_person(sa_sync_conn, "Auteur")
    insert_authorship(sa_sync_conn, these, person_id=jury, in_perimeter=True, roles=["jury_member"])
    insert_authorship(sa_sync_conn, article, person_id=auteur, in_perimeter=True, roles=["author"])

    refresh_publications_perimeter_evidence(sa_sync_conn)

    assert _evidence(sa_sync_conn, these) == []
    assert _evidence(sa_sync_conn, article) == ["address"]


def test_these_soutenue_dans_l_etablissement(sa_sync_conn):
    universite = insert_persons_perimeter(sa_sync_conn)
    sa_sync_conn.execute(
        text("UPDATE structures SET api_ids = CAST(:ids AS jsonb) WHERE id = :id"),
        {"ids": json.dumps({"theses": [_PPN]}), "id": universite},
    )
    refresh_perimeter_structures(sa_sync_conn)
    these = insert_publication(sa_sync_conn, "Thèse soutenue ici", doc_type="thesis")
    notice = insert_source_publication(
        sa_sync_conn, these, source="theses", source_id="2021CLFAC001"
    )
    sa_sync_conn.execute(
        text("UPDATE source_publications SET meta = CAST(:meta AS jsonb) WHERE id = :id"),
        {"meta": json.dumps({"etablissement_ppn": _PPN}), "id": notice},
    )

    refresh_publications_perimeter_evidence(sa_sync_conn)

    assert _evidence(sa_sync_conn, these) == ["thesis_institution"]
