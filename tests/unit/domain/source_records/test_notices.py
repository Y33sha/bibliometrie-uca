"""Signaux d'avis propres à un enregistrement source : mises à jour Crossref, référence en fin de titre WoS."""

from domain.source_records.notices import (
    CorrectedArticle,
    corrected_work_doi,
    notice_doc_type,
    withdrawn_original_doi,
    wos_corrected_article,
)


class TestCorrectedWorkDoi:
    def test_single_declared_work(self):
        extras = {
            "update_to": [
                {"doi": "10.1/article", "type": "addendum", "source": "publisher"},
                {"doi": "10.1/article", "type": "retraction", "source": "retraction-watch"},
                {"doi": "10.1/notice", "type": "retraction", "source": "publisher"},
            ]
        }
        assert corrected_work_doi(extras, "10.1/notice") == "10.1/article"

    def test_several_declared_works(self):
        extras = {
            "update_to": [
                {"doi": "10.1/a", "type": "erratum", "source": "publisher"},
                {"doi": "10.1/b", "type": "erratum", "source": "publisher"},
            ]
        }
        assert corrected_work_doi(extras, "10.1/notice") is None

    def test_other_updates(self):
        extras = {"update_to": [{"doi": "10.1/a", "type": "new_version", "source": "publisher"}]}
        assert corrected_work_doi(extras, "10.1/notice") is None
        assert corrected_work_doi(None, "10.1/notice") is None


class TestWithdrawnOriginalDoi:
    def test_duplicate_declares_the_original(self):
        """Cas réel : la version française retirée déclare un retrait vers l'article de Joint Bone Spine."""
        extras = {
            "update_to": [
                {"doi": "10.1016/j.jbspin.2022.105478", "type": "withdrawal", "source": "publisher"}
            ]
        }
        assert (
            withdrawn_original_doi(extras, "10.1016/j.rhum.2022.12.007")
            == "10.1016/j.jbspin.2022.105478"
        )

    def test_withdrawal_in_place_or_other_updates(self):
        """Un retrait vers son propre DOI, ou une rétractation, ne désigne aucun original."""
        in_place = {"update_to": [{"doi": "10.1/a", "type": "withdrawal", "source": "publisher"}]}
        assert withdrawn_original_doi(in_place, "10.1/a") is None
        retraction = {"update_to": [{"doi": "10.1/b", "type": "retraction", "source": "publisher"}]}
        assert withdrawn_original_doi(retraction, "10.1/a") is None
        assert withdrawn_original_doi(None, "10.1/a") is None


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
