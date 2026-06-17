"""Tests unitaires de `domain.source_publications.keys.project_confirmation_keys`.

Garde le contrat de la projection partagée : extraction et normalisation des clés de confirmation (DOI / NNT / PMID / HAL), token métadonnée `metadata_block`, et tolérance aux `external_ids` malformés.
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


class TestMetadataBlock:
    LONG = "une communication scientifique au titre assez long"  # > 30 caractères

    def test_token_for_any_doc_type(self):
        """Tout doc_type + titre long + année → `<doc_type>|<title>|<year>` (doc_type dans la clé).

        La thèse passe par ce même token (pas de `thesis_meta` séparé)."""
        for dt in ("conference_paper", "book_chapter", "article", "thesis", "report"):
            keys = _keys(doc_type=dt, title_normalized=self.LONG, pub_year=2020)
            assert keys.metadata_block == f"{dt}|{self.LONG}|2020"

    def test_doc_type_in_key_separates_types(self):
        """Même titre+année mais doc_type différents → clés différentes (pas de fusion cross-type)."""
        article = _keys(doc_type="article", title_normalized=self.LONG, pub_year=2020)
        chapter = _keys(doc_type="book_chapter", title_normalized=self.LONG, pub_year=2020)
        assert article.metadata_block != chapter.metadata_block

    def test_short_title_no_token(self):
        """Titre ≤ seuil → pas de token (garde de longueur, écarte les titres génériques)."""
        keys = _keys(doc_type="conference_paper", title_normalized="court titre", pub_year=2020)
        assert keys.metadata_block is None

    def test_no_doc_type_no_token(self):
        keys = _keys(doc_type=None, title_normalized=self.LONG, pub_year=2020)
        assert keys.metadata_block is None

    def test_without_year_no_token(self):
        keys = _keys(doc_type="poster", title_normalized=self.LONG, pub_year=None)
        assert keys.metadata_block is None


class TestMalformedExternalIds:
    def test_none_external_ids(self):
        assert _keys("10.1/x") == ConfirmationKeys(
            doi="10.1/x", nnt=None, pmid=None, hal_ids=(), metadata_block=None
        )

    def test_non_str_values_ignored(self):
        """`external_ids` peut porter des listes (issn/isbn) ou None : ignorés sans crash."""
        keys = _keys(None, {"issn": ["0028-0836"], "nnt": None, "pmid": "12345"})
        assert keys == ConfirmationKeys(
            doi=None, nnt=None, pmid="12345", hal_ids=(), metadata_block=None
        )


class TestTokens:
    def test_tokens_namespaced_by_type(self):
        keys = ConfirmationKeys(
            doi="d",
            nnt="n",
            pmid="p",
            hal_ids=("h1", "h2"),
            metadata_block="conference_paper|titre|2020",
        )
        assert keys.tokens() == frozenset(
            {
                ("doi", "d"),
                ("nnt", "n"),
                ("pmid", "p"),
                ("hal_id", "h1"),
                ("hal_id", "h2"),
                ("metadata_block", "conference_paper|titre|2020"),
            }
        )

    def test_absent_keys_produce_no_token(self):
        keys = ConfirmationKeys(doi="d", nnt=None, pmid=None, hal_ids=(), metadata_block=None)
        assert keys.tokens() == frozenset({("doi", "d")})

    def test_no_keys_empty_token_set(self):
        empty = ConfirmationKeys(doi=None, nnt=None, pmid=None, hal_ids=(), metadata_block=None)
        assert empty.tokens() == frozenset()
