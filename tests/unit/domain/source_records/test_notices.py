"""Signaux d'avis propres à un enregistrement source : mises à jour Crossref, référence en fin de titre WoS."""

from domain.source_records.notices import CorrectedArticle, notice_doc_type, wos_corrected_article


class TestNoticeDocType:
    def test_correction(self):
        assert notice_doc_type({"correction"}) == "erratum"
        assert notice_doc_type({"addendum", "new_version"}) == "erratum"

    def test_retraction_wins(self):
        assert notice_doc_type({"erratum", "retraction"}) == "retraction"

    def test_other_updates(self):
        """Un retrait Elsevier est déclaré par le doublon retiré : l'enregistrement source reste un article."""
        assert notice_doc_type({"withdrawal"}) is None
        assert notice_doc_type({"new_version", "expression_of_concern"}) is None
        assert notice_doc_type(()) is None


class TestWosCorrectedArticle:
    def test_reference_with_page(self):
        assert wos_corrected_article(
            "Non-perennial segments in river networks (vol 4, pg 815, 2023)"
        ) == CorrectedArticle("Non-perennial segments in river networks", 2023)

    def test_reference_with_article_number(self):
        assert wos_corrected_article(
            "Geoconservation in France: History, Key Policies, and Current Tools (Vol. 15, 52, 2023)"
        ) == CorrectedArticle(
            "Geoconservation in France: History, Key Policies, and Current Tools", 2023
        )

    def test_reference_with_doi(self):
        """Cas réel : la référence donne le DOI de l'article à la place de la page."""
        assert wos_corrected_article(
            "Association of Rare Genetic Variants in Opioid Receptors with Tourette Syndrome (vol 9, 10.5334/tohm.464, 2019)"
        ) == CorrectedArticle(
            "Association of Rare Genetic Variants in Opioid Receptors with Tourette Syndrome", 2019
        )

    def test_title_without_reference(self):
        assert wos_corrected_article("Erratum to: Serum IL-33, a new marker") is None
        assert wos_corrected_article("(vol 11, pg 194, 2018)") is None
