"""Tests de `effective_metadata` (correction des métadonnées canoniques)."""

from domain.source_publications.correction import (
    CorrectedFields,
    MetadataCorrectionRule,
    SourcePublicationForCorrection,
    effective_metadata,
)


def _view(**overrides: object) -> SourcePublicationForCorrection:
    defaults: dict[str, object] = {
        "id": 1,
        "source": "openalex",
        "source_id": "W42",
        "title": "Some title",
        "pub_year": None,
        "doc_type": None,
        "doi": None,
        "journal_id": None,
        "oa_status": None,
        "container_title": None,
        "language": None,
        "urls": (),
        "external_ids": {},
        "journal_type": None,
        "oa_model": None,
        "apc_amount": None,
        "raw_metadata": {},
        "embargo_expired": False,
    }
    defaults.update(overrides)
    return SourcePublicationForCorrection(**defaults)  # type: ignore[arg-type]


class TestCorrectedFields:
    def test_is_empty_on_default(self):
        assert CorrectedFields().is_empty()

    def test_is_not_empty_with_a_correction(self):
        fields = effective_metadata(_view(urls=("https://theses.fr/2024XYZ",)))
        assert not fields.is_empty()


class TestThesesFrRule:
    def test_theses_fr_url_corrects_to_thesis(self):
        view = _view(doc_type="article", urls=("https://theses.fr/s123456789",))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"
        assert corrected.rule == MetadataCorrectionRule.THESES_FR_URL_TO_THESIS

    def test_theses_fr_wins_over_dumas(self):
        # Une vue portant les deux marqueurs : theses.fr fait autorité.
        view = _view(
            doc_type="dissertation",
            urls=("https://theses.fr/s1", "https://dumas.ccsd.cnrs.fr/dumas-1"),
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"

    def test_no_theses_fr_url_no_correction(self):
        view = _view(doc_type="article", urls=("https://example.com/paper",))
        assert effective_metadata(view).doc_type is None


class TestDumasRule:
    def test_dumas_url_corrects_to_memoir(self):
        view = _view(doc_type="dissertation", urls=("https://dumas.ccsd.cnrs.fr/dumas-12345",))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "memoir"
        assert corrected.rule == MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR

    def test_dumas_url_corrects_regardless_of_doc_type(self):
        # Règle dure URL-only : un `doc_type` brut OpenAlex « article » (mésclassement
        # ou entité mêlant thèse + article) passe quand même en `memoir`.
        view = _view(doc_type="article", urls=("https://dumas.ccsd.cnrs.fr/dumas-1",))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "memoir"

    def test_no_dumas_url_no_correction(self):
        view = _view(doc_type="dissertation", urls=("https://example.com/x",))
        assert effective_metadata(view).doc_type is None


class TestThesisWithJournalRule:
    # Famille thèse + journal_id + DOI d'éditeur ⇒ article ; DOI de registre de thèses (ABES) ou
    # pas de DOI ⇒ pas de correction (le journal_id est parasite, conflation → relations).
    PUBLISHER_DOI = "10.1016/j.ex.2020.01.001"
    ABES_DOI = "10.70675/abc123"

    def test_thesis_with_journal_and_publisher_doi_corrects_to_article(self):
        view = _view(doc_type="thesis", journal_id=42, doi=self.PUBLISHER_DOI)
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "article"
        assert corrected.rule == MetadataCorrectionRule.THESIS_WITH_JOURNAL_TO_ARTICLE

    def test_ongoing_thesis_and_memoir_also_corrected(self):
        for doc_type in ("ongoing_thesis", "memoir"):
            view = _view(doc_type=doc_type, journal_id=42, doi=self.PUBLISHER_DOI)
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "article"

    def test_thesis_registry_doi_is_not_corrected(self):
        view = _view(doc_type="thesis", journal_id=42, doi=self.ABES_DOI)
        assert effective_metadata(view).doc_type is None

    def test_no_doi_is_not_corrected(self):
        view = _view(doc_type="thesis", journal_id=42, doi=None)
        assert effective_metadata(view).doc_type is None

    def test_no_journal_id_is_not_corrected(self):
        view = _view(doc_type="thesis", journal_id=None, doi=self.PUBLISHER_DOI)
        assert effective_metadata(view).doc_type is None

    def test_article_with_journal_is_spared(self):
        # `article` hors whitelist thèse : pas de bascule (rien à corriger).
        view = _view(doc_type="article", journal_id=42, doi=self.PUBLISHER_DOI)
        assert effective_metadata(view).doc_type is None


class TestTitleEditorialRule:
    def test_editorial_prefix_corrects_to_editorial(self):
        view = _view(doc_type="article", title="Editorial: The multifaceted roles of lipids")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "editorial"
        assert corrected.rule == MetadataCorrectionRule.TITLE_EDITORIAL_PREFIX_TO_EDITORIAL

    def test_editorial_without_colon_no_correction(self):
        # « Editorial Board », « Editorial comment »… ne sont pas le motif éditorial univoque.
        assert (
            effective_metadata(_view(doc_type="article", title="Editorial Board")).doc_type is None
        )

    def test_editorial_spares_reference_doc_types(self):
        assert effective_metadata(_view(doc_type="book", title="Editorial: X")).doc_type is None


class TestTitleLetterRule:
    def test_letter_prefix_corrects_to_letter(self):
        view = _view(doc_type="article", title="Letter: is the AHHS score really useful?")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "letter"
        assert corrected.rule == MetadataCorrectionRule.TITLE_LETTER_PREFIX_TO_LETTER

    def test_plural_letters_without_colon_no_correction(self):
        assert (
            effective_metadata(_view(doc_type="article", title="Letters from the field")).doc_type
            is None
        )


class TestTitleSystematicReviewRule:
    def test_prefix_corrects_to_review(self):
        view = _view(doc_type="article", title="Systematic review of atrial vascular access")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "review"
        assert corrected.rule == MetadataCorrectionRule.TITLE_SYSTEMATIC_REVIEW_TO_REVIEW

    def test_subtitle_after_colon_corrects_to_review(self):
        view = _view(
            doc_type="article", title="Impact of psychedelics on craving: a systematic review"
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "review"

    def test_mid_title_mention_not_corrected(self):
        # Étude primaire mentionnant une revue au fil du titre (ni début, ni après « : ») → épargnée.
        view = _view(
            doc_type="article", title="French cohort of systemic sclerosis and a systematic review"
        )
        assert effective_metadata(view).doc_type is None

    def test_spares_conference_paper(self):
        # Une revue systématique peut légitimement être un conference_paper : whitelist {article, other}.
        view = _view(
            doc_type="conference_paper", title="Systematic review of serious games on livestock"
        )
        assert effective_metadata(view).doc_type is None


class TestJournalTypeMediaRule:
    def test_journal_type_media_corrects_to_media(self):
        view = _view(doc_type="article", journal_type="media")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "media"
        assert corrected.rule == MetadataCorrectionRule.JOURNAL_TYPE_MEDIA_TO_MEDIA

    def test_journal_type_media_applies_regardless_of_raw_doc_type(self):
        # La règle est inconditionnelle sur `journal_type=media` : peu importe le
        # `doc_type` brut, la publication d'un journal média est reclassée.
        for raw in ("article", "review", "editorial", None):
            view = _view(doc_type=raw, journal_type="media")
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "media"

    def test_journal_type_non_media_no_correction(self):
        view = _view(doc_type="article", journal_type="journal")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_none_no_correction(self):
        # Cas dédup-entrée (pas de JOIN sur journals → journal_type=None) : la règle media ne fire pas.
        view = _view(doc_type="article", journal_type=None)
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_journal_type_media(self):
        # Une thèse hébergée sur theses.fr publiée par un journal typé media :
        # la cascade donne priorité à l'URL (autoritative sur le type de doc).
        view = _view(
            doc_type="article",
            urls=("https://theses.fr/s1",),
            journal_type="media",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"


class TestTitleSupplementaryContentRule:
    def test_additional_file_on_article_corrects_to_dataset(self):
        view = _view(doc_type="article", title="Additional file 1: Supplementary tables")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "dataset"
        assert corrected.rule == MetadataCorrectionRule.TITLE_SUPPLEMENTARY_CONTENT_TO_DATASET

    def test_supplementary_material_corrects_to_dataset(self):
        view = _view(doc_type="article", title="Supplementary material to seasonality of X")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "dataset"

    def test_supplementary_data_corrects_to_dataset(self):
        view = _view(doc_type="other", title="Supplementary data for desi dr1")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "dataset"

    def test_supplementary_information_corrects_to_dataset(self):
        view = _view(doc_type="article", title="Supplementary information: petrogenesis of X")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "dataset"

    def test_supplementary_file_plural_corrects_to_dataset(self):
        # Préfixe "supplementary file" couvre "file" et "files".
        view = _view(doc_type="other", title="Supplementary files from evolution of X")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "dataset"

    def test_supplementary_dataset_plural_corrects_to_dataset(self):
        view = _view(doc_type="other", title="Supplementary datasets for a major X")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "dataset"

    def test_data_from_corrects_to_dataset(self):
        view = _view(doc_type="article", title="Data from: Evolution of SARS-CoV-2 in Brazil")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "dataset"

    def test_rule_on_dataset_is_noop(self):
        # Déjà classé `dataset` : rien à corriger.
        view = _view(doc_type="dataset", title="Additional file 2: raw data")
        assert effective_metadata(view).doc_type is None

    def test_rule_on_unwhitelisted_type_is_spared(self):
        # `thesis` n'est pas dans la whitelist : titre suspect mais on ne corrige pas aveuglément.
        view = _view(doc_type="thesis", title="Additional file 1")
        assert effective_metadata(view).doc_type is None

    def test_unrelated_title_no_correction(self):
        view = _view(doc_type="article", title="Some real article title")
        assert effective_metadata(view).doc_type is None

    def test_supplementary_without_specific_subprefix_no_correction(self):
        # Le set est ciblé : "Supplementary roles of X" (vrai article hypothétique) ne matche aucun préfixe précis et reste tel quel.
        view = _view(doc_type="article", title="Supplementary roles of microbiota in X")
        assert effective_metadata(view).doc_type is None

    def test_match_is_case_insensitive_and_diacritic_insensitive(self):
        # `normalize_text` ramène à `lower()` + strip d'accents + collapse non-alphanum.
        for raw_title in ("Additional File 1", "ADDITIONAL FILE 1", "additional file 1"):
            view = _view(doc_type="article", title=raw_title)
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "dataset"

    def test_match_requires_prefix_not_substring(self):
        # Un titre qui *contient* "additional file" en milieu de phrase n'est pas un fichier complémentaire.
        view = _view(doc_type="article", title="An article about additional file formats")
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_supplementary_rule(self):
        # Combinaison improbable mais cascade-couverte : URL theses.fr autoritaire.
        view = _view(
            doc_type="article",
            title="Additional file 1",
            urls=("https://theses.fr/s1",),
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"


class TestJournalTypeProceedingsRule:
    def test_journal_type_proceedings_article_corrects(self):
        view = _view(doc_type="article", journal_type="proceedings")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "conference_paper"
        assert corrected.rule == MetadataCorrectionRule.JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER

    def test_journal_type_proceedings_book_chapter_corrects(self):
        view = _view(doc_type="book_chapter", journal_type="proceedings")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "conference_paper"

    def test_journal_type_proceedings_book_is_spared(self):
        # `book` hors whitelist : un volume entier d'actes peut rester `book`.
        view = _view(doc_type="book", journal_type="proceedings")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_proceedings_already_conference_paper_is_noop(self):
        view = _view(doc_type="conference_paper", journal_type="proceedings")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_non_proceedings_no_correction(self):
        view = _view(doc_type="article", journal_type="journal")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_none_no_correction(self):
        # Cas dédup-entrée (pas de JOIN sur journals → journal_type=None).
        view = _view(doc_type="article", journal_type=None)
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_journal_type_proceedings(self):
        # Cas combinaison improbable : URL theses.fr autoritaire.
        view = _view(
            doc_type="article",
            urls=("https://theses.fr/s1",),
            journal_type="proceedings",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "thesis"


class TestJournalTypePreprintServerRule:
    def test_journal_type_preprint_server_article_corrects(self):
        view = _view(doc_type="article", journal_type="preprint_server")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "preprint"
        assert corrected.rule == MetadataCorrectionRule.JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT

    def test_journal_type_preprint_server_other_corrects(self):
        view = _view(doc_type="other", journal_type="preprint_server")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "preprint"

    def test_journal_type_preprint_server_already_preprint_is_noop(self):
        view = _view(doc_type="preprint", journal_type="preprint_server")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_preprint_server_dataset_is_spared(self):
        # `dataset` hors whitelist : un dataset déposé sur arXiv/Zenodo reste dataset.
        view = _view(doc_type="dataset", journal_type="preprint_server")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_preprint_server_software_is_spared(self):
        view = _view(doc_type="software", journal_type="preprint_server")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_non_preprint_server_no_correction(self):
        view = _view(doc_type="article", journal_type="journal")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_none_no_correction(self):
        view = _view(doc_type="article", journal_type=None)
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_journal_type_preprint_server(self):
        view = _view(
            doc_type="article",
            urls=("https://theses.fr/s1",),
            journal_type="preprint_server",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "thesis"


class TestTitleMediaPrefixRule:
    def test_interview_prefix_on_other_corrects_to_media(self):
        view = _view(doc_type="other", title="Interview par France Inter sur l'agriculture")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "media"
        assert corrected.rule == MetadataCorrectionRule.TITLE_MEDIA_PREFIX_TO_MEDIA

    def test_podcast_prefix_corrects_to_media(self):
        view = _view(
            doc_type="other", title="Podcast Émission radio RCF : « Vous avez dit biz'arbres ? »"
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "media"

    def test_reportage_prefix_corrects_to_media(self):
        view = _view(doc_type="other", title="Reportage pour France 5 par Maxime Vautier")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "media"

    def test_article_with_interview_title_corrects(self):
        # OpenAlex classe parfois les interviews écrites en `article`.
        view = _view(doc_type="article", title="Interview of Teis Hansen, Full Professor")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "media"

    def test_rule_on_media_is_noop(self):
        # `media` hors whitelist : pas de re-correction.
        view = _view(doc_type="media", title="Interview RTL")
        assert effective_metadata(view).doc_type is None

    def test_rule_on_thesis_is_spared(self):
        # `thesis` hors whitelist : titre suspect mais on n'écrase pas.
        view = _view(doc_type="thesis", title="Interview as data collection method")
        assert effective_metadata(view).doc_type is None

    def test_unrelated_title_no_correction(self):
        view = _view(doc_type="article", title="Effects of soil nitrogen on plant growth")
        assert effective_metadata(view).doc_type is None

    def test_match_is_case_insensitive_and_diacritic_insensitive(self):
        for raw in ("INTERVIEW…", "interview …", "Interview…"):
            view = _view(doc_type="other", title=raw)
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "media"

    def test_match_requires_prefix_not_substring(self):
        # Un titre qui contient "interview" au milieu n'est pas une intervention média.
        view = _view(doc_type="article", title="A review of the interview methodology in HRM")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_media_wins_over_title_media_rule(self):
        # Les deux règles produisent `media` ; la priorité est sur journal_type
        # (signal admin-typé, plus fiable que l'heuristique titre).
        view = _view(doc_type="article", title="Interview pour France Inter", journal_type="media")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "media"
        assert corrected.rule == MetadataCorrectionRule.JOURNAL_TYPE_MEDIA_TO_MEDIA


class TestTitleErratumPrefixRule:
    def test_erratum_prefix_on_article_corrects_to_erratum(self):
        view = _view(doc_type="article", title="Erratum to: Search for X with the ATLAS detector")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "erratum"
        assert corrected.rule == MetadataCorrectionRule.TITLE_ERRATUM_PREFIX_TO_ERRATUM

    def test_errata_prefix_corrects_to_erratum(self):
        view = _view(doc_type="article", title="Errata: Measurement of Y at sqrt(s)=13 TeV")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "erratum"

    def test_corrigendum_prefix_corrects_to_erratum(self):
        view = _view(doc_type="article", title="Corrigendum to a study about Z")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "erratum"

    def test_preprint_with_erratum_title_corrects(self):
        # Audit a montré des errata CERN livrés comme `preprint` par OpenAlex.
        view = _view(doc_type="preprint", title="Erratum to: Search for CP violation")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "erratum"

    def test_data_paper_with_corrigendum_title_corrects(self):
        view = _view(doc_type="data_paper", title="Corrigendum to a clinical study")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "erratum"

    def test_rule_on_erratum_is_noop(self):
        # `erratum` n'est pas dans la whitelist : pas de re-correction.
        view = _view(doc_type="erratum", title="Erratum to: …")
        assert effective_metadata(view).doc_type is None

    def test_rule_on_thesis_is_spared(self):
        # `thesis` hors whitelist : titre suspect mais on n'écrase pas.
        view = _view(doc_type="thesis", title="Erratum to: a doctoral thesis")
        assert effective_metadata(view).doc_type is None

    def test_unrelated_title_no_correction(self):
        view = _view(doc_type="article", title="Some real article title")
        assert effective_metadata(view).doc_type is None

    def test_match_is_case_insensitive(self):
        for raw in ("ERRATUM TO: X", "erratum to: x", "Erratum To: x"):
            view = _view(doc_type="article", title=raw)
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "erratum"

    def test_match_requires_prefix_not_substring(self):
        # Un titre qui contient "erratum" au milieu n'est pas un erratum.
        view = _view(doc_type="article", title="A note about the erratum policy of the journal")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_media_wins_over_erratum_rule(self):
        # Cascade : la règle media (plus haute) gagne sur erratum (plus basse).
        view = _view(doc_type="article", title="Erratum to: X", journal_type="media")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "media"


class TestTitleRetractionPrefixRule:
    def test_retraction_notice_prefix_on_article_corrects(self):
        view = _view(
            doc_type="article",
            title="Retraction notice to “Value creation…” [IMM 104 (2022) 366–375]",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "retraction"
        assert corrected.rule == MetadataCorrectionRule.TITLE_RETRACTION_PREFIX_TO_RETRACTION

    def test_retraction_note_prefix_on_other_corrects(self):
        view = _view(
            doc_type="other",
            title="Retraction Note: Efficacy of vitamin C for the prevention of …",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "retraction"

    def test_strict_prefix_avoids_false_positive_on_retraction_alone(self):
        # Préfixe strict : "Retraction of consent in clinical trials" est un vrai
        # article sur la rétractation de consentement, pas un avis de rétractation.
        view = _view(doc_type="article", title="Retraction of consent in clinical trials")
        assert effective_metadata(view).doc_type is None

    def test_rule_on_retraction_is_noop(self):
        view = _view(doc_type="retraction", title="Retraction notice to …")
        assert effective_metadata(view).doc_type is None

    def test_rule_on_thesis_is_spared(self):
        # Hors whitelist `{article, other}`.
        view = _view(doc_type="thesis", title="Retraction note: a thesis on …")
        assert effective_metadata(view).doc_type is None

    def test_unrelated_title_no_correction(self):
        view = _view(doc_type="article", title="A regular article about science")
        assert effective_metadata(view).doc_type is None

    def test_match_is_case_insensitive(self):
        for raw in ("RETRACTION NOTICE TO X", "retraction notice to x", "Retraction Notice: x"):
            view = _view(doc_type="article", title=raw)
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "retraction"

    def test_match_requires_prefix_not_substring(self):
        view = _view(doc_type="article", title="An analysis of the retraction notice policy")
        assert effective_metadata(view).doc_type is None


class TestTitleIsbnBookReviewRule:
    def test_isbn_word_on_article_corrects(self):
        view = _view(
            doc_type="article",
            title="Compte rendu de l'ouvrage X, Éditions Y, 2020, ISBN 978-2-12345-678-9",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "book_review"
        assert corrected.rule == MetadataCorrectionRule.TITLE_ISBN_TO_BOOK_REVIEW

    def test_isbn_13_naked_corrects(self):
        # ISBN-13 nu sans le mot « ISBN ».
        view = _view(doc_type="review", title="Recension d'un livre, PUF, 2021, 978-2-13-082345-6")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "book_review"

    def test_isbn_on_other_corrects(self):
        view = _view(doc_type="other", title="CR : Étude sur Z, isbn 9782070123456")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "book_review"

    def test_isbn_on_book_is_spared(self):
        # `book` hors whitelist : un livre peut légitimement porter son propre
        # ISBN dans le titre (saisie HAL fréquente, faux positif sinon).
        view = _view(doc_type="book", title="Un vrai livre, Éditions Y, ISBN 978-2-12345-678-9")
        assert effective_metadata(view).doc_type is None

    def test_isbn_on_book_chapter_is_spared(self):
        view = _view(
            doc_type="book_chapter",
            title="Chapitre dans un ouvrage collectif ISBN 978-2-12345-678-9",
        )
        assert effective_metadata(view).doc_type is None

    def test_isbn_on_book_review_is_noop(self):
        view = _view(doc_type="book_review", title="Compte rendu, ISBN 978-2-12345-678-9")
        assert effective_metadata(view).doc_type is None

    def test_isbn_case_insensitive(self):
        for raw in ("ISBN 978-2-12345-678-9", "Isbn 978...", "compte rendu isbn 9782070123456"):
            view = _view(doc_type="article", title=raw)
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "book_review"

    def test_unrelated_title_no_correction(self):
        view = _view(doc_type="article", title="A regular article without book metadata")
        assert effective_metadata(view).doc_type is None

    def test_isbn_substring_not_matched(self):
        # `isbn` doit être un mot entier — ne pas matcher "Isbnxyz" ou "disbn".
        view = _view(doc_type="article", title="A study of Disbnophilia in laboratory mice")
        assert effective_metadata(view).doc_type is None

    def test_isbn_naked_requires_full_pattern(self):
        # Un nombre commençant par 978 mais trop court n'est pas un ISBN.
        view = _view(doc_type="article", title="Page 9785 of the journal")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_media_wins_over_isbn_rule(self):
        view = _view(
            doc_type="article",
            title="Recension d'un livre, ISBN 978-2-12345-678-9",
            journal_type="media",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "media"


class TestTitleYearPagesEndBookReviewRule:
    def test_year_pages_end_on_article_corrects(self):
        view = _view(
            doc_type="article",
            title="Auteur, Titre de l'ouvrage, Éditions Y, 2020, 244 p.",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "book_review"
        assert corrected.rule == MetadataCorrectionRule.TITLE_YEAR_PAGES_END_TO_BOOK_REVIEW

    def test_year_pages_pages_form_corrects(self):
        view = _view(doc_type="review", title="Auteur, Titre, PUF, 2019, 350 pages")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "book_review"

    def test_year_pages_pp_form_corrects(self):
        view = _view(doc_type="other", title="Auteur, Titre, Springer, 2021, 198 pp")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "book_review"

    def test_year_pages_on_book_is_spared(self):
        # `book` hors whitelist (vrais livres dont le titre porte leur propre
        # référence biblio — cf. audit 2026-05-28).
        view = _view(doc_type="book", title="Un vrai livre, Éditeur, 2020, 244 p")
        assert effective_metadata(view).doc_type is None

    def test_year_pages_on_book_review_is_noop(self):
        view = _view(doc_type="book_review", title="Recension d'un livre, 2020, 244 p")
        assert effective_metadata(view).doc_type is None

    def test_year_pages_requires_end_anchor(self):
        # Pattern « 2020, 244 p » au milieu d'un titre suivi d'autre chose
        # n'est pas le marqueur attendu.
        view = _view(
            doc_type="article",
            title="In 2020, 244 papers were published on the topic of climate change",
        )
        assert effective_metadata(view).doc_type is None

    def test_year_pages_case_insensitive(self):
        for suffix in ("2020, 244 P", "2020, 244 PAGES", "2020, 244 Pp"):
            view = _view(doc_type="article", title=f"Titre, Éditeur, {suffix}")
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "book_review"

    def test_isbn_wins_over_year_pages(self):
        # Les deux patterns matchent ; ISBN passe d'abord dans la cascade,
        # la règle ISBN posée gagne.
        view = _view(
            doc_type="article",
            title="Titre, Éditeur, ISBN 978-2-12345-678-9, 2020, 244 p",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.rule == MetadataCorrectionRule.TITLE_ISBN_TO_BOOK_REVIEW

    def test_unrelated_title_no_correction(self):
        view = _view(doc_type="article", title="Effects of soil nitrogen on plant growth")
        assert effective_metadata(view).doc_type is None


class TestDoiFigshareCollectionRule:
    COLL = "10.6084/m9.figshare.c.7654321"
    ITEM = "10.6084/m9.figshare.1234567"

    def test_collection_doi_corrects_to_dataset(self):
        corrected = effective_metadata(_view(doc_type="other", doi=self.COLL)).doc_type
        assert corrected is not None
        assert corrected.value == "dataset"
        assert corrected.rule == MetadataCorrectionRule.DOI_FIGSHARE_COLLECTION_TO_DATASET

    def test_article_collection_corrected(self):
        corrected = effective_metadata(_view(doc_type="article", doi=self.COLL)).doc_type
        assert corrected is not None and corrected.value == "dataset"

    def test_already_dataset_is_noop(self):
        assert effective_metadata(_view(doc_type="dataset", doi=self.COLL)).doc_type is None

    def test_figshare_item_not_matched(self):
        # un item figshare (pas de `.c.`) ne doit PAS matcher
        assert effective_metadata(_view(doc_type="other", doi=self.ITEM)).doc_type is None

    def test_non_figshare_doi_not_matched(self):
        assert (
            effective_metadata(_view(doc_type="other", doi="10.1038/nature12345")).doc_type is None
        )

    def test_no_doi_not_matched(self):
        assert effective_metadata(_view(doc_type="other", doi=None)).doc_type is None

    def test_doc_type_outside_whitelist_noop(self):
        # collection typée `book` (improbable) : pas corrigée aveuglément
        assert effective_metadata(_view(doc_type="book", doi=self.COLL)).doc_type is None

    def test_wins_over_title_supplement_rule(self):
        # même output (dataset) mais la règle DOI, plus en amont, est créditée
        corrected = effective_metadata(
            _view(doc_type="other", doi=self.COLL, title="Additional file 1 of X")
        ).doc_type
        assert corrected is not None
        assert corrected.rule == MetadataCorrectionRule.DOI_FIGSHARE_COLLECTION_TO_DATASET


class TestEmbargoExpiredRule:
    def test_expired_embargo_promoted_to_green(self):
        view = _view(oa_status="embargoed", embargo_expired=True)
        corrected = effective_metadata(view).oa_status
        assert corrected is not None
        assert corrected.value == "green"
        assert corrected.rule == MetadataCorrectionRule.EMBARGO_EXPIRED_TO_GREEN

    def test_active_embargo_not_promoted(self):
        # Embargo encore en cours (non expiré) → reste `embargoed`.
        assert (
            effective_metadata(_view(oa_status="embargoed", embargo_expired=False)).oa_status
            is None
        )

    def test_non_embargoed_status_untouched(self):
        # Un statut non-`embargoed` n'est pas concerné, même si `embargo_expired` est vrai.
        assert effective_metadata(_view(oa_status="green", embargo_expired=True)).oa_status is None
        assert effective_metadata(_view(oa_status="closed", embargo_expired=True)).oa_status is None


class TestEffectiveMetadataScope:
    def test_no_signals_no_correction(self):
        assert effective_metadata(_view()).is_empty()

    def test_only_doc_type_is_touched(self):
        # journal_id n'a aucune règle ; oa_status n'a que la règle embargo, ici non déclenchée
        # (gold non expiré). Seul doc_type pourrait être corrigé sur cette vue.
        view = _view(
            doc_type="article",
            urls=("https://theses.fr/s1",),
            journal_id=42,
            oa_status="gold",
        )
        fields = effective_metadata(view)
        assert fields.journal_id is None
        assert fields.oa_status is None
