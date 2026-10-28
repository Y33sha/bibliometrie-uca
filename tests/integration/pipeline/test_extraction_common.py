"""Tests de la persistance et du hash de détection de l'extraction."""

from functools import partial

import pytest
from sqlalchemy import text

from domain.publications.identifiers import clean_doi
from pipeline.ingestion.common.change_detection import change_detection_hash
from pipeline.ingestion.common.doi_search import get_missing_dois
from pipeline.ingestion.common.fingerprint import fingerprint
from pipeline.ingestion.common.stale_refetch import get_stale_source_ids, set_disappeared
from pipeline.ingestion.hal.hash_normalize import strip_volatile_for_hash
from tests.integration.helpers.publications import insert_publication, insert_publication_relation
from tests.integration.helpers.serials import insert_doi_prefix
from tests.integration.helpers.sources import insert_source_record, secondary_identifiers
from tests.integration.helpers.staging import insert_failed_lookup, insert_staging

# Publication de 2020 sans titre normalisé ni type.
_publication = partial(
    insert_publication, normalize_title=False, publication_year=2020, doc_type=None
)

# Enregistrement source de titre « T ».
_source_record = partial(insert_source_record, title="T")

# ── fingerprint ─────────────────────────────────────────────────


class TestComputeHash:
    def test_deterministic(self):
        data = {"title": "Test", "year": 2024}
        assert fingerprint(data) == fingerprint(data)

    def test_key_order_independent(self):
        """Le hash ne dépend pas de l'ordre des clés."""
        a = {"z": 1, "a": 2}
        b = {"a": 2, "z": 1}
        assert fingerprint(a) == fingerprint(b)

    def test_different_data_different_hash(self):
        a = {"title": "Foo"}
        b = {"title": "Bar"}
        assert fingerprint(a) != fingerprint(b)

    def test_unicode(self):
        """Les caractères accentués sont gérés correctement."""
        data = {"title": "Étude des phénomènes"}
        h = fingerprint(data)
        assert isinstance(h, str) and len(h) == 32

    def test_nested_structures(self):
        data = {"authors": [{"name": "Dupont"}, {"name": "Durand"}]}
        h = fingerprint(data)
        assert isinstance(h, str) and len(h) == 32

    def test_empty_dict(self):
        assert fingerprint({}) == fingerprint({})


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
        assert change_detection_hash("openalex", payload) == fingerprint(payload)


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


def _add_inperim_source_record(conn, source, sid, *, doi=None, identifiers=None):
    """Publication `in_perimeter` + source_record `source` rattaché.

    Le pool de la recherche par DOI ne part que des `source_records` in-périmètre, donc un DOI candidat doit être porté par un tel record (et non par un simple `staging.doi`, retiré du pool)."""
    publication_id = _publication(conn, "T", in_perimeter=True)
    _source_record(
        conn,
        publication_id,
        source=source,
        source_id=sid,
        doi=doi,
        identifiers=secondary_identifiers(identifiers or {}),
    )


