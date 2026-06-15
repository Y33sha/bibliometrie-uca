"""Tests unitaires de `domain.source_publications.keys.project_confirmation_keys`.

Garde le contrat de la projection partagée : extraction et normalisation des clés de confirmation (DOI / NNT / PMID / HAL), substitution du DOI effectif Zenodo, et tolérance aux `external_ids` malformés.
"""

from __future__ import annotations

from domain.source_publications.keys import ConfirmationKeys, project_confirmation_keys


class TestDoi:
    def test_doi_from_column_normalized(self):
        """Le DOI de colonne est normalisé (casse, suffixe de version strippé)."""
        keys = project_confirmation_keys("10.1234/ABC.v2", None)
        assert keys.doi == "10.1234/abc"

    def test_doi_read_from_column_ignores_external_ids(self):
        """Le DOI vient de la colonne nue ; `external_ids.zenodo_concept_doi` (cache) est
        ignoré — la substitution concept est déjà persistée par `metadata_correction`."""
        keys = project_confirmation_keys(
            "10.5281/zenodo.10", {"zenodo_concept_doi": "10.5281/zenodo.999"}
        )
        assert keys.doi == "10.5281/zenodo.10"

    def test_no_doi(self):
        keys = project_confirmation_keys(None, None)
        assert keys.doi is None

    def test_blank_doi_dropped(self):
        """Un DOI vide / espaces seuls est écarté (le VO le rejette)."""
        keys = project_confirmation_keys("   ", None)
        assert keys.doi is None


class TestNnt:
    def test_nnt_normalized_uppercase(self):
        keys = project_confirmation_keys(None, {"nnt": "2021clfac030"})
        assert keys.nnt == "2021CLFAC030"

    def test_nnt_absent(self):
        keys = project_confirmation_keys(None, {"pmid": "12345"})
        assert keys.nnt is None


class TestPmid:
    def test_pmid_from_external_ids(self):
        keys = project_confirmation_keys(None, {"pmid": "12345"})
        assert keys.pmid == "12345"

    def test_pmid_extracted_from_url(self):
        keys = project_confirmation_keys(None, {"pmid": "https://pubmed.ncbi.nlm.nih.gov/12345"})
        assert keys.pmid == "12345"


class TestHalIds:
    def test_hal_ids_list_normalized(self):
        """`hal_id` est multivalué : chaque élément est normalisé (sans version)."""
        keys = project_confirmation_keys(None, {"hal_id": ["hal-04123456v2", "tel-00112233"]})
        assert keys.hal_ids == ("hal-04123456", "tel-00112233")

    def test_hal_id_invalid_element_dropped(self):
        keys = project_confirmation_keys(None, {"hal_id": ["hal-04123456", "bogus"]})
        assert keys.hal_ids == ("hal-04123456",)

    def test_hal_id_not_a_list_ignored(self):
        """`hal_id` non-liste (forme inattendue) → ignoré, pas de crash."""
        keys = project_confirmation_keys(None, {"hal_id": "hal-04123456"})
        assert keys.hal_ids == ()


class TestMalformedExternalIds:
    def test_none_external_ids(self):
        keys = project_confirmation_keys("10.1/x", None)
        assert keys == ConfirmationKeys(doi="10.1/x", nnt=None, pmid=None, hal_ids=())

    def test_non_str_values_ignored(self):
        """`external_ids` peut porter des listes (issn/isbn) ou None : ignorés sans crash."""
        keys = project_confirmation_keys(
            None, {"issn": ["0028-0836"], "nnt": None, "pmid": "12345"}
        )
        assert keys == ConfirmationKeys(doi=None, nnt=None, pmid="12345", hal_ids=())


class TestTokens:
    def test_tokens_namespaced_by_type(self):
        keys = ConfirmationKeys(doi="d", nnt="n", pmid="p", hal_ids=("h1", "h2"))
        assert keys.tokens() == frozenset(
            {("doi", "d"), ("nnt", "n"), ("pmid", "p"), ("hal_id", "h1"), ("hal_id", "h2")}
        )

    def test_absent_keys_produce_no_token(self):
        keys = ConfirmationKeys(doi="d", nnt=None, pmid=None, hal_ids=())
        assert keys.tokens() == frozenset({("doi", "d")})

    def test_no_keys_empty_token_set(self):
        assert ConfirmationKeys(doi=None, nnt=None, pmid=None, hal_ids=()).tokens() == frozenset()
