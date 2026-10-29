"""Tests unitaires de `domain.source_records.keys` : clés de confirmation et ancres DOI.

Garde le contrat de la projection partagée : DOI actifs non liés, clé de chaque type d'identifiant (rôle le plus fort, puis plus petite valeur, parmi les identifiants actifs), token métadonnée `metadata_block`.
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
    DoiKeys,
    anchor_of,
    doi_anchors,
    project_confirmation_keys,
)

T, R = SourceIdentifierType, SourceIdentifierRole


def _keys(identifiers=(), doc_type=None, title_normalized=None, publication_year=None, **kw):
    """Appel avec valeurs par défaut neutres (sans titre/année)."""
    return project_confirmation_keys(
        identifiers, doc_type, title_normalized, publication_year, **kw
    )


def _none(**overrides):
    keys = dict.fromkeys(("nnt", "pmid", "arxiv_id", "hal_id", "metadata_block"))
    return ConfirmationKeys(**{"doi": DoiKeys(), **keys, **overrides})


class TestDoi:
    def test_active_unrelated_dois_by_role(self):
        identifiers = [
            SourceIdentifier(T.DOI, "10.1/article", R.DERIVED),
            SourceIdentifier(T.DOI, "10.48550/arxiv.1", R.SECONDARY),
            SourceIdentifier(T.DOI, "10.9/lie", R.RELATED),
            SourceIdentifier(T.DOI, "10.9/retire", R.SECONDARY, "OUVRAGE_VS_CHAPITRE"),
        ]
        assert _keys(identifiers).doi == DoiKeys(
            frozenset({"10.1/article"}), frozenset({"10.48550/arxiv.1"})
        )

    def test_target_replaces_the_doi_of_a_secondary_form(self):
        identifiers = [SourceIdentifier(T.DOI, "10.5281/zenodo.10", R.SECONDARY)]
        keys = _keys(identifiers, doi_targets={"10.5281/zenodo.10": "10.5281/zenodo.1"})
        assert keys.doi == DoiKeys(frozenset(), frozenset({"10.5281/zenodo.1"}))

    def test_no_doi(self):
        assert _keys().doi == DoiKeys()


class TestAnchors:
    def test_primary_or_derived_dois_are_the_anchors(self):
        keys = [DoiKeys(frozenset({"a"})), DoiKeys(frozenset(), frozenset({"x"}))]
        assert doi_anchors(keys) == {"a"}

    def test_without_primary_or_derived_doi_single_dois_are_the_anchors(self):
        keys = [DoiKeys(frozenset(), frozenset({"a"})), DoiKeys(frozenset(), frozenset({"a", "b"}))]
        assert doi_anchors(keys) == {"a"}

    def test_anchor_of_a_member(self):
        anchors = frozenset({"a", "b"})
        assert anchor_of(DoiKeys(frozenset({"a"}), frozenset({"b"})), anchors) == "a"
        assert anchor_of(DoiKeys(frozenset(), frozenset({"b", "x"})), anchors) == "b"
        assert anchor_of(DoiKeys(frozenset(), frozenset({"a", "b"})), anchors) is None


class TestIdentifiers:
    def test_one_key_per_type(self):
        identifiers = [
            SourceIdentifier(T.NNT, "2021CLFAC030", R.PRIMARY),
            SourceIdentifier(T.PMID, "12345", R.SECONDARY),
            SourceIdentifier(T.ARXIV_ID, "2301.12345", R.DERIVED),
            SourceIdentifier(T.ISBN, "9780306406157", R.SECONDARY),
        ]
        assert _keys(identifiers) == _none(nnt="2021CLFAC030", pmid="12345", arxiv_id="2301.12345")

    def test_strongest_role_then_smallest_value(self):
        """La clé HAL est le `hal_id` dérivé ; à rôle égal, la plus petite valeur. Les autres ne relient rien."""
        identifiers = [
            SourceIdentifier(T.HAL_ID, "hal-00000001", R.SECONDARY),
            SourceIdentifier(T.HAL_ID, "hal-04123456", R.DERIVED),
            SourceIdentifier(T.PMID, "2", R.SECONDARY),
            SourceIdentifier(T.PMID, "1", R.SECONDARY),
        ]
        keys = _keys(identifiers)
        assert (keys.hal_id, keys.pmid) == ("hal-04123456", "1")
        assert ("hal_id", "hal-00000001") not in keys.tokens()

    def test_removed_identifier_is_no_key(self):
        identifiers = [
            SourceIdentifier(T.HAL_ID, "hal-04123456", R.PRIMARY, "HAL_DEPOSIT_MISSING_TO_REMOVED"),
            SourceIdentifier(T.HAL_ID, "hal-00000001", R.SECONDARY),
        ]
        assert _keys(identifiers).hal_id == "hal-00000001"


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
        keys = _none(
            doi=DoiKeys(frozenset({"d"}), frozenset({"e"})),
            nnt="n",
            pmid="p",
            arxiv_id="a",
            hal_id="h1",
            metadata_block="conference_paper|titre|2020",
        )
        assert keys.tokens() == frozenset(
            {
                ("doi", "d"),
                ("doi", "e"),
                ("nnt", "n"),
                ("pmid", "p"),
                ("arxiv_id", "a"),
                ("hal_id", "h1"),
                ("metadata_block", "conference_paper|titre|2020"),
            }
        )

    def test_absent_keys_produce_no_token(self):
        assert _none(doi=DoiKeys(frozenset({"d"}))).tokens() == frozenset({("doi", "d")})

    def test_no_keys_empty_token_set(self):
        assert _none().tokens() == frozenset()
