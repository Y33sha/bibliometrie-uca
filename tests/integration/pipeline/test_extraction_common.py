"""Tests pour extraction/common.py — fonctions partagées d'extraction."""

import pytest

from domain.publications.identifiers import clean_doi
from infrastructure.sources.common import compute_hash, get_cross_import_dois, get_existing_ids

# ── compute_hash ─────────────────────────────────────────────────


class TestComputeHash:
    def test_deterministic(self):
        data = {"title": "Test", "year": 2024}
        assert compute_hash(data) == compute_hash(data)

    def test_key_order_independent(self):
        """Le hash ne dépend pas de l'ordre des clés."""
        a = {"z": 1, "a": 2}
        b = {"a": 2, "z": 1}
        assert compute_hash(a) == compute_hash(b)

    def test_different_data_different_hash(self):
        a = {"title": "Foo"}
        b = {"title": "Bar"}
        assert compute_hash(a) != compute_hash(b)

    def test_unicode(self):
        """Les caractères accentués sont gérés correctement."""
        data = {"title": "Étude des phénomènes"}
        h = compute_hash(data)
        assert isinstance(h, str) and len(h) == 32

    def test_nested_structures(self):
        data = {"authors": [{"name": "Dupont"}, {"name": "Durand"}]}
        h = compute_hash(data)
        assert isinstance(h, str) and len(h) == 32

    def test_empty_dict(self):
        assert compute_hash({}) == compute_hash({})


# ── clean_doi ────────────────────────────────────────────────────


class TestCleanDoi:
    def test_none(self):
        assert clean_doi(None) is None

    def test_empty(self):
        assert clean_doi("") is None

    def test_whitespace_only(self):
        assert clean_doi("   ") is None

    def test_plain_doi(self):
        assert clean_doi("10.1234/test.5678") == "10.1234/test.5678"

    def test_https_prefix(self):
        assert clean_doi("https://doi.org/10.1234/test") == "10.1234/test"

    def test_http_prefix(self):
        assert clean_doi("http://doi.org/10.1234/test") == "10.1234/test"

    def test_dx_prefix(self):
        assert clean_doi("https://dx.doi.org/10.1234/test") == "10.1234/test"

    def test_strips_whitespace(self):
        assert clean_doi("  https://doi.org/10.1234/test  ") == "10.1234/test"

    def test_case_insensitive_prefix(self):
        assert clean_doi("HTTPS://DOI.ORG/10.1234/test") == "10.1234/test"


# ── get_existing_ids ─────────────────────────────────────────────


class TestGetExistingIds:
    def test_rejects_unknown_source(self):
        with pytest.raises(ValueError, match="Source inconnue"):
            get_existing_ids(None, "unknown")

    def test_returns_set(self, db):
        """Avec une base vide, retourne un set vide."""
        conn = db.connection
        result = get_existing_ids(conn, "hal")
        assert result == set()

    def test_reads_dict_row_cursor(self, db):
        """Régression : `row[0]` sur une row dict_row lève KeyError.

        La connexion du pipeline utilise `row_factory=dict_row` — il faut
        accéder aux colonnes par nom, pas par index.
        """
        db.execute(
            "INSERT INTO staging (source, source_id, raw_data) VALUES (%s, %s, %s)",
            ("hal", "hal-42", "{}"),
        )
        db.execute(
            "INSERT INTO staging (source, source_id, raw_data) VALUES (%s, %s, %s)",
            ("hal", "hal-43", "{}"),
        )
        db.execute(
            "INSERT INTO staging (source, source_id, raw_data) VALUES (%s, %s, %s)",
            ("openalex", "W1", "{}"),
        )
        result = get_existing_ids(db.connection, "hal")
        assert result == {"hal-42", "hal-43"}


class TestGetCrossImportDois:
    def test_rejects_unknown_source(self):
        with pytest.raises(ValueError, match="Source inconnue"):
            get_cross_import_dois(None, "unknown")

    def test_reads_dict_row_cursor(self, db):
        """Régression : `row[0]` sur une row dict_row lève KeyError."""
        db.execute(
            "INSERT INTO staging (source, source_id, doi, raw_data, processed) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("openalex", "W1", "10.1234/a", "{}", False),
        )
        db.execute(
            "INSERT INTO staging (source, source_id, doi, raw_data, processed) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("hal", "hal-1", "10.1234/b", "{}", False),
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert result == ["10.1234/a"]

    def test_crossref_target_filters_non_crossref_prefixes(self, db):
        """target='crossref' : DOIs DataCite/mEDRA filtrés via doi_prefixes."""
        # Préfixes résolus
        db.execute(
            "INSERT INTO doi_prefixes (prefix, ra) VALUES (%s, %s)",
            ("10.5281", "DataCite"),
        )
        db.execute(
            "INSERT INTO doi_prefixes (prefix, ra) VALUES (%s, %s)",
            ("10.1038", "Crossref"),
        )
        # Trois DOIs en staging non-crossref : un DataCite, un Crossref, un préfixe inconnu
        for src, sid, doi in (
            ("hal", "h1", "10.5281/zenodo.1"),
            ("hal", "h2", "10.1038/nature.1"),
            ("hal", "h3", "10.99999/x.1"),  # préfixe absent de doi_prefixes
        ):
            db.execute(
                "INSERT INTO staging (source, source_id, doi, raw_data, processed) "
                "VALUES (%s, %s, %s, %s, %s)",
                (src, sid, doi, "{}", False),
            )

        result = get_cross_import_dois(db.connection, "crossref")

        # DataCite éliminé, Crossref gardé, NULL gardé (best-effort).
        assert "10.5281/zenodo.1" not in result
        assert "10.1038/nature.1" in result
        assert "10.99999/x.1" in result

    def test_hal_target_no_prefix_filter(self, db):
        """target='hal' : aucun filtre par RA, tous les DOIs candidats remontent."""
        db.execute(
            "INSERT INTO doi_prefixes (prefix, ra) VALUES (%s, %s)",
            ("10.5281", "DataCite"),
        )
        db.execute(
            "INSERT INTO staging (source, source_id, doi, raw_data, processed) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("openalex", "W1", "10.5281/zenodo.1", "{}", False),
        )

        result = get_cross_import_dois(db.connection, "hal")

        assert result == ["10.5281/zenodo.1"]
