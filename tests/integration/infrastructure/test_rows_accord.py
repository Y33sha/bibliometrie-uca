"""Accord entre les colonnes des relevés et les types qu'ils alimentent.

Chaque adaptateur construit ses lignes par appariement de noms. Le relevé étant une chaîne de caractères, l'accord échappe aux vérificateurs de types : seule son exécution le montre. Ces tests exercent les relevés concernés et laissent `infrastructure.db.rows` prononcer le désaccord.

Un relevé nomme ses colonnes qu'il rende des lignes ou aucune : les relevés qui rendent une liste se contrôlent donc sur une base sans données. Ceux qui rendent une ligne unique demandent que la ligne existe.
"""

import ast
from pathlib import Path

import pytest
from sqlalchemy import text

from application.ports.read_models.publications_queries import PublicationFilters
from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries
from infrastructure.read_models.publications.facets import _PublicationFacetsBuilder
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

    def test_les_facettes_de_publications_s_accordent(self, sa_sync_conn_owner):
        """Les quatre facettes bâties par appariement aboutissent, l'accord étant prononcé au passage."""
        builder = _PublicationFacetsBuilder(sa_sync_conn_owner, PublicationFilters(), [])
        options, total = builder._facet_labs()
        assert builder._facet_years() == []
        assert builder._facet_doc_types() == []
        assert options == [] and total == 0
        # La facette d'accès énumère son vocabulaire, que des publications le portent ou non.
        assert {option.value for option in builder._facet_access()}


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


TYPES_EXERCES = {
    "FacetOption",
    "JournalCorrectionRow",
    "JournalDoiPrefixRow",
    "UnaryCorrectionRow",
    "_JournalRow",
    "_PerimeterRow",
    "_PublisherRow",
    "_SourcePublicationRow",
    "_StructureNameFormRow",
    "_StructureRow",
}
"""Types que les tests ci-dessus construisent depuis un relevé réel.

Le test qui suit confronte cette liste aux appariements que porte le code : un adaptateur ajouté sans son test fait échouer l'intégration, et un type dont le dernier appariement disparaît sort de la liste.
"""

_APPARIEMENTS = frozenset({"row_as", "rows_as"})

_COUCHES = ("application", "infrastructure")


def _types_apparies() -> set[str]:
    """Types que le code construit par appariement de noms, relevés sur l'arbre syntaxique."""
    racine = Path(__file__).resolve().parents[3]
    trouves: set[str] = set()
    for couche in _COUCHES:
        for chemin in (racine / couche).rglob("*.py"):
            if "__pycache__" in chemin.parts:
                continue
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if (
                    isinstance(noeud, ast.Call)
                    and isinstance(noeud.func, ast.Name)
                    and noeud.func.id in _APPARIEMENTS
                    and noeud.args
                    and isinstance(noeud.args[0], ast.Name)
                ):
                    trouves.add(noeud.args[0].id)
    return trouves


def test_le_parcours_trouve_les_appariements():
    """Filet du filet : un parcours qui n'en trouverait aucun rendrait l'assertion vide, donc verte."""
    assert len(_types_apparies()) >= 10


def test_chaque_type_apparie_est_exerce_par_un_test():
    trouves = _types_apparies()
    assert trouves == TYPES_EXERCES, (
        "Types appariés sans test qui les exerce : "
        f"{sorted(trouves - TYPES_EXERCES)}. "
        "Types de la liste qu'aucun appariement ne construit plus : "
        f"{sorted(TYPES_EXERCES - trouves)}."
    )


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
