"""Tests unitaires de `domain.source_records.keys` : clés de confirmation et ancres DOI.

Contrat de la projection partagée : DOI actifs de rôle autre que `related`, clé de chaque type d'identifiant (rôle le plus fort, puis plus petite valeur, parmi les identifiants actifs), token métadonnée `metadata_block`.
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
    Derivation,
    DoiKeys,
    anchor_of,
    deposit_anchors,
    derivation,
    doi_anchors,
    project_confirmation_keys,
)

T, R = SourceIdentifierType, SourceIdentifierRole


def _keys(identifiers=(), doc_type=None, title_normalized=None, publication_year=None, **kw):
    """Appelle `project_confirmation_keys`, sans titre ni année par défaut."""
    return project_confirmation_keys(
        identifiers, doc_type, title_normalized, publication_year, **kw
    )


def _block(keys: ConfirmationKeys) -> str | None:
    """Renvoie le bloc de métadonnées des clés, `None` sans bloc."""
    return keys.single_valued.get("metadata_block")


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

    def test_preprint_server_dois_are_not_anchors(self):
        arxiv, article = "10.48550/arxiv.1", "10.1016/article"
        assert doi_anchors([DoiKeys(frozenset({arxiv})), DoiKeys(frozenset({article}))]) == {
            article
        }
        assert doi_anchors([DoiKeys(frozenset({arxiv}))]) == frozenset()
        assert doi_anchors(
            [DoiKeys(frozenset({arxiv})), DoiKeys(frozenset(), frozenset({article}))]
        ) == {article}

    def test_deposit_anchors_are_chosen_like_anchors(self):
        arxiv, ssrn = "10.48550/arxiv.1", "10.2139/ssrn.1"
        keys = [DoiKeys(frozenset({arxiv})), DoiKeys(frozenset(), frozenset({ssrn}))]
        assert deposit_anchors(keys) == {arxiv}

    def test_the_doi_of_a_copy_archive_is_not_an_anchor(self):
        desy, article = "10.3204/pubdb-2024-00624", "10.1016/article"
        keys = [DoiKeys(frozenset({desy}), doc_type="article"), DoiKeys(frozenset({article}))]
        assert doi_anchors(keys) == {article}

    def test_the_zenodo_doi_of_a_text_deposit_is_not_an_anchor(self):
        zenodo, article = "10.5281/zenodo.1", "10.1016/article"
        copy = DoiKeys(frozenset({zenodo}), doc_type="article")
        dataset = DoiKeys(frozenset({zenodo}), doc_type="dataset")
        assert doi_anchors([copy, DoiKeys(frozenset({article}))]) == {article}
        assert doi_anchors([dataset, DoiKeys(frozenset({article}))]) == {zenodo, article}

    def test_anchor_of_a_member(self):
        anchors = frozenset({"a", "b"})
        assert anchor_of(DoiKeys(frozenset({"a"}), frozenset({"b"})), anchors) == "a"
        assert anchor_of(DoiKeys(frozenset(), frozenset({"b", "x"})), anchors) == "b"
        assert anchor_of(DoiKeys(frozenset(), frozenset({"a", "b"})), anchors) is None

    def test_the_deposit_dois_of_a_member_are_not_its_anchors(self):
        """Un preprint cite l'article et un DOI Zenodo, ancre par l'enregistrement source d'un dataset : il rejoint l'article."""
        zenodo, article = "10.5281/zenodo.1", "10.1103/article"
        preprint = DoiKeys(frozenset(), frozenset({zenodo, article}), doc_type="preprint")
        assert anchor_of(preprint, frozenset({zenodo, article})) == article


class TestIdentifiers:
    def test_one_key_per_type(self):
        identifiers = [
            SourceIdentifier(T.NNT, "2021CLFAC030", R.PRIMARY),
            SourceIdentifier(T.PMID, "12345", R.SECONDARY),
            SourceIdentifier(T.ISBN, "9780306406157", R.SECONDARY),
        ]
        assert _keys(identifiers) == ConfirmationKeys(
            DoiKeys(), {"nnt": "2021CLFAC030", "pmid": "12345"}
        )

    def test_strongest_role_then_smallest_value(self):
        """La clé HAL est le `hal_id` dérivé ; à rôle égal, la plus petite valeur. Les autres ne relient rien."""
        identifiers = [
            SourceIdentifier(T.HAL_ID, "hal-00000001", R.SECONDARY),
            SourceIdentifier(T.HAL_ID, "hal-04123456", R.DERIVED),
            SourceIdentifier(T.PMID, "2", R.SECONDARY),
            SourceIdentifier(T.PMID, "1", R.SECONDARY),
        ]
        keys = _keys(identifiers)
        assert (keys.single_valued["hal_id"], keys.single_valued["pmid"]) == ("hal-04123456", "1")
        assert ("hal_id", "hal-00000001") not in keys.tokens()

    def test_removed_identifier_is_no_key(self):
        identifiers = [
            SourceIdentifier(T.HAL_ID, "hal-04123456", R.PRIMARY, "HAL_DEPOSIT_MISSING_TO_REMOVED"),
            SourceIdentifier(T.HAL_ID, "hal-00000001", R.SECONDARY),
        ]
        assert _keys(identifiers).single_valued["hal_id"] == "hal-00000001"

    def test_every_patent_publication_number_is_a_key(self):
        """Chaque numéro de publication actif, de rôle autre que `related`, est une clé. Le numéro de demande reste hors des clés."""
        identifiers = [
            SourceIdentifier(T.PATENT_PUBLICATION_NUMBER, "FR3053353", R.SECONDARY),
            SourceIdentifier(T.PATENT_PUBLICATION_NUMBER, "WO2018002556", R.SECONDARY),
            SourceIdentifier(T.PATENT_PUBLICATION_NUMBER, "EP1", R.RELATED),
            SourceIdentifier(T.PATENT_PUBLICATION_NUMBER, "EP2", R.SECONDARY, "REGLE"),
            SourceIdentifier(T.PATENT_APPLICATION_NUMBER, "FR1851441", R.SECONDARY),
        ]
        assert _keys(identifiers).tokens() == {
            ("patent_publication_number", "FR3053353"),
            ("patent_publication_number", "WO2018002556"),
        }


class TestMetadataBlock:
    LONG = "une communication scientifique au titre assez long"  # > 30 caractères

    def test_token_for_any_doc_type(self):
        """Un titre long et une année donnent le token `<doc_type>|<title>|<year>`, quel que soit le type de document, thèse comprise."""
        for dt in ("conference_paper", "book_chapter", "article", "thesis", "report"):
            keys = _keys(doc_type=dt, title_normalized=self.LONG, publication_year=2020)
            assert _block(keys) == f"{dt}|{self.LONG}|2020"

    def test_doc_type_in_key_separates_types(self):
        """Un même titre et une même année donnent deux clés différentes pour deux types de document."""
        article = _keys(doc_type="article", title_normalized=self.LONG, publication_year=2020)
        chapter = _keys(doc_type="book_chapter", title_normalized=self.LONG, publication_year=2020)
        assert _block(article) != _block(chapter)

    def test_short_title_no_token(self):
        """Un titre court ne donne aucun token : les titres génériques sont écartés."""
        keys = _keys(
            doc_type="conference_paper", title_normalized="court titre", publication_year=2020
        )
        assert _block(keys) is None

    def test_title_at_the_threshold_no_token(self):
        seuil = "a" * DISCRIMINANT_TITLE_MIN_LENGTH
        assert (
            _block(_keys(doc_type="article", title_normalized=seuil, publication_year=2020)) is None
        )
        assert _block(
            _keys(doc_type="article", title_normalized=seuil + "b", publication_year=2020)
        )

    def test_no_doc_type_no_token(self):
        keys = _keys(doc_type=None, title_normalized=self.LONG, publication_year=2020)
        assert _block(keys) is None

    def test_without_year_no_token(self):
        keys = _keys(doc_type="poster", title_normalized=self.LONG, publication_year=None)
        assert _block(keys) is None


class TestTokens:
    def test_tokens_namespaced_by_type(self):
        keys = ConfirmationKeys(
            DoiKeys(frozenset({"d"}), frozenset({"e"})),
            {
                "nnt": "n",
                "pmid": "p",
                "arxiv_id": "a",
                "hal_id": "h1",
                "metadata_block": "conference_paper|titre|2020",
            },
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
        assert ConfirmationKeys(DoiKeys(frozenset({"d"})), {}).tokens() == frozenset({("doi", "d")})

    def test_no_keys_empty_token_set(self):
        assert ConfirmationKeys(DoiKeys(), {}).tokens() == frozenset()


def test_derivation_lit_l_identifiant_primaire_et_l_identifiant_derive_actifs():
    hal, doi = SourceIdentifierType.HAL_ID, SourceIdentifierType.DOI
    identifiers = [
        SourceIdentifier(hal, "hal-1", SourceIdentifierRole.DERIVED),
        SourceIdentifier(doi, "10.1/x", SourceIdentifierRole.PRIMARY),
        SourceIdentifier(doi, "10.1/z", SourceIdentifierRole.SECONDARY),
    ]
    assert derivation(identifiers) == Derivation(("doi", "10.1/x"), ("hal_id", "hal-1"))


def test_derivation_ignore_un_identifiant_primaire_retire():
    removed = SourceIdentifier(
        SourceIdentifierType.DOI, "10.1/y", SourceIdentifierRole.PRIMARY, removed_by="RULE"
    )
    assert derivation([removed]) == Derivation()
