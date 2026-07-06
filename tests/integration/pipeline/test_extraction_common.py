"""Tests pour extraction/common.py — fonctions partagées d'extraction."""

import pytest
from sqlalchemy import text

from domain.publications.identifiers import clean_doi
from infrastructure.sources.common import (
    change_detection_hash,
    compute_hash,
    get_cross_import_dois,
    get_existing_ids,
    get_stale_rows,
    record_doi_not_found,
    set_disappeared_by_source_id,
)
from infrastructure.sources.hal.hash_normalize import strip_volatile_for_hash

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


# ── change_detection_hash / normalisation HAL ────────────────────


def _tei(*, when, not_before="2025-01-01"):
    """Fragment TEI HAL minimal : horodatage de génération (`@when`, volatil) et
    date d'embargo (`@notBefore`, bibliographique)."""
    return (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>'
        f'<publicationStmt><date when="{when}"/></publicationStmt></fileDesc></teiHeader>'
        f'<text><body><ref type="file"><date notBefore="{not_before}"/></ref>'
        "</body></text></TEI>"
    )


class TestChangeDetectionHash:
    def test_hal_generation_timestamp_ignored(self):
        """Deux moissonnages HAL ne différant que par l'horodatage de génération du
        TEI produisent le même hash : ni UPSERT ni re-normalisation parasites."""
        a = {"halId_s": "hal-1", "label_xml": _tei(when="2026-05-28T15:21:36+02:00")}
        b = {"halId_s": "hal-1", "label_xml": _tei(when="2026-06-16T20:30:49+02:00")}
        assert change_detection_hash("hal", a) == change_detection_hash("hal", b)

    def test_hal_real_content_change_detected(self):
        """Un champ métier qui change reste détecté malgré la neutralisation."""
        base = _tei(when="2026-05-28T15:21:36+02:00")
        a = {"label_xml": base, "title_s": ["Étude A"]}
        b = {"label_xml": base, "title_s": ["Étude B"]}
        assert change_detection_hash("hal", a) != change_detection_hash("hal", b)

    def test_hal_embargo_change_detected(self):
        """Une date d'embargo (`@notBefore`) qui change reste détectée : seul `@when`
        est neutralisé."""
        a = {"label_xml": _tei(when="2026-01-01T00:00:00+02:00", not_before="2025-01-01")}
        b = {"label_xml": _tei(when="2026-01-01T00:00:00+02:00", not_before="2026-06-01")}
        assert change_detection_hash("hal", a) != change_detection_hash("hal", b)

    def test_non_hal_source_hashes_faithful_payload(self):
        """Sans normaliseur, l'empreinte est celle du payload fidèle — la
        neutralisation est propre à la source, pas au champ."""
        payload = {"id": "W1", "label_xml": _tei(when="2026-01-01T00:00:00+02:00")}
        assert change_detection_hash("openalex", payload) == compute_hash(payload)


class TestStripVolatileForHash:
    def test_does_not_mutate_input(self):
        original = _tei(when="2026-01-01T00:00:00+02:00")
        payload = {"label_xml": original}
        strip_volatile_for_hash(payload)
        assert payload["label_xml"] == original

    def test_returns_input_when_no_label_xml(self):
        payload = {"halId_s": "hal-1"}
        assert strip_volatile_for_hash(payload) is payload


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


def _add_inperim_sp(db, source, sid, *, doi=None, external_ids="{}"):
    """Publication `in_perimeter` + source_publication `source` rattaché.

    Le pool de cross-import ne part que des `source_publications` in-périmètre, donc
    un DOI candidat doit être porté par un tel record (et non par un simple
    `staging.doi`, retiré du pool)."""
    db.execute(
        "INSERT INTO publications (title, pub_year, in_perimeter) VALUES ('T', 2020, TRUE) "
        "RETURNING id"
    )
    pub_id = db.fetchone()["id"]
    db.execute(
        "INSERT INTO source_publications (source, source_id, title, doi, publication_id, "
        "external_ids) VALUES (%s, %s, 'T', %s, %s, %s::jsonb)",
        (source, sid, doi, pub_id, external_ids),
    )


