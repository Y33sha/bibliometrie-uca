"""Tests unitaires de `domain.source_publications.keys.project_confirmation_keys`.

Garde le contrat de la projection partagée : extraction et normalisation des clés de confirmation (DOI / NNT / PMID / HAL), token métadonnée thèse, substitution du DOI effectif Zenodo, et tolérance aux `external_ids` malformés.
"""

from __future__ import annotations

from domain.source_publications.keys import ConfirmationKeys, project_confirmation_keys


def _keys(doi=None, external_ids=None, doc_type=None, title_normalized=None, pub_year=None):
    """Appel avec valeurs par défaut neutres (non-thèse, sans titre/année)."""
    return project_confirmation_keys(doi, external_ids, doc_type, title_normalized, pub_year)


class TestDoi:
    def test_doi_from_column_normalized(self):
        """Le DOI de colonne est normalisé (casse, suffixe de version strippé)."""
        assert _keys("10.1234/ABC.v2").doi == "10.1234/abc"

    def test_doi_read_from_column_ignores_external_ids(self):
        """Le DOI vient de la colonne nue ; `external_ids.zenodo_concept_doi` (cache) est
        ignoré — la substitution concept est déjà persistée par `metadata_correction`."""
        keys = _keys("10.5281/zenodo.10", {"zenodo_concept_doi": "10.5281/zenodo.999"})
        assert keys.doi == "10.5281/zenodo.10"

    def test_no_doi(self):
        assert _keys(None, None).doi is None

    def test_blank_doi_dropped(self):
        """Un DOI vide / espaces seuls est écarté (le VO le rejette)."""
        assert _keys("   ").doi is None


class TestNnt:
    def test_nnt_normalized_uppercase(self):
        assert _keys(None, {"nnt": "2021clfac030"}).nnt == "2021CLFAC030"

    def test_nnt_absent(self):
        assert _keys(None, {"pmid": "12345"}).nnt is None


class TestPmid:
    def test_pmid_from_external_ids(self):
        assert _keys(None, {"pmid": "12345"}).pmid == "12345"

    def test_pmid_extracted_from_url(self):
        keys = _keys(None, {"pmid": "https://pubmed.ncbi.nlm.nih.gov/12345"})
        assert keys.pmid == "12345"


class TestHalIds:
    def test_hal_ids_list_normalized(self):
        """`hal_id` est multivalué : chaque élément est normalisé (sans version)."""
        keys = _keys(None, {"hal_id": ["hal-04123456v2", "tel-00112233"]})
        assert keys.hal_ids == ("hal-04123456", "tel-00112233")

    def test_hal_id_invalid_element_dropped(self):
        keys = _keys(None, {"hal_id": ["hal-04123456", "bogus"]})
        assert keys.hal_ids == ("hal-04123456",)

    def test_hal_id_not_a_list_ignored(self):
        """`hal_id` non-liste (forme inattendue) → ignoré, pas de crash."""
        assert _keys(None, {"hal_id": "hal-04123456"}).hal_ids == ()


class TestThesisMeta:
    def test_thesis_with_title_and_year(self):
        """doc_type thèse + titre + année → clé composite `<titre>|<année>`."""
        keys = _keys(doc_type="thesis", title_normalized="ma these", pub_year=2020)
        assert keys.thesis_meta == "ma these|2020"

    def test_ongoing_thesis_also_token(self):
        keys = _keys(doc_type="ongoing_thesis", title_normalized="ma these", pub_year=2021)
        assert keys.thesis_meta == "ma these|2021"

    def test_non_thesis_doc_type_no_token(self):
        """Un article au même titre+année ne porte pas de token thèse."""
        keys = _keys(doc_type="article", title_normalized="ma these", pub_year=2020)
        assert keys.thesis_meta is None

    def test_thesis_without_title_no_token(self):
        assert _keys(doc_type="thesis", title_normalized="", pub_year=2020).thesis_meta is None

    def test_thesis_without_year_no_token(self):
        keys = _keys(doc_type="thesis", title_normalized="ma these", pub_year=None)
        assert keys.thesis_meta is None


class TestMalformedExternalIds:
    def test_none_external_ids(self):
        assert _keys("10.1/x") == ConfirmationKeys(
            doi="10.1/x", nnt=None, pmid=None, hal_ids=(), thesis_meta=None
        )

    def test_non_str_values_ignored(self):
        """`external_ids` peut porter des listes (issn/isbn) ou None : ignorés sans crash."""
        keys = _keys(None, {"issn": ["0028-0836"], "nnt": None, "pmid": "12345"})
        assert keys == ConfirmationKeys(
            doi=None, nnt=None, pmid="12345", hal_ids=(), thesis_meta=None
        )


class TestTokens:
    def test_tokens_namespaced_by_type(self):
        keys = ConfirmationKeys(
            doi="d", nnt="n", pmid="p", hal_ids=("h1", "h2"), thesis_meta="t|2020"
        )
        assert keys.tokens() == frozenset(
            {
                ("doi", "d"),
                ("nnt", "n"),
                ("pmid", "p"),
                ("hal_id", "h1"),
                ("hal_id", "h2"),
                ("thesis_meta", "t|2020"),
            }
        )

    def test_absent_keys_produce_no_token(self):
        keys = ConfirmationKeys(doi="d", nnt=None, pmid=None, hal_ids=(), thesis_meta=None)
        assert keys.tokens() == frozenset({("doi", "d")})

    def test_no_keys_empty_token_set(self):
        empty = ConfirmationKeys(doi=None, nnt=None, pmid=None, hal_ids=(), thesis_meta=None)
        assert empty.tokens() == frozenset()
