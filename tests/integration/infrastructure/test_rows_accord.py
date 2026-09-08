"""Accord entre les colonnes des relevés et les types qu'ils alimentent.

Chaque adaptateur construit ses lignes par appariement de noms. Le relevé étant une chaîne de caractères, l'accord échappe aux vérificateurs de types : seule son exécution le montre. Ces tests exercent les relevés concernés et laissent `infrastructure.db.rows` prononcer le désaccord.

Un relevé nomme ses colonnes qu'il rende des lignes ou aucune : les relevés qui rendent une liste se contrôlent donc sur une base sans données. Ceux qui rendent une ligne unique demandent que la ligne existe.
"""

import pytest
from sqlalchemy import text

from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries
from infrastructure.repositories.journal_repository import PgJournalRepository
from infrastructure.repositories.perimeter_repository import PgPerimeterRepository
from infrastructure.repositories.publication_repository import PgPublicationRepository
from infrastructure.repositories.publisher_repository import PgPublisherRepository
from infrastructure.repositories.structure_repository import PgStructureRepository


class TestRelevesRendantUneListe:
    """Relevés dont l'accord se vérifie sans qu'aucune ligne existe."""

    def test_les_candidates_a_la_correction_unaire_s_accordent(self, sa_sync_conn_owner):
        assert PgMetadataCorrectionQueries().fetch_for_unary_correction(sa_sync_conn_owner) == []

    def test_les_candidates_d_une_revue_s_accordent(self, sa_sync_conn_owner):
        queries = PgMetadataCorrectionQueries()
        assert queries.fetch_for_unary_correction_by_journal(sa_sync_conn_owner, 1) == []

    def test_les_prefixes_doi_des_revues_s_accordent(self, sa_sync_conn_owner):
        assert PgMetadataCorrectionQueries().fetch_journal_doi_prefixes(sa_sync_conn_owner) == []

    def test_les_candidates_au_rattachement_par_doi_s_accordent(self, sa_sync_conn_owner):
        queries = PgMetadataCorrectionQueries()
        assert queries.fetch_journal_by_doi_candidates(sa_sync_conn_owner) == []

    def test_les_publications_sources_d_une_publication_s_accordent(self, sa_sync_conn_owner):
        repo = PgPublicationRepository(sa_sync_conn_owner)
        assert repo.get_source_publications(1) == []


class TestRelevesRendantUneLigne:
    """Relevés dont l'accord demande qu'une ligne existe."""

    def test_une_revue_s_accorde(self, sa_sync_conn_owner):
        journal_id = sa_sync_conn_owner.execute(
            text("""
                INSERT INTO journals (title, title_normalized)
                VALUES ('Revue', 'revue') RETURNING id
            """)
        ).scalar_one()
        assert PgJournalRepository(sa_sync_conn_owner).find_by_id(journal_id) is not None

    def test_un_editeur_s_accorde(self, sa_sync_conn_owner):
        publisher_id = sa_sync_conn_owner.execute(
            text("""
                INSERT INTO publishers (name, name_normalized)
                VALUES ('Éditeur', 'editeur') RETURNING id
            """)
        ).scalar_one()
        assert PgPublisherRepository(sa_sync_conn_owner).find_by_id(publisher_id) is not None

    def test_un_perimetre_s_accorde(self, sa_sync_conn_owner):
        perimeter_id = sa_sync_conn_owner.execute(
            text("""
                INSERT INTO perimeters (code, name) VALUES ('test-accord', 'Périmètre')
                RETURNING id
            """)
        ).scalar_one()
        assert PgPerimeterRepository(sa_sync_conn_owner).find_by_id(perimeter_id) is not None

    def test_une_structure_et_ses_formes_de_nom_s_accordent(self, sa_sync_conn_owner):
        structure_id = sa_sync_conn_owner.execute(
            text("""
                INSERT INTO structures (code, name, structure_type)
                VALUES ('test-accord', 'Structure', 'labo')
                RETURNING id
            """)
        ).scalar_one()
        sa_sync_conn_owner.execute(
            text("""
                INSERT INTO structure_name_forms (structure_id, form_text)
                VALUES (:sid, 'Forme de nom')
            """),
            {"sid": structure_id},
        )
        structure = PgStructureRepository(sa_sync_conn_owner).find_by_id(structure_id)
        assert structure is not None
        assert structure.name_forms


@pytest.mark.parametrize(
    "requete",
    [
        "SELECT 1 AS id",
        "SELECT 1 AS id, 'x' AS colonne_intruse",
    ],
)
def test_un_releve_qui_ne_s_accorde_pas_leve(sa_sync_conn_owner, requete):
    """Le désaccord porte le nom du type visé et celui des colonnes en écart."""
    from infrastructure.db.rows import rows_as
    from infrastructure.repositories.journal_repository import _JournalRow

    with pytest.raises(TypeError, match="_JournalRow"):
        rows_as(_JournalRow, sa_sync_conn_owner.execute(text(requete)))