class TestGetCrossImportDois:
    def test_rejects_unknown_source(self):
        with pytest.raises(ValueError, match="Source inconnue"):
            get_cross_import_dois(None, "unknown")

    def test_reads_dict_row_cursor(self, db):
        """Régression : `row[0]` sur une row dict_row lève KeyError."""
        _add_inperim_sp(db, "openalex", "W1", doi="10.1234/a")
        _add_inperim_sp(db, "hal", "hal-1", doi="10.1234/b")
        result = get_cross_import_dois(db.connection, "hal")
        assert result == ["10.1234/a"]

    def test_excludes_out_of_perimeter_source_publications(self, db):
        """Un DOI porté par une publication hors-périmètre ne remonte pas dans le pool."""
        db.execute(
            "INSERT INTO publications (title, pub_year, in_perimeter) VALUES ('T', 2020, FALSE) "
            "RETURNING id"
        )
        pub_id = db.fetchone()["id"]
        db.execute(
            "INSERT INTO source_publications (source, source_id, title, doi, publication_id) "
            "VALUES ('openalex', 'W1', 'T', '10.1234/out', %s)",
            (pub_id,),
        )
        assert get_cross_import_dois(db.connection, "hal") == []

    def test_crossref_target_filters_non_crossref_prefixes(self, db):
        """target='crossref' : DOIs DataCite/mEDRA filtrés via doi_prefixes."""
        db.execute("INSERT INTO doi_prefixes (prefix, ra) VALUES ('10.5281', 'DataCite')")
        db.execute("INSERT INTO doi_prefixes (prefix, ra) VALUES ('10.1038', 'Crossref')")
        # Trois DOIs non-crossref in-périmètre : DataCite, Crossref, préfixe inconnu.
        _add_inperim_sp(db, "hal", "h1", doi="10.5281/zenodo.1")
        _add_inperim_sp(db, "hal", "h2", doi="10.1038/nature.1")
        _add_inperim_sp(db, "hal", "h3", doi="10.99999/x.1")  # préfixe absent

        result = get_cross_import_dois(db.connection, "crossref")

        # DataCite éliminé, Crossref gardé, NULL gardé (best-effort).
        assert "10.5281/zenodo.1" not in result
        assert "10.1038/nature.1" in result
        assert "10.99999/x.1" in result

    def test_includes_related_dois_from_source_publications(self, db):
        """Les related_dois d'un source_publication in-périmètre (source != cible)
        entrent dans le pool, comme le DOI primaire."""
        _add_inperim_sp(
            db,
            "openalex",
            "W1",
            doi="10.1234/primary",
            external_ids='{"related_dois": ["10.9999/preprint"]}',
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert "10.1234/primary" in result
        assert "10.9999/preprint" in result

    def test_includes_arxiv_derived_datacite_doi(self, db):
        """Un arxiv_id d'un SP in-périmètre (source != cible) entre dans le pool sous la
        forme du DOI DataCite `10.48550/arxiv.<id>`, en minuscules."""
        _add_inperim_sp(db, "openalex", "W1", external_ids='{"arxiv_id": "2605.02321"}')
        result = get_cross_import_dois(db.connection, "hal")
        assert "10.48550/arxiv.2605.02321" in result

    def test_arxiv_derived_doi_excluded_for_same_source(self, db):
        """L'arxiv_id d'un record de la cible elle-même ne génère pas de candidat
        (même logique `source != cible` que les autres branches du pool)."""
        _add_inperim_sp(db, "hal", "H1", external_ids='{"arxiv_id": "2605.02321"}')
        result = get_cross_import_dois(db.connection, "hal")
        assert "10.48550/arxiv.2605.02321" not in result

    def test_includes_relation_targets(self, db):
        """Les cibles des relations depuis une publication in-périmètre
        (`publication_relations.target_doi`) entrent dans le pool."""
        db.execute(
            "INSERT INTO publications (id, title, pub_year, in_perimeter) "
            "VALUES (1, 'Parent', 2020, TRUE)"
        )
        db.execute(
            "INSERT INTO publication_relations "
            "(from_publication_id, relation_type, target_doi, source) "
            "VALUES (1, 'is_preprint_of', '10.9999/related', 'crossref')"
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert "10.9999/related" in result

    def test_relation_targets_excluded_when_parent_out_of_perimeter(self, db):
        """Une relation depuis une publication hors-périmètre n'entre pas dans le pool."""
        db.execute(
            "INSERT INTO publications (id, title, pub_year, in_perimeter) "
            "VALUES (1, 'Parent', 2020, FALSE)"
        )
        db.execute(
            "INSERT INTO publication_relations "
            "(from_publication_id, relation_type, target_doi, source) "
            "VALUES (1, 'is_preprint_of', '10.9999/related', 'crossref')"
        )
        assert get_cross_import_dois(db.connection, "hal") == []

    def test_hal_target_no_prefix_filter(self, db):
        """target='hal' : aucun filtre par RA, tous les DOIs candidats remontent."""
        db.execute("INSERT INTO doi_prefixes (prefix, ra) VALUES ('10.5281', 'DataCite')")
        _add_inperim_sp(db, "openalex", "W1", doi="10.5281/zenodo.1")

        result = get_cross_import_dois(db.connection, "hal")

        assert result == ["10.5281/zenodo.1"]

    def test_excludes_dois_in_backoff(self, db):
        """Un DOI en backoff `doi_lookups` (next_retry futur) sort du pool."""
        _add_inperim_sp(db, "openalex", "W1", doi="10.1234/a")
        _add_inperim_sp(db, "openalex", "W2", doi="10.1234/b")
        db.execute(
            "INSERT INTO doi_lookups (source, doi, not_found_at, next_retry) "
            "VALUES ('hal', '10.1234/a', now(), now() + interval '30 days')"
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert result == ["10.1234/b"]

    def test_retries_dois_with_expired_backoff(self, db):
        """Backoff expiré (next_retry passé) → le DOI repasse dans le pool."""
        _add_inperim_sp(db, "openalex", "W1", doi="10.1234/a")
        db.execute(
            "INSERT INTO doi_lookups (source, doi, not_found_at, next_retry) "
            "VALUES ('hal', '10.1234/a', now() - interval '60 days', now() - interval '1 day')"
        )
        result = get_cross_import_dois(db.connection, "hal")
        assert result == ["10.1234/a"]

    def test_backoff_is_per_target_source(self, db):
        """Le backoff d'un DOI sur `hal` n'affecte pas le pool de `openalex`."""
        _add_inperim_sp(db, "scanr", "S1", doi="10.1234/a")
        db.execute(
            "INSERT INTO doi_lookups (source, doi, not_found_at, next_retry) "
            "VALUES ('hal', '10.1234/a', now(), now() + interval '30 days')"
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


def _insert_source_pub(conn, source, sid, pub_year):
    conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, pub_year) "
            "VALUES (CAST(:s AS source_type), :sid, 'T', :y)"
        ),
        {"s": source, "sid": sid, "y": pub_year},
    )


class TestGetStaleRows:
    def test_returns_old_rows_with_and_without_doi(self, sa_sync_conn):
        # Le refetch par id natif ne dépend pas du DOI : la row sans DOI est
        # sélectionnée au même titre que celle qui en a un.
        _insert_staging(sa_sync_conn, "openalex", "W1", "10.1/old", seen_days_ago=100)
        _insert_staging(sa_sync_conn, "openalex", "W2", None, seen_days_ago=100)
        _insert_staging(sa_sync_conn, "openalex", "W3", "10.1/recent", seen_days_ago=10)
        rows = get_stale_rows(sa_sync_conn, "openalex")
        assert sorted(src_id for _, src_id in rows) == ["W1", "W2"]

    def test_excludes_not_found_and_disappeared(self, sa_sync_conn):
        _insert_staging(
            sa_sync_conn, "openalex", "W1", "10.1/nf", seen_days_ago=100, not_found=True
        )
        _insert_staging(
            sa_sync_conn, "openalex", "W2", "10.1/gone", seen_days_ago=100, disappeared=True
        )
        assert get_stale_rows(sa_sync_conn, "openalex") == []

    def test_scoped_to_source(self, sa_sync_conn):
        _insert_staging(sa_sync_conn, "openalex", "W1", "10.1/a", seen_days_ago=100)
        _insert_staging(sa_sync_conn, "scanr", "S1", "10.1/b", seen_days_ago=100)
        assert [src_id for _, src_id in get_stale_rows(sa_sync_conn, "openalex")] == ["W1"]

    def test_year_filter_scopes_to_window_and_keeps_null(self, sa_sync_conn):
        # W1 hors fenêtre (exclue), W2 dans la fenêtre (gardée), W3 sans
        # source_publications → pub_year NULL, conservée (LEFT JOIN conservateur).
        for sid in ("W1", "W2", "W3"):
            _insert_staging(sa_sync_conn, "openalex", sid, None, seen_days_ago=100)
        _insert_source_pub(sa_sync_conn, "openalex", "W1", 2020)
        _insert_source_pub(sa_sync_conn, "openalex", "W2", 2023)
        rows = get_stale_rows(sa_sync_conn, "openalex", [2023, 2024])
        assert sorted(src_id for _, src_id in rows) == ["W2", "W3"]

    def test_no_year_filter_returns_all(self, sa_sync_conn):
        _insert_staging(sa_sync_conn, "openalex", "W1", None, seen_days_ago=100)
        _insert_source_pub(sa_sync_conn, "openalex", "W1", 2010)
        assert [src_id for _, src_id in get_stale_rows(sa_sync_conn, "openalex")] == ["W1"]


class TestDisappearedMarking:
    def test_set_disappeared_by_source_id(self, sa_sync_conn):
        _insert_staging(sa_sync_conn, "openalex", "W1", None, seen_days_ago=100)
        set_disappeared_by_source_id(sa_sync_conn, "openalex", "W1")
        marked = sa_sync_conn.execute(
            text(
                "SELECT disappeared_at IS NOT NULL FROM staging WHERE source='openalex' AND source_id='W1'"
            )
        ).scalar()
        assert marked is True

    def test_set_disappeared_skips_not_found_stub(self, sa_sync_conn):
        # Une row déjà marquée not_found (stub cross-import) n'est pas re-marquée.
        _insert_staging(sa_sync_conn, "openalex", "W1", None, seen_days_ago=100, not_found=True)
        set_disappeared_by_source_id(sa_sync_conn, "openalex", "W1")
        marked = sa_sync_conn.execute(
            text(
                "SELECT disappeared_at IS NULL FROM staging WHERE source='openalex' AND source_id='W1'"
            )
        ).scalar()
        assert marked is True


class TestGetUnresolvedPrefixes:
    """Régression : resolve tire ses préfixes de la vue `candidate_dois`, le même
    pool que cross-import — donc aussi les cibles de relations et les arXiv-dérivés,
    pas seulement staging + related_dois. L'ancienne requête ratait ces préfixes,
    laissant leur RA jamais résolue et cross-import en best-effort sur les deux RA."""

    def test_pool_covers_relation_and_arxiv_prefixes(self, sa_sync_conn):
        from infrastructure.repositories.doi_prefix_repository import PgDoiPrefixRepository

        # Préfixe vu UNIQUEMENT via publication_relations.target_doi (parent in-périmètre).
        sa_sync_conn.execute(
            text(
                "INSERT INTO publications (id, title, pub_year, in_perimeter) "
                "VALUES (1, 'P', 2020, TRUE)"
            )
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO publication_relations "
                "(from_publication_id, relation_type, target_doi, source) "
                "VALUES (1, 'is_preprint_of', '10.77777/rel', 'crossref')"
            )
        )
        # Préfixe vu UNIQUEMENT via un arxiv_id (DOI DataCite dérivé), SP in-périmètre.
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, publication_id, "
                "external_ids) VALUES ('openalex', 'W1', 'T', 1, '{\"arxiv_id\": \"2605.02321\"}')"
            )
        )

        prefixes = dict(
            PgDoiPrefixRepository(sa_sync_conn).get_unresolved_prefixes_with_samples(
                n_samples_per_prefix=3
            )
        )
        assert "10.77777" in prefixes  # cible de relation
        assert "10.48550" in prefixes  # arxiv-dérivé
