"""Tests d'intégration du chargement des formes de nom de structures."""

from pipeline.transformation.structures.name_recognition import load_name_forms
from tests.integration.helpers.structures import insert_structure, insert_structure_name_form


class TestLoadNameForms:
    def test_returns_all_forms(self, sa_sync_conn):
        s = insert_structure(sa_sync_conn, name="X")
        f = insert_structure_name_form(sa_sync_conn, s, form_text="uca")
        rows = load_name_forms(sa_sync_conn)
        assert any(r.id == f for r in rows)
        ours = next(r for r in rows if r.id == f)
        assert ours.structure_id == s
        assert ours.form_text == "uca"
