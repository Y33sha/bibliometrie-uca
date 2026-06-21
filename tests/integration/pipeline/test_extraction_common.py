"""Tests pour extraction/common.py — fonctions partagées d'extraction."""

import pytest
from sqlalchemy import text

from domain.publications.identifiers import clean_doi
from infrastructure.sources.common import (
    compute_hash,
    get_cross_import_dois,
    get_existing_ids,
    get_stale_dois,
    mark_undiscoverable_stale_disappeared,
    record_doi_not_found,
    set_disappeared_by_doi,
)

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

    def test_includes_related_dois_from_source_publications(self, db):
        """Les related_dois des source_publications normalisés (source != cible)
        entrent dans le pool, comme les DOI primaires de staging."""
        db.execute(
            "INSERT INTO staging (source, source_id, doi, raw_data, processed) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("openalex", "W1", "10.1234/primary", "{}", True),
        )
        db.execute(
            "INSERT INTO source_publications (source, source_id, title, external_ids) "
            "VALUES (%s, %s, %s, %s)",
            ("openalex", "W1", "T", '{"related_dois": ["10.9999/preprint"]}'),
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert "10.1234/primary" in result
        assert "10.9999/preprint" in result

    def test_includes_relation_targets(self, db):
        """Les cibles des relations entre publications (`publication_relations.target_doi`)
        entrent dans le pool, pour rapatrier les œuvres liées absentes."""
        db.execute(
            "INSERT INTO publications (id, title, pub_year) VALUES (%s, %s, %s)",
            (1, "Parent", 2020),
        )
        db.execute(
            "INSERT INTO publication_relations "
            "(from_publication_id, relation_type, target_doi, source) VALUES (%s, %s, %s, %s)",
            (1, "is_preprint_of", "10.9999/related", "crossref"),
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert "10.9999/related" in result

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

    def test_includes_processed_rows(self, db):
        """Plus de filtre `processed` : un DOI d'une row normalisée jamais
        cross-importé reste candidat (le backoff borne le pool, pas processed)."""
        db.execute(
            "INSERT INTO staging (source, source_id, doi, raw_data, processed) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("openalex", "W1", "10.1234/a", "{}", True),
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert result == ["10.1234/a"]

    def test_excludes_dois_in_backoff(self, db):
        """Un DOI en backoff `doi_lookups` (next_retry futur) sort du pool."""
        for sid, doi in (("W1", "10.1234/a"), ("W2", "10.1234/b")):
            db.execute(
                "INSERT INTO staging (source, source_id, doi, raw_data, processed) "
                "VALUES (%s, %s, %s, %s, %s)",
                ("openalex", sid, doi, "{}", False),
            )
        db.execute(
            "INSERT INTO doi_lookups (source, doi, not_found_at, next_retry) "
            "VALUES (%s, %s, now(), now() + interval '30 days')",
            ("hal", "10.1234/a"),
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert result == ["10.1234/b"]

    def test_retries_dois_with_expired_backoff(self, db):
        """Backoff expiré (next_retry passé) → le DOI repasse dans le pool."""
        db.execute(
            "INSERT INTO staging (source, source_id, doi, raw_data, processed) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("openalex", "W1", "10.1234/a", "{}", False),
        )
        db.execute(
            "INSERT INTO doi_lookups (source, doi, not_found_at, next_retry) "
            "VALUES (%s, %s, now() - interval '60 days', now() - interval '1 day')",
            ("hal", "10.1234/a"),
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert result == ["10.1234/a"]

    def test_backoff_is_per_target_source(self, db):
        """Le backoff d'un DOI sur `hal` n'affecte pas le pool de `openalex`."""
        db.execute(
            "INSERT INTO staging (source, source_id, doi, raw_data, processed) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("scanr", "S1", "10.1234/a", "{}", False),
        )
        db.execute(
            "INSERT INTO doi_lookups (source, doi, not_found_at, next_retry) "
            "VALUES (%s, %s, now(), now() + interval '30 days')",
            ("hal", "10.1234/a"),
        )
        assert get_cross_import_dois(db.connection, "hal") == []
        assert get_cross_import_dois(db.connection, "openalex") == ["10.1234/a"]


class TestRecordDoiNotFound:
    def test_inserts_pending_backoff_row(self, sa_sync_conn):
        record_doi_not_found(sa_sync_conn, "hal", "10.1234/x")
        row = sa_sync_conn.execute(
            text(
                "SELECT next_retry > now() AS pending FROM doi_lookups "
                "WHERE source = 'hal' AND doi = '10.1234/x'"
            )
        ).one()
        assert row.pending is True

    def test_rearms_on_conflict_without_duplicate(self, sa_sync_conn):
        record_doi_not_found(sa_sync_conn, "hal", "10.1234/x")
        record_doi_not_found(sa_sync_conn, "hal", "10.1234/x")
        count = sa_sync_conn.execute(
            text("SELECT count(*) FROM doi_lookups WHERE source = 'hal' AND doi = '10.1234/x'")
        ).scalar()
        assert count == 1


def _insert_staging(conn, source, sid, doi, *, seen_days_ago, not_found=False, disappeared=False):
    conn.execute(
        text(
            "INSERT INTO staging (source, source_id, doi, raw_data, processed, last_seen_at, "
            "       not_found_at, disappeared_at) "
            "VALUES (CAST(:s AS source_type), :sid, :doi, '{}'::jsonb, :proc, "
            "       now() - make_interval(days => :d), "
            "       CASE WHEN :nf THEN now() ELSE NULL END, "
            "       CASE WHEN :dis THEN now() ELSE NULL END)"
        ),
        {
            "s": source,
            "sid": sid,
            "doi": doi,
            "d": seen_days_ago,
            "proc": not_found,
            "nf": not_found,
            "dis": disappeared,
        },
    )


class TestGetStaleDois:
    def test_returns_only_old_with_doi(self, sa_sync_conn):
        _insert_staging(sa_sync_conn, "openalex", "W1", "10.1/old", seen_days_ago=100)
        _insert_staging(sa_sync_conn, "openalex", "W2", "10.1/recent", seen_days_ago=10)
        assert get_stale_dois(sa_sync_conn, "openalex") == ["10.1/old"]

    def test_excludes_null_doi(self, sa_sync_conn):
        _insert_staging(sa_sync_conn, "openalex", "W1", None, seen_days_ago=100)
        assert get_stale_dois(sa_sync_conn, "openalex") == []

    def test_excludes_not_found_and_disappeared(self, sa_sync_conn):
        _insert_staging(
            sa_sync_conn, "openalex", "W1", "10.1/nf", seen_days_ago=100, not_found=True
        )
        _insert_staging(
            sa_sync_conn, "openalex", "W2", "10.1/gone", seen_days_ago=100, disappeared=True
        )
        assert get_stale_dois(sa_sync_conn, "openalex") == []

    def test_scoped_to_source(self, sa_sync_conn):
        _insert_staging(sa_sync_conn, "openalex", "W1", "10.1/a", seen_days_ago=100)
        _insert_staging(sa_sync_conn, "scanr", "S1", "10.1/b", seen_days_ago=100)
        assert get_stale_dois(sa_sync_conn, "openalex") == ["10.1/a"]


class TestDisappearedMarking:
    def test_set_disappeared_by_doi(self, sa_sync_conn):
        _insert_staging(sa_sync_conn, "openalex", "W1", "10.1/gone", seen_days_ago=100)
        set_disappeared_by_doi(sa_sync_conn, "openalex", "10.1/gone")
        marked = sa_sync_conn.execute(
            text(
                "SELECT disappeared_at IS NOT NULL FROM staging WHERE source='openalex' AND source_id='W1'"
            )
        ).scalar()
        assert marked is True

    def test_mark_undiscoverable_targets_stale_null_doi_only(self, sa_sync_conn):
        _insert_staging(sa_sync_conn, "openalex", "W1", None, seen_days_ago=100)  # stale, no doi
        _insert_staging(sa_sync_conn, "openalex", "W2", None, seen_days_ago=10)  # recent, no doi
        _insert_staging(
            sa_sync_conn, "openalex", "W3", "10.1/a", seen_days_ago=100
        )  # stale, has doi
        n = mark_undiscoverable_stale_disappeared(sa_sync_conn)
        assert n == 1
        gone = (
            sa_sync_conn.execute(
                text(
                    "SELECT source_id FROM staging WHERE disappeared_at IS NOT NULL ORDER BY source_id"
                )
            )
            .scalars()
            .all()
        )
        assert gone == ["W1"]
