"""Tests unitaires de `domain.source_records.keys.project_confirmation_keys`.

Garde le contrat de la projection partagée : DOI de la colonne, identifiants qui sont des clés de confirmation selon leur type, leur rôle et leur statut, token métadonnée `metadata_block`.
"""

from __future__ import annotations

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.keys import (
    DISCRIMINANT_TITLE_MIN_LENGTH,
    ConfirmationKeys,
    project_confirmation_keys,
)

T, R = SourceIdentifierType, SourceIdentifierRole


def _keys(doi=None, identifiers=(), doc_type=None, title_normalized=None, publication_year=None):
    """Appel avec valeurs par défaut neutres (sans titre/année)."""
    return project_confirmation_keys(doi, identifiers, doc_type, title_normalized, publication_year)


class TestDoi:
    def test_doi_from_column_normalized(self):
        """Le DOI de colonne est normalisé (casse, suffixe de version strippé)."""
        assert _keys("10.1234/ABC.v2").doi == "10.1234/abc"

    def test_doi_identifiers_are_no_keys(self):
        """Le DOI vient de la colonne nue : un DOI de la table ne sert pas de clé."""
        keys = _keys(
            "10.5281/zenodo.10", [SourceIdentifier(T.DOI, "10.5281/zenodo.999", R.RELATED)]
        )
        assert keys.tokens() == frozenset({("doi", "10.5281/zenodo.10")})

    def test_no_doi(self):
        assert _keys(None).doi is None

    def test_blank_doi_dropped(self):
        """Un DOI vide / espaces seuls est écarté (le VO le rejette)."""
        assert _keys("   ").doi is None


class TestIdentifiers:
    def test_nnt_pmid_arxiv_keys_whatever_their_role(self):
        identifiers = [
            SourceIdentifier(T.NNT, "2021CLFAC030", R.PRIMARY),
            SourceIdentifier(T.PMID, "12345", R.SECONDARY),
            SourceIdentifier(T.ARXIV_ID, "2301.12345", R.DERIVED),
        ]
        assert _keys(None, identifiers).identifiers == frozenset(
            {("nnt", "2021CLFAC030"), ("pmid", "12345"), ("arxiv_id", "2301.12345")}
        )

    def test_hal_id_key_when_primary_or_derived(self):
        identifiers = [
            SourceIdentifier(T.HAL_ID, "hal-04123456", R.DERIVED),
            SourceIdentifier(T.HAL_ID, "tel-00112233", R.SECONDARY),
        ]
        assert _keys(None, identifiers).identifiers == frozenset({("hal_id", "hal-04123456")})

    def test_removed_identifier_is_no_key(self):
        removed = SourceIdentifier(
            T.HAL_ID, "hal-04123456", R.PRIMARY, "HAL_DEPOSIT_MISSING_TO_REMOVED"
        )
        assert _keys(None, [removed]).identifiers == frozenset()

    def test_related_and_other_types_are_no_keys(self):
        identifiers = [
            SourceIdentifier(T.PMID, "12345", R.RELATED),
            SourceIdentifier(T.ISBN, "9780306406157", R.SECONDARY),
        ]
        assert _keys(None, identifiers).identifiers == frozenset()


class TestMetadataBlock:
    LONG = "une communication scientifique au titre assez long"  # > 30 caractères

    def test_token_for_any_doc_type(self):
        """Tout doc_type + titre long + année → `<doc_type>|<title>|<year>` (doc_type dans la clé).

        La thèse passe par ce même token (pas de `thesis_meta` séparé)."""
        for dt in ("conference_paper", "book_chapter", "article", "thesis", "report"):
            keys = _keys(doc_type=dt, title_normalized=self.LONG, publication_year=2020)
            assert keys.metadata_block == f"{dt}|{self.LONG}|2020"

    def test_doc_type_in_key_separates_types(self):
        """Même titre+année mais doc_type différents → clés différentes (pas de fusion cross-type)."""
        article = _keys(doc_type="article", title_normalized=self.LONG, publication_year=2020)
        chapter = _keys(doc_type="book_chapter", title_normalized=self.LONG, publication_year=2020)
        assert article.metadata_block != chapter.metadata_block

    def test_short_title_no_token(self):
        """Titre ≤ seuil → pas de token (garde de longueur, écarte les titres génériques)."""
        keys = _keys(
            doc_type="conference_paper", title_normalized="court titre", publication_year=2020
        )
        assert keys.metadata_block is None

    def test_title_at_the_threshold_no_token(self):
        seuil = "a" * DISCRIMINANT_TITLE_MIN_LENGTH
        assert (
            _keys(doc_type="article", title_normalized=seuil, publication_year=2020).metadata_block
            is None
        )
        assert _keys(
            doc_type="article", title_normalized=seuil + "b", publication_year=2020
        ).metadata_block

    def test_no_doc_type_no_token(self):
        keys = _keys(doc_type=None, title_normalized=self.LONG, publication_year=2020)
        assert keys.metadata_block is None

    def test_without_year_no_token(self):
        keys = _keys(doc_type="poster", title_normalized=self.LONG, publication_year=None)
        assert keys.metadata_block is None


class TestTokens:
    def test_tokens_namespaced_by_type(self):
        keys = ConfirmationKeys(
            doi="d",
            metadata_block="conference_paper|titre|2020",
            identifiers=frozenset({("nnt", "n"), ("hal_id", "h1")}),
        )
        assert keys.tokens() == frozenset(
            {
                ("doi", "d"),
                ("nnt", "n"),
                ("hal_id", "h1"),
                ("metadata_block", "conference_paper|titre|2020"),
            }
        )

    def test_absent_keys_produce_no_token(self):
        assert ConfirmationKeys(doi="d", metadata_block=None).tokens() == frozenset({("doi", "d")})

    def test_no_keys_empty_token_set(self):
        assert ConfirmationKeys(doi=None, metadata_block=None).tokens() == frozenset()
