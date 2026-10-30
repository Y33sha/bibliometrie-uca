"""Empreinte et hash de détection des changements de l'extraction, sélection des DOI à chercher et des documents à relire."""

from functools import partial

import pytest
from sqlalchemy import text

from domain.publications.identifiers import clean_doi
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
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
        """Un texte accentué donne une empreinte de 32 caractères."""
        data = {"title": "Étude des phénomènes"}
        h = fingerprint(data)
        assert isinstance(h, str) and len(h) == 32

    def test_nested_structures(self):
        data = {"authors": [{"name": "Dupont"}, {"name": "Durand"}]}
        h = fingerprint(data)
        assert isinstance(h, str) and len(h) == 32

    def test_empty_dict(self):
        assert fingerprint({}) == fingerprint({})


def _tei(*, when, not_before="2025-01-01"):
    """Fragment TEI HAL minimal : horodatage de génération (`@when`, variable d'un moissonnage à l'autre) et date d'embargo (`@notBefore`, donnée bibliographique)."""
    return (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>'
        f'<publicationStmt><date when="{when}"/></publicationStmt></fileDesc></teiHeader>'
        f'<text><body><ref type="file"><date notBefore="{not_before}"/></ref>'
        "</body></text></TEI>"
    )


class TestChangeDetectionHash:
    def test_hal_generation_timestamp_ignored(self):
        """Deux moissonnages HAL qui diffèrent seulement par l'horodatage de génération du TEI donnent le même hash : le document n'est ni réécrit ni renormalisé."""
        a = {"halId_s": "hal-1", "label_xml": _tei(when="2026-05-28T15:21:36+02:00")}
        b = {"halId_s": "hal-1", "label_xml": _tei(when="2026-06-16T20:30:49+02:00")}
        assert change_detection_hash("hal", a) == change_detection_hash("hal", b)

    def test_hal_real_content_change_detected(self):
        """Un changement de titre change le hash."""
        base = _tei(when="2026-05-28T15:21:36+02:00")
        a = {"label_xml": base, "title_s": ["Étude A"]}
        b = {"label_xml": base, "title_s": ["Étude B"]}
        assert change_detection_hash("hal", a) != change_detection_hash("hal", b)

    def test_hal_embargo_change_detected(self):
        """Un changement de date d'embargo (`@notBefore`) change le hash : seul `@when` est ignoré."""
        a = {"label_xml": _tei(when="2026-01-01T00:00:00+02:00", not_before="2025-01-01")}
        b = {"label_xml": _tei(when="2026-01-01T00:00:00+02:00", not_before="2026-06-01")}
        assert change_detection_hash("hal", a) != change_detection_hash("hal", b)

    def test_non_hal_source_hashes_faithful_payload(self):
        """Hors HAL, le hash est l'empreinte du payload entier, `label_xml` compris."""
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
    """Publication du périmètre et son enregistrement source `source`, de DOI `doi` et d'identifiants secondaires `identifiers`. La recherche par DOI part seulement des enregistrements sources du périmètre."""
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
        """La cible renvoie le même document pour son DOI principal comme pour ses DOI secondaires."""
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
        """Le DOI d'une publication hors périmètre est exclu des DOI à chercher."""
        publication_id = _publication(sa_sync_conn, "T", in_perimeter=False)
        _source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="W1", doi="10.1234/out"
        )
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == []

    def test_crossref_target_filters_non_crossref_prefixes(self, sa_sync_conn):
        """Pour Crossref, seuls les DOI de préfixe attribué à Crossref sont retenus. Un DOI de préfixe sans agence connue attend la phase `resolve_ra`."""
        insert_doi_prefix(sa_sync_conn, "10.5281", ra="DataCite")
        insert_doi_prefix(sa_sync_conn, "10.1038", ra="Crossref")
        # Trois DOI d'enregistrements sources HAL du périmètre : préfixe DataCite, préfixe Crossref, préfixe inconnu.
        _add_inperim_source_record(sa_sync_conn, "hal", "h1", doi="10.5281/zenodo.1")
        _add_inperim_source_record(sa_sync_conn, "hal", "h2", doi="10.1038/nature.1")
        _add_inperim_source_record(sa_sync_conn, "hal", "h3", doi="10.99999/x.1")  # préfixe inconnu

        result = get_missing_dois(sa_sync_conn, "crossref", retry_after_days=30)

        # Seul le DOI de préfixe Crossref est retenu.
        assert "10.5281/zenodo.1" not in result
        assert "10.1038/nature.1" in result
        assert "10.99999/x.1" not in result

    def test_includes_related_dois_from_source_records(self, sa_sync_conn):
        """Tous les DOI actifs d'un enregistrement source du périmètre, d'une autre source que la cible, sont retenus."""
        _add_inperim_source_record(
            sa_sync_conn,
            "openalex",
            "W1",
            identifiers={"doi": ["10.1234/primary", "10.9999/preprint"]},
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert "10.1234/primary" in result
        assert "10.9999/preprint" in result

    def test_reads_the_dois_of_the_identifier_table(self, sa_sync_conn):
        """Régression : la colonne `doi` d'un work OpenAlex gardait un DOI mal formé, absent de ses identifiants."""
        _add_inperim_source_record(
            sa_sync_conn,
            "openalex",
            "W1",
            doi="10.3389/feart.2020.00279/abstract",
            identifiers={"doi": ["10.3389/feart.2020.00279"]},
        )
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == [
            "10.3389/feart.2020.00279"
        ]

    def test_excludes_a_doi_removed_by_the_correction(self, sa_sync_conn):
        publication_id = _publication(sa_sync_conn, "T", in_perimeter=True)
        _source_record(
            sa_sync_conn,
            publication_id,
            source="openalex",
            source_id="W1",
            identifiers=[
                SourceIdentifier(
                    SourceIdentifierType.DOI,
                    "10.1234/faux",
                    SourceIdentifierRole.SECONDARY,
                    "UNRESOLVED_DOI_TO_NULL",
                )
            ],
        )
        assert get_missing_dois(sa_sync_conn, "hal", retry_after_days=30) == []

    def test_includes_arxiv_derived_datacite_doi(self, sa_sync_conn):
        """L'identifiant arXiv d'un enregistrement source du périmètre, d'une autre source que la cible, est retenu sous la forme du DOI DataCite `10.48550/arxiv.<id>`, en minuscules."""
        _add_inperim_source_record(
            sa_sync_conn, "openalex", "W1", identifiers={"arxiv_id": "2605.02321"}
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert "10.48550/arxiv.2605.02321" in result

    def test_arxiv_derived_doi_excluded_for_same_source(self, sa_sync_conn):
        """L'identifiant arXiv d'un enregistrement source de la cible elle-même est exclu."""
        _add_inperim_source_record(
            sa_sync_conn, "hal", "H1", identifiers={"arxiv_id": "2605.02321"}
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert "10.48550/arxiv.2605.02321" not in result

    def test_includes_the_unversioned_form_of_a_versioned_doi(self, sa_sync_conn):
        """La forme sans version, sans source, est cherchée même dans la source qui a la version."""
        insert_doi_prefix(sa_sync_conn, "10.6084", ra="DataCite")
        _add_inperim_source_record(
            sa_sync_conn,
            "datacite",
            "10.6084/m9.figshare.1.v1",
            identifiers={"doi": ["10.6084/m9.figshare.1.v1"]},
        )
        result = get_missing_dois(sa_sync_conn, "datacite", retry_after_days=30)
        assert result == ["10.6084/m9.figshare.1"]

    def test_includes_relation_targets(self, sa_sync_conn):
        """Le DOI cible d'une relation depuis une publication du périmètre est retenu."""
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
        """Le DOI cible d'une relation depuis une publication hors périmètre est exclu."""
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
        """Pour HAL, les DOI sont retenus quelle que soit leur agence d'enregistrement."""
        insert_doi_prefix(sa_sync_conn, "10.5281", ra="DataCite")
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.5281/zenodo.1")

        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)

        assert result == ["10.5281/zenodo.1"]

    def test_excludes_dois_in_backoff(self, sa_sync_conn):
        """Un DOI cherché en vain depuis moins longtemps que le délai est exclu."""
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.1234/a")
        _add_inperim_source_record(sa_sync_conn, "openalex", "W2", doi="10.1234/b")
        insert_failed_lookup(
            sa_sync_conn, id_type="doi", id_value="10.1234/a", not_found_days_ago=10
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert result == ["10.1234/b"]

    def test_retries_dois_with_expired_backoff(self, sa_sync_conn):
        """Un DOI cherché en vain depuis plus longtemps que le délai est retenu."""
        _add_inperim_source_record(sa_sync_conn, "openalex", "W1", doi="10.1234/a")
        insert_failed_lookup(
            sa_sync_conn, id_type="doi", id_value="10.1234/a", not_found_days_ago=60
        )
        result = get_missing_dois(sa_sync_conn, "hal", retry_after_days=30)
        assert result == ["10.1234/a"]

    def test_exclut_les_doi_inconnus_de_doi_org(self, sa_sync_conn):
        """Un DOI inconnu de doi.org est exclu pour toutes les cibles, quelle que soit la date de l'échec."""
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
        """L'échec d'un DOI dans HAL laisse ce DOI parmi les DOI à chercher dans OpenAlex."""
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
        # La relecture par identifiant de la source est indépendante du DOI.
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
        # W1 est hors de la fenêtre, W2 dedans. W3, sans enregistrement source, n'a pas d'année : il est gardé.
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
    """Régression : les préfixes des DOI cibles de relations et des DOI dérivés d'arXiv restaient sans agence d'enregistrement. Les préfixes à résoudre viennent de la vue `candidate_dois`, comme les DOI de la recherche par DOI."""

    def test_pool_covers_relation_and_arxiv_prefixes(self, sa_sync_conn):
        from pipeline.transformation.publishing.doi_prefixes import DoiPrefixStore

        # Préfixe présent seulement dans le DOI cible d'une relation, depuis une publication du périmètre.
        _publication(sa_sync_conn, "P", row_id=1, in_perimeter=True)
        insert_publication_relation(
            sa_sync_conn,
            1,
            relation_type="is_preprint_of",
            source="crossref",
            target_doi="10.77777/rel",
        )
        # Préfixe présent seulement dans le DOI DataCite dérivé de l'identifiant arXiv d'un enregistrement source du périmètre.
        _source_record(
            sa_sync_conn,
            1,
            source="openalex",
            source_id="W1",
            identifiers=secondary_identifiers({"arxiv_id": "2605.02321"}),
        )

        prefixes = DoiPrefixStore(sa_sync_conn).get_prefixes_to_resolve()
        assert "10.77777" in prefixes  # cible de relation
        assert "10.48550" in prefixes  # DOI dérivé d'arXiv