class TestGetMissingDois:
    def test_rejects_unknown_source(self):
        with pytest.raises(ValueError, match="Source inconnue"):
            get_missing_dois(None, "unknown", retry_after_days=30)

    def test_exclut_un_doi_que_la_cible_porte_deja(self, sa_sync_conn):
        """Interroger la cible sur ce DOI rendrait un document déjà présent."""
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.1234/partage")
        _add_inperim_source_record(sa_sync_conn, "hal", "hal-1", doi="10.1234/partage")

        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == []

    def test_exclut_un_doi_secondaire_de_la_cible(self, sa_sync_conn):
        """La cible rend le même document pour son DOI principal comme pour ses DOI secondaires."""
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.1234/preprint")
        _add_inperim_source_record(
            sa_sync_conn,
            "hal",
            "hal-1",
            doi="10.1234/version-editeur",
            identifiers={"doi": ["10.1234/preprint"]},
        )

        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == []

    def test_excludes_out_of_perimeter_source_records(self, sa_sync_conn):
        """Un DOI porté par une publication hors-périmètre ne remonte pas dans le pool."""
        publication_id = _publication(sa_sync_conn, "T", in_perimeter=False)
        _source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="W1", doi="10.1234/out"
        )
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == []

    def test_crossref_target_filters_non_crossref_prefixes(self, sa_sync_conn):
        """target='crossref' : seuls les DOI dont le préfixe est résolu vers Crossref ; un préfixe pas encore résolu attend `resolve_ra`."""
        insert_doi_prefix(sa_sync_conn, "10.5281", ra="DataCite")
        insert_doi_prefix(sa_sync_conn, "10.1038", ra="Crossref")
        # Trois DOIs non-crossref in-périmètre : DataCite, Crossref, préfixe inconnu.
        _add_inperim_source_record(sa_sync_conn, "hal", "h1", doi="10.5281/zenodo.1")
        _add_inperim_source_record(sa_sync_conn, "hal", "h2", doi="10.1038/nature.1")
        _add_inperim_source_record(sa_sync_conn, "hal", "h3", doi="10.99999/x.1")  # préfixe absent

        result = get_missing_dois(sa_sync_conn, "crossref", retry_after_days=30)

        # DataCite éliminé, Crossref gardé, préfixe non résolu en attente.
        assert "10.5281/zenodo.1" not in result
        assert "10.1038/nature.1" in result
        assert "10.99999/x.1" not in result

    def test_includes_related_dois_from_source_records(self, sa_sync_conn):
        """Les autres DOI d'un source_record in-périmètre (source != cible) entrent dans le pool, comme le DOI primaire."""
        _add_inperim_source_record(
            sa_sync_conn,
            "openalex",
            "W1",
            doi="10.1234/primary",
            identifiers={"doi": ["10.9999/preprint"]},
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert "10.1234/primary" in result
        assert "10.9999/preprint" in result

    def test_includes_arxiv_derived_datacite_doi(self, sa_sync_conn):
        """Un arxiv_id d'un source_record in-périmètre (source != cible) entre dans le pool sous la forme du DOI DataCite `10.48550/arxiv.<id>`, en minuscules."""
        _add_inperim_source_record(
            sa_sync_conn, "openalex", "W1", identifiers={"arxiv_id": "2605.02321"}
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert "10.48550/arxiv.2605.02321" in result

    def test_arxiv_derived_doi_excluded_for_same_source(self, sa_sync_conn):
        """L'arxiv_id d'un record de la cible elle-même ne génère pas de candidat (même logique `source != cible` que les autres branches du pool)."""
        _add_inperim_source_record(
            sa_sync_conn, "hal", "H1", identifiers={"arxiv_id": "2605.02321"}
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert "10.48550/arxiv.2605.02321" not in result

    def test_includes_relation_targets(self, sa_sync_conn):
        """Les cibles des relations depuis une publication in-périmètre (`publication_relations.target_doi`) entrent dans le pool."""
        _publication(sa_sync_conn, "Parent", row_id=1, in_perimeter=True)
        insert_publication_relation(
            sa_sync_conn,
            1,
            relation_type="is_preprint_of",
            source="crossref",
            target_doi="10.9999/related",
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert "10.9999/related" in result

    def test_relation_targets_excluded_when_parent_out_of_perimeter(self, sa_sync_conn):
        """Une relation depuis une publication hors-périmètre n'entre pas dans le pool."""
        _publication(sa_sync_conn, "Parent", row_id=1, in_perimeter=False)
        insert_publication_relation(
            sa_sync_conn,
            1,
            relation_type="is_preprint_of",
            source="crossref",
            target_doi="10.9999/related",
        )
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == []

    def test_hal_target_no_prefix_filter(self, sa_sync_conn):
        """target='hal' : aucun filtre par RA, tous les DOIs candidats remontent."""
        insert_doi_prefix(sa_sync_conn, "10.5281", ra="DataCite")
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.5281/zenodo.1")

        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)

        assert result == ["10.5281/zenodo.1"]

    def test_excludes_dois_in_backoff(self, sa_sync_conn):
        """Un DOI cherché en vain depuis moins que le délai sort du pool."""
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.1234/a")
        _add_inperim_source_record(sa_sync_conn, "openalex", "W2", doi="10.1234/b")
        insert_failed_lookup(
            sa_sync_conn, id_type="doi", id_value="10.1234/a", not_found_days_ago=10
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert result == ["10.1234/b"]

    def test_retries_dois_with_expired_backoff(self, sa_sync_conn):
        """Délai échu → le DOI repasse dans le pool."""
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.1234/a")
        insert_failed_lookup(
            sa_sync_conn, id_type="doi", id_value="10.1234/a", not_found_days_ago=60
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert result == ["10.1234/a"]

    def test_exclut_les_doi_inconnus_de_doi_org(self, sa_sync_conn):
        """Un DOI que doi.org ne connaît pas sort du pool de toutes les cibles, quelle que soit la date de l'échec."""
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.1234/a")
        _add_inperim_source_record(sa_sync_conn, "openalex", "W2", doi="10.1234/b")
        insert_failed_lookup(
            sa_sync_conn, "doi_org", id_type="doi", id_value="10.1234/a", not_found_days_ago=365
        )
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == ["10.1234/b"]

    def test_le_delai_configure_s_applique_aux_echecs_deja_inscrits(self, sa_sync_conn):
        """Le délai se lit à la sélection : le raccourcir libère les échecs déjà inscrits."""
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.1234/a")
        insert_failed_lookup(
            sa_sync_conn, id_type="doi", id_value="10.1234/a", not_found_days_ago=10
        )
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == []
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=7) == ["10.1234/a"]

    def test_backoff_is_per_target_source(self, sa_sync_conn):
        """L'échec d'un DOI sur `hal` n'affecte pas le pool de `openalex`."""
        _add_inperim_source_record(sa_sync_conn, "scanr", "S1", doi="10.1234/a")
        insert_failed_lookup(sa_sync_conn, id_type="doi", id_value="10.1234/a")
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == []
        assert get_missing_dois(sa_sync_conn, "openalex", retry_after_days=30) == ["10.1234/a"]

    def test_fenetre_d_annees_par_les_enregistrements_sources_de_la_publication(self, sa_sync_conn):
        """Un DOI est retenu quand l'un des enregistrements sources de sa publication a son année dans la fenêtre : OpenAlex date la publication de 2021, ScanR de 2022."""
        publication_id = _publication(sa_sync_conn, "T", in_perimeter=True)
        _source_record(
            sa_sync_conn,
            publication_id,
            source="openalex",
            source_id="W1",
            doi="10.1234/a",
            publication_year=2021,
        )
        _source_record(
            sa_sync_conn, publication_id, source="scanr", source_id="S1", publication_year=2022
        )

        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30, years=[2022]) == [
            "10.1234/a"
        ]
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30, years=[2021]) == [
            "10.1234/a"
        ]
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30, years=[2020]) == []


class TestGetStaleSourceIds:
    def test_returns_old_rows_with_and_without_doi(self, sa_sync_conn):
        # Le refetch par id natif ne dépend pas du DOI : la row sans DOI est
        # sélectionnée au même titre que celle qui en a un.
        insert_staging(sa_sync_conn, "openalex", source_id="W1", doi="10.1/old", seen_days_ago=100)
        insert_staging(sa_sync_conn, "openalex", source_id="W2", seen_days_ago=100)
        insert_staging(
            sa_sync_conn, "openalex", source_id="W3", doi="10.1/recent", seen_days_ago=10
        )
        rows = get_stale_source_ids(sa_sync_conn, "openalex", after_days=90)
        assert sorted(rows) == ["W1", "W2"]

    def test_excludes_disappeared(self, sa_sync_conn):
        insert_staging(
            sa_sync_conn,
            "openalex",
            source_id="W1",
            doi="10.1/gone",
            seen_days_ago=100,
            disappeared=True,
        )
        assert get_stale_source_ids(sa_sync_conn, "openalex", after_days=90) == []

    def test_scoped_to_source(self, sa_sync_conn):
        insert_staging(sa_sync_conn, "openalex", source_id="W1", doi="10.1/a", seen_days_ago=100)
        insert_staging(sa_sync_conn, "scanr", source_id="S1", doi="10.1/b", seen_days_ago=100)
        assert get_stale_source_ids(sa_sync_conn, "openalex", after_days=90) == ["W1"]

    def test_year_filter_scopes_to_window_and_keeps_null(self, sa_sync_conn):
        # W1 hors fenêtre (exclue), W2 dans la fenêtre (gardée), W3 sans
        # source_records → publication_year NULL, conservée (LEFT JOIN conservateur).
        for sid in ("W1", "W2", "W3"):
            insert_staging(sa_sync_conn, "openalex", source_id=sid, seen_days_ago=100)
        _source_record(sa_sync_conn, source="openalex", source_id="W1", publication_year=2020)
        _source_record(sa_sync_conn, source="openalex", source_id="W2", publication_year=2023)
        rows = get_stale_source_ids(sa_sync_conn, "openalex", [2023, 2024], after_days=90)
        assert sorted(rows) == ["W2", "W3"]

    def test_une_these_en_cours_est_relue_hors_fenetre(self, sa_sync_conn):
        """Une thèse en cours n'a pas d'année de soutenance : son année de première inscription ne l'écarte pas."""
        for sid in ("2005CLF21600", "s367812"):
            insert_staging(sa_sync_conn, "theses", source_id=sid, seen_days_ago=100)
        _source_record(
            sa_sync_conn,
            source="theses",
            source_id="2005CLF21600",
            publication_year=2005,
            doc_type="thesis",
        )
        _source_record(
            sa_sync_conn,
            source="theses",
            source_id="s367812",
            publication_year=2012,
            doc_type="ongoing_thesis",
        )
        rows = get_stale_source_ids(sa_sync_conn, "theses", [2023, 2024], after_days=90)
        assert rows == ["s367812"]

    def test_no_year_filter_returns_all(self, sa_sync_conn):
        insert_staging(sa_sync_conn, "openalex", source_id="W1", seen_days_ago=100)
        _source_record(sa_sync_conn, source="openalex", source_id="W1", publication_year=2010)
        assert get_stale_source_ids(sa_sync_conn, "openalex", after_days=90) == ["W1"]

    def test_the_threshold_comes_from_the_argument(self, sa_sync_conn):
        insert_staging(sa_sync_conn, "openalex", source_id="W1", seen_days_ago=40)
        assert get_stale_source_ids(sa_sync_conn, "openalex", after_days=90) == []
        rows = get_stale_source_ids(sa_sync_conn, "openalex", after_days=30)
        assert rows == ["W1"]


class TestDisappearedMarking:
    def test_set_disappeared(self, sa_sync_conn):
        insert_staging(sa_sync_conn, "openalex", source_id="W1", seen_days_ago=100)
        set_disappeared(sa_sync_conn, "openalex", "W1")
        marked = sa_sync_conn.execute(
            text(
                "SELECT disappeared_at IS NOT NULL FROM staging WHERE source='openalex' AND source_id='W1'"
            )
        ).scalar()
        assert marked is True


class TestGetPrefixesToResolve:
    """Régression : resolve tire ses préfixes de la vue `candidate_dois`, le même
    pool que la recherche par DOI — donc aussi les cibles de relations et les arXiv-dérivés,
    pas seulement staging + related_dois. L'ancienne requête ratait ces préfixes,
    laissant leur RA jamais résolue et la recherche par DOI en best-effort sur les deux RA."""

    def test_pool_covers_relation_and_arxiv_prefixes(self, sa_sync_conn):
        from pipeline.transformation.publishing.doi_prefixes import DoiPrefixStore

        # Préfixe vu UNIQUEMENT via publication_relations.target_doi (parent in-périmètre).
        _publication(sa_sync_conn, "P", row_id=1, in_perimeter=True)
        insert_publication_relation(
            sa_sync_conn,
            1,
            relation_type="is_preprint_of",
            source="crossref",
            target_doi="10.77777/rel",
        )
        # Préfixe vu UNIQUEMENT via un arxiv_id (DOI DataCite dérivé), enregistrement source in-périmètre.
        _source_record(
            sa_sync_conn,
            1,
            source="openalex",
            source_id="W1",
            identifiers=secondary_identifiers({"arxiv_id": "2605.02321"}),
        )

        prefixes = DoiPrefixStore(sa_sync_conn).get_prefixes_to_resolve()
        assert "10.77777" in prefixes  # cible de relation
        assert "10.48550" in prefixes  # arxiv-dérivé
