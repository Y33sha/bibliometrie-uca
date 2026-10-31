"""Règles de correction des métadonnées d'un enregistrement source (`effective_metadata`)."""

import pytest

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.metadata_correction.rules import (
    MetadataCorrectionRule,
    MetadataForCorrection,
    _check_predicate,
    effective_metadata,
    is_dissertation_identifier,
)


def _publication(**overrides: object) -> MetadataForCorrection:
    defaults: dict[str, object] = {
        "title": "Some title",
        "doc_type": None,
        "doi": None,
        "serial_id": None,
        "serial_type": None,
    }
    defaults.update(overrides)
    return MetadataForCorrection.for_publication(**defaults)  # type: ignore[arg-type]


def _view(doi: str | None = None, **overrides: object) -> MetadataForCorrection:
    """Construit les faits d'un enregistrement source.

    Args:
        doi: seul DOI propre de l'enregistrement source.
    """
    defaults: dict[str, object] = {
        "title": "Some title",
        "doc_type": None,
        "dois": frozenset({doi} if doi else ()),
        "serial_id": None,
        "urls": (),
        "serial_type": None,
        "self_declared_preprint": False,
        "declares_conference": False,
    }
    defaults.update(overrides)
    return MetadataForCorrection(**defaults)  # type: ignore[arg-type]


class TestPredicates:
    def test_title_prefix_needs_a_title(self):
        """Sans titre, aucune règle de préfixe de titre ne s'applique."""
        assert effective_metadata(_view(doc_type="article", title="")).doc_type is None

    def test_unknown_predicate_is_named(self):
        with pytest.raises(ValueError, match="Prédicat inconnu : 'inconnu'"):
            _check_predicate(_view(), "inconnu", True)


def _identifier(id_type: SourceIdentifierType, value: str) -> SourceIdentifier:
    return SourceIdentifier(id_type, value, SourceIdentifierRole.SECONDARY)


class TestIsDissertationIdentifier:
    def test_nnt_and_dissertation_hal_ids(self):
        assert is_dissertation_identifier(_identifier(SourceIdentifierType.NNT, "2021CLFAC030"))
        assert is_dissertation_identifier(_identifier(SourceIdentifierType.HAL_ID, "tel-01234567"))
        assert is_dissertation_identifier(
            _identifier(SourceIdentifierType.HAL_ID, "dumas-07654321")
        )

    def test_article_identifiers(self):
        assert not is_dissertation_identifier(
            _identifier(SourceIdentifierType.HAL_ID, "hal-04123456")
        )
        assert not is_dissertation_identifier(_identifier(SourceIdentifierType.DOI, "10.1/x"))


class TestThesesFrRule:
    def test_theses_fr_url_corrects_to_thesis(self):
        view = _view(doc_type="article", urls=("https://theses.fr/s123456789",))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"
        assert corrected.rule == MetadataCorrectionRule.THESES_FR_URL_TO_THESIS

    def test_theses_fr_wins_over_dumas(self):
        # Vue qui a les deux URL : theses.fr prime.
        view = _view(
            doc_type="thesis",
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
        view = _view(doc_type="thesis", urls=("https://dumas.ccsd.cnrs.fr/dumas-12345",))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "memoir"
        assert corrected.rule == MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR

    def test_dumas_url_corrects_regardless_of_doc_type(self):
        # La règle lit seulement l'URL : un `article` passe aussi en `memoir`.
        view = _view(doc_type="article", urls=("https://dumas.ccsd.cnrs.fr/dumas-1",))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "memoir"

    def test_dumas_url_spares_practice_thesis(self):
        # Le diplôme du dépôt HAL fait de la thèse d'exercice un type à part.
        view = _view(doc_type="practice_thesis", urls=("https://dumas.ccsd.cnrs.fr/dumas-1",))
        assert effective_metadata(view).doc_type is None

    def test_no_dumas_url_no_correction(self):
        view = _view(doc_type="thesis", urls=("https://example.com/x",))
        assert effective_metadata(view).doc_type is None


class TestThesisWithSerialRule:
    # Type de la famille thèse, avec revue et DOI d'éditeur : article. Avec un DOI du registre des thèses (ABES), ou sans DOI, la revue est parasite et le type reste.
    PUBLISHER_DOI = "10.1016/j.ex.2020.01.001"
    ABES_DOI = "10.70675/abc123"

    def test_thesis_with_serial_and_publisher_doi_corrects_to_article(self):
        view = _view(doc_type="thesis", serial_id=42, doi=self.PUBLISHER_DOI)
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "article"
        assert corrected.rule == MetadataCorrectionRule.THESIS_WITH_SERIAL_TO_ARTICLE

    def test_ongoing_thesis_and_memoir_also_corrected(self):
        for doc_type in ("ongoing_thesis", "memoir"):
            view = _view(doc_type=doc_type, serial_id=42, doi=self.PUBLISHER_DOI)
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "article"

    def test_thesis_registry_doi_is_not_corrected(self):
        view = _view(doc_type="thesis", serial_id=42, doi=self.ABES_DOI)
        assert effective_metadata(view).doc_type is None

    def test_registry_prefix_is_read_before_the_first_slash(self):
        """Un DOI de registre dont le suffixe contient lui-même une barre oblique reste un DOI de registre."""
        view = _view(doc_type="thesis", serial_id=42, doi="10.70675/abc/123")
        assert effective_metadata(view).doc_type is None

    def test_no_doi_is_not_corrected(self):
        view = _view(doc_type="thesis", serial_id=42, doi=None)
        assert effective_metadata(view).doc_type is None

    def test_publisher_doi_among_registry_dois_corrects_to_article(self):
        view = _view(
            doc_type="thesis", serial_id=42, dois=frozenset({self.ABES_DOI, self.PUBLISHER_DOI})
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "article"

    def test_no_serial_id_is_not_corrected(self):
        view = _view(doc_type="thesis", serial_id=None, doi=self.PUBLISHER_DOI)
        assert effective_metadata(view).doc_type is None

    def test_article_with_serial_is_spared(self):
        # `article` est hors des types corrigés par la règle.
        view = _view(doc_type="article", serial_id=42, doi=self.PUBLISHER_DOI)
        assert effective_metadata(view).doc_type is None


class TestTitleEditorialRule:
    def test_editorial_prefix_corrects_to_editorial(self):
        view = _view(doc_type="article", title="Editorial: The multifaceted roles of lipids")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "editorial"
        assert corrected.rule == MetadataCorrectionRule.TITLE_EDITORIAL_PREFIX_TO_EDITORIAL

    def test_editorial_without_colon_no_correction(self):
        # « Editorial Board », « Editorial comment »… : motif éditorial ambigu.
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
        # Étude primaire qui mentionne une revue au fil du titre (ni au début, ni après « : ») : type conservé.
        view = _view(
            doc_type="article", title="French cohort of systemic sclerosis and a systematic review"
        )
        assert effective_metadata(view).doc_type is None

    def test_spares_conference_paper(self):
        # Une revue systématique peut être un `conference_paper` : la règle corrige seulement `article` et `other`.
        view = _view(
            doc_type="conference_paper", title="Systematic review of serious games on livestock"
        )
        assert effective_metadata(view).doc_type is None


class TestSerialTypeMediaRule:
    def test_serial_type_media_corrects_to_media(self):
        view = _view(doc_type="article", serial_type="media")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "media"
        assert corrected.rule == MetadataCorrectionRule.SERIAL_TYPE_MEDIA_TO_MEDIA

    def test_serial_type_media_applies_regardless_of_doc_type(self):
        # La règle dépend seulement de `serial_type=media` : la publication d'un journal média est reclassée quel que soit son `doc_type`.
        for doc_type in ("article", "review", "editorial", None):
            view = _view(doc_type=doc_type, serial_type="media")
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "media"

    def test_serial_type_non_media_no_correction(self):
        view = _view(doc_type="article", serial_type="journal")
        assert effective_metadata(view).doc_type is None

    def test_serial_type_none_no_correction(self):
        # Sans type de revue (`serial_type=None`), la règle media est inactive.
        view = _view(doc_type="article", serial_type=None)
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_serial_type_media(self):
        # Thèse sur theses.fr, publiée par une revue de type media : la règle de l'URL prime.
        view = _view(
            doc_type="article",
            urls=("https://theses.fr/s1",),
            serial_type="media",
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

    def test_additional_file_on_conference_corrects_to_dataset(self):
        # figshare type `Presentation` certains fichiers complémentaires d'articles.
        view = _view(doc_type="conference", title="Additional file 1 of COVID-19 associated X")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "dataset"

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

    def test_supporting_movies_on_recorded_talk_corrects_to_dataset(self):
        # DataCite `Audiovisual` : vidéos jointes à un article.
        view = _view(
            doc_type="recorded_talk",
            title="Supporting Movies from: Seismo-acoustic observations of crashing ocean waves",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "dataset"

    def test_supplementary_videos_corrects_to_dataset(self):
        view = _view(
            doc_type="recorded_talk",
            title="Supplementary videos for 'Driven shear flow in biological magneto-active fluids'",
        )
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
        # `thesis` est hors des types corrigés par la règle, malgré le titre suspect.
        view = _view(doc_type="thesis", title="Additional file 1")
        assert effective_metadata(view).doc_type is None

    def test_unrelated_title_no_correction(self):
        view = _view(doc_type="article", title="Some real article title")
        assert effective_metadata(view).doc_type is None

    def test_supplementary_without_specific_subprefix_no_correction(self):
        # « Supplementary roles of X » (titre d'article plausible) ne commence par aucun préfixe de la liste : type conservé.
        view = _view(doc_type="article", title="Supplementary roles of microbiota in X")
        assert effective_metadata(view).doc_type is None

    def test_match_is_case_insensitive_and_diacritic_insensitive(self):
        # Le titre est comparé normalisé : minuscules, sans accents, ponctuation réduite à des espaces.
        for raw_title in ("Additional File 1", "ADDITIONAL FILE 1", "additional file 1"):
            view = _view(doc_type="article", title=raw_title)
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "dataset"

    def test_match_requires_prefix_not_substring(self):
        # Un titre qui *contient* "additional file" en milieu de phrase n'est pas un fichier complémentaire.
        view = _view(doc_type="article", title="An article about additional file formats")
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_supplementary_rule(self):
        # Combinaison improbable : la règle de l'URL theses.fr prime.
        view = _view(
            doc_type="article",
            title="Additional file 1",
            urls=("https://theses.fr/s1",),
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"


class TestDoiRegistrantMediaRule:
    def test_doi_depose_par_un_editeur_de_presse_devient_media(self):
        """Cas réel : article de The Conversation, typé `posted-content` par Crossref, sans revue."""
        corrected = effective_metadata(
            _view(doc_type="preprint", registrant_publisher_types=frozenset({"media"}))
        ).doc_type
        assert corrected is not None
        assert corrected.value == "media"
        assert corrected.rule == MetadataCorrectionRule.DOI_REGISTRANT_MEDIA_TO_MEDIA

    def test_un_des_deposants_de_presse_suffit(self):
        view = _view(
            doc_type="article", registrant_publisher_types=frozenset({"commercial", "media"})
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "media"

    def test_autre_type_de_deposant_sans_effet(self):
        view = _view(doc_type="article", registrant_publisher_types=frozenset({"commercial"}))
        assert effective_metadata(view).doc_type is None


class TestConferenceDeclaredRule:
    def test_chapitre_issu_d_un_congres_devient_article_de_congres(self):
        corrected = effective_metadata(
            _view(doc_type="book_chapter", declares_conference=True)
        ).doc_type
        assert corrected is not None
        assert corrected.value == "conference_paper"
        assert corrected.rule == MetadataCorrectionRule.CONFERENCE_DECLARED_TO_CONFERENCE_PAPER

    def test_livre_issu_d_un_congres_reste_livre(self):
        view = _view(doc_type="book", declares_conference=True)
        assert effective_metadata(view).doc_type is None

    def test_chapitre_sans_congres_reste_chapitre(self):
        assert effective_metadata(_view(doc_type="book_chapter")).doc_type is None

    def test_publication_sans_ce_fait_non_corrigee(self):
        assert effective_metadata(_publication(doc_type="book_chapter")).doc_type is None


class TestProceedingsVolumeRule:
    def test_article_d_un_volume_d_actes_devient_article_de_congres(self):
        corrected = effective_metadata(
            _view(doc_type="article", in_proceedings_volume=True)
        ).doc_type
        assert corrected is not None
        assert corrected.value == "conference_paper"
        assert corrected.rule == MetadataCorrectionRule.PROCEEDINGS_VOLUME_TO_CONFERENCE_PAPER

    def test_chapitre_d_un_volume_d_actes_devient_article_de_congres(self):
        view = _view(doc_type="book_chapter", in_proceedings_volume=True)
        assert effective_metadata(view).doc_type.value == "conference_paper"

    def test_livre_d_un_volume_d_actes_reste_livre(self):
        """Le volume d'actes lui-même, typé livre."""
        view = _view(doc_type="book", in_proceedings_volume=True)
        assert effective_metadata(view).doc_type is None

    def test_publication_sans_ce_fait_non_corrigee(self):
        assert effective_metadata(_publication(doc_type="article")).doc_type is None


class TestCrossrefVolumeRules:
    def test_enregistrement_source_sans_auteur_au_titre_de_congres_devient_volume(self):
        view = _view(
            source="crossref",
            author_count=0,
            doc_type="article",
            title="31st European Congress on Obesity (ECO 2024)",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "proceedings"
        assert (
            corrected.rule == MetadataCorrectionRule.CROSSREF_AUTHORLESS_VOLUME_TITLE_TO_PROCEEDINGS
        )

    def test_volume_a_un_auteur_declare_devient_volume(self):
        view = _view(
            source="crossref",
            author_count=1,
            doc_type="conference_paper",
            title="Proceedings of the 23rd International Conference of IFORS",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.rule == MetadataCorrectionRule.CROSSREF_VOLUME_TITLE_PREFIX_TO_PROCEEDINGS

    def test_recueil_de_resumes_listant_leurs_auteurs_devient_volume(self):
        """Cas réel : le recueil liste les 934 auteurs de ses résumés."""
        view = _view(
            source="crossref",
            author_count=934,
            doc_type="article",
            title="Abstracts from the Food Allergy and Anaphylaxis Meeting 2016",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.rule == MetadataCorrectionRule.CROSSREF_VOLUME_TITLE_PREFIX_TO_PROCEEDINGS

    def test_article_signe_au_titre_de_congres_reste_article(self):
        view = _view(
            source="crossref",
            author_count=1,
            doc_type="article",
            title="Presidential Address Presented at the 53rd AAGL Global Congress",
        )
        assert effective_metadata(view).doc_type is None

    def test_resume_isole_reste_article(self):
        view = _view(
            source="crossref",
            author_count=12,
            doc_type="article",
            title="Abstract 4007: Evolutionary history of transformation",
        )
        assert effective_metadata(view).doc_type is None

    def test_autre_source_non_concernee(self):
        view = _view(
            source="openalex",
            author_count=0,
            doc_type="article",
            title="EAPC2023 Abstract Book",
        )
        assert effective_metadata(view).doc_type is None

    def test_nombre_d_auteurs_inconnu_non_concerne(self):
        view = _view(source="crossref", doc_type="article", title="Poster Abstracts")
        assert effective_metadata(view).doc_type is None

    def test_publication_sans_source_ni_auteurs_non_corrigee(self):
        view = _publication(doc_type="article", title="Poster Abstracts")
        assert effective_metadata(view).doc_type is None


class TestSerialTypeProceedingsRule:
    def test_serial_type_proceedings_article_corrects(self):
        view = _view(doc_type="article", serial_type="proceedings")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "conference_paper"
        assert corrected.rule == MetadataCorrectionRule.SERIAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER

    def test_serial_type_proceedings_book_chapter_corrects(self):
        view = _view(doc_type="book_chapter", serial_type="proceedings")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "conference_paper"

    def test_serial_type_proceedings_book_is_spared(self):
        # `book` est hors des types corrigés : un volume entier d'actes peut rester `book`.
        view = _view(doc_type="book", serial_type="proceedings")
        assert effective_metadata(view).doc_type is None

    def test_serial_type_proceedings_already_conference_paper_is_noop(self):
        view = _view(doc_type="conference_paper", serial_type="proceedings")
        assert effective_metadata(view).doc_type is None

    def test_serial_type_non_proceedings_no_correction(self):
        view = _view(doc_type="article", serial_type="journal")
        assert effective_metadata(view).doc_type is None

    def test_serial_type_none_no_correction(self):
        # Sans type de revue (`serial_type=None`).
        view = _view(doc_type="article", serial_type=None)
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_serial_type_proceedings(self):
        # Combinaison improbable : la règle de l'URL theses.fr prime.
        view = _view(
            doc_type="article",
            urls=("https://theses.fr/s1",),
            serial_type="proceedings",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "thesis"


class TestSerialTypePreprintServerRule:
    def test_serial_type_preprint_server_article_corrects(self):
        view = _view(doc_type="article", serial_type="preprint_server")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "preprint"
        assert corrected.rule == MetadataCorrectionRule.SERIAL_TYPE_PREPRINT_SERVER_TO_PREPRINT

    def test_serial_type_preprint_server_other_corrects(self):
        view = _view(doc_type="other", serial_type="preprint_server")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "preprint"

    def test_serial_type_preprint_server_already_preprint_is_noop(self):
        view = _view(doc_type="preprint", serial_type="preprint_server")
        assert effective_metadata(view).doc_type is None

    def test_serial_type_preprint_server_dataset_is_spared(self):
        # `dataset` est hors des types corrigés : un jeu de données déposé sur arXiv ou Zenodo reste `dataset`.
        view = _view(doc_type="dataset", serial_type="preprint_server")
        assert effective_metadata(view).doc_type is None

    def test_serial_type_preprint_server_software_is_spared(self):
        view = _view(doc_type="software", serial_type="preprint_server")
        assert effective_metadata(view).doc_type is None

    def test_serial_type_non_preprint_server_no_correction(self):
        view = _view(doc_type="article", serial_type="journal")
        assert effective_metadata(view).doc_type is None

    def test_serial_type_none_no_correction(self):
        view = _view(doc_type="article", serial_type=None)
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_serial_type_preprint_server(self):
        view = _view(
            doc_type="article",
            urls=("https://theses.fr/s1",),
            serial_type="preprint_server",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "thesis"


class TestSerialTypeDataJournalRule:
    def test_article_of_data_journal_is_data_paper(self):
        view = _view(doc_type="article", serial_type="data_journal")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "data_paper"
        assert corrected.rule == MetadataCorrectionRule.SERIAL_TYPE_DATA_JOURNAL_TO_DATA_PAPER

    def test_publication_of_data_journal_is_data_paper(self):
        publication = _publication(doc_type="article", serial_type="data_journal")
        corrected = effective_metadata(publication).doc_type
        assert corrected is not None and corrected.value == "data_paper"

    @pytest.mark.parametrize("doc_type", ["erratum", "preprint", "other", "data_paper"])
    def test_other_doc_types_are_spared(self, doc_type):
        view = _view(doc_type=doc_type, serial_type="data_journal")
        assert effective_metadata(view).doc_type is None

    def test_erratum_title_wins_over_data_journal(self):
        # 10.1038/s41597-023-01980-z, Scientific Data : Crossref type l'erratum `journal-article`.
        view = _view(
            doc_type="article",
            serial_type="data_journal",
            title="Author Correction: MOSAiC-ACA and AFLUX - Arctic airborne campaigns",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "erratum"


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

    def test_interview_prefix_on_recorded_talk_corrects_to_media(self):
        view = _view(doc_type="recorded_talk", title="Interview Jean Pierre CHANET INRAE")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "media"

    def test_rule_on_media_is_noop(self):
        # `media` est hors des types corrigés.
        view = _view(doc_type="media", title="Interview RTL")
        assert effective_metadata(view).doc_type is None

    def test_rule_on_thesis_is_spared(self):
        # `thesis` est hors des types corrigés, malgré le titre suspect.
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

    def test_serial_type_media_wins_over_title_media_rule(self):
        # Les deux règles donnent `media` ; la règle du type de revue prime sur celle du titre.
        view = _view(doc_type="article", title="Interview pour France Inter", serial_type="media")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "media"
        assert corrected.rule == MetadataCorrectionRule.SERIAL_TYPE_MEDIA_TO_MEDIA


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
        # OpenAlex donne `preprint` à des errata du CERN.
        view = _view(doc_type="preprint", title="Erratum to: Search for CP violation")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "erratum"

    def test_data_paper_with_corrigendum_title_corrects(self):
        view = _view(doc_type="data_paper", title="Corrigendum to a clinical study")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "erratum"

    def test_rule_on_erratum_is_noop(self):
        # `erratum` est hors des types corrigés.
        view = _view(doc_type="erratum", title="Erratum to: …")
        assert effective_metadata(view).doc_type is None

    def test_rule_on_thesis_is_spared(self):
        # `thesis` est hors des types corrigés, malgré le titre suspect.
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

    def test_serial_type_media_wins_over_erratum_rule(self):
        # La règle media précède la règle erratum.
        view = _view(doc_type="article", title="Erratum to: X", serial_type="media")
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
        # Préfixe strict : « Retraction of consent in clinical trials » est un article sur le retrait du consentement.
        view = _view(doc_type="article", title="Retraction of consent in clinical trials")
        assert effective_metadata(view).doc_type is None

    def test_rule_on_retraction_is_noop(self):
        view = _view(doc_type="retraction", title="Retraction notice to …")
        assert effective_metadata(view).doc_type is None

    def test_rule_on_thesis_is_spared(self):
        # Hors des types corrigés (`article`, `other`).
        view = _view(doc_type="thesis", title="Retraction note: a thesis on …")
        assert effective_metadata(view).doc_type is None

    def test_unrelated_title_no_correction(self):
        view = _view(doc_type="article", title="A regular article about science")
        assert effective_metadata(view).doc_type is None

    def test_match_is_case_insensitive(self):
        for raw in (
            "RETRACTION NOTICE TO X",
            "retraction notice to x",
            "Retraction Notice: x",
        ):
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
        # `book` est hors des types corrigés : la saisie HAL met souvent l'ISBN d'un livre dans son titre.
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
        # `isbn` est reconnu seulement comme mot entier : « Isbnxyz » et « disbn » sont ignorés.
        view = _view(doc_type="article", title="A study of Disbnophilia in laboratory mice")
        assert effective_metadata(view).doc_type is None

    def test_isbn_naked_requires_full_pattern(self):
        # Un nombre commençant par 978 mais trop court n'est pas un ISBN.
        view = _view(doc_type="article", title="Page 9785 of the journal")
        assert effective_metadata(view).doc_type is None

    def test_serial_type_media_wins_over_isbn_rule(self):
        view = _view(
            doc_type="article",
            title="Recension d'un livre, ISBN 978-2-12345-678-9",
            serial_type="media",
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
        # `book` est hors des types corrigés : le titre d'un livre contient parfois sa propre référence bibliographique.
        view = _view(doc_type="book", title="Un vrai livre, Éditeur, 2020, 244 p")
        assert effective_metadata(view).doc_type is None

    def test_year_pages_on_book_review_is_noop(self):
        view = _view(doc_type="book_review", title="Recension d'un livre, 2020, 244 p")
        assert effective_metadata(view).doc_type is None

    def test_year_pages_requires_end_anchor(self):
        # Le motif « 2020, 244 p » au milieu du titre, suivi d'autre chose, est ignoré.
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
        # Les deux motifs sont présents ; la règle ISBN, appliquée d'abord, prime.
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


class TestTitleRecensionBookReviewRule:
    def test_recension_prefix_corrects(self):
        view = _view(
            doc_type="article", title="Recension de Stéphane Toussaint, La Liberté d'esprit"
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "book_review"
        assert corrected.rule == MetadataCorrectionRule.TITLE_RECENSION_TO_BOOK_REVIEW

    def test_recension_colon_form_corrects(self):
        view = _view(doc_type="other", title="Recension : Shakespeare and Authority")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "book_review"

    def test_recensions_plural_corrects(self):
        view = _view(doc_type="preprint", title="Recensions")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "book_review"

    def test_comptes_rendus_colon_corrects(self):
        view = _view(
            doc_type="article", title="Comptes rendus : « Philippe Antoine (dir.), La Littérature »"
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "book_review"

    def test_compte_rendu_singular_colon_corrects(self):
        view = _view(doc_type="preprint", title="Compte rendu : Plotin, Traité 30")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "book_review"

    def test_compte_rendu_de_mission_is_not_a_recension(self):
        # Le deux-points immédiat est requis : « Compte rendu de mission : … » est un rapport, type conservé.
        view = _view(doc_type="other", title="Compte rendu de mission : Ile de Santiago (Cap-Vert)")
        assert effective_metadata(view).doc_type is None

    def test_compte_rendu_de_soutenance_is_not_a_recension(self):
        view = _view(
            doc_type="other", title="Compte rendu de la soutenance d'HDR de Carole Christen"
        )
        assert effective_metadata(view).doc_type is None

    def test_book_is_spared(self):
        # `book` et `book_chapter` sont hors des types corrigés : la recension est un article, distinct de l'ouvrage recensé.
        view = _view(doc_type="book", title="Recension de cet ouvrage")
        assert effective_metadata(view).doc_type is None

    def test_unrelated_title_no_correction(self):
        view = _view(doc_type="article", title="Recent advances in soil science")
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
        # un item figshare (sans `.c.`) est ignoré
        assert effective_metadata(_view(doc_type="other", doi=self.ITEM)).doc_type is None

    def test_non_figshare_doi_not_matched(self):
        assert (
            effective_metadata(_view(doc_type="other", doi="10.1038/nature12345")).doc_type is None
        )

    def test_no_doi_not_matched(self):
        assert effective_metadata(_view(doc_type="other", doi=None)).doc_type is None

    def test_collection_doi_among_other_dois_corrects_to_dataset(self):
        view = _view(doc_type="other", dois=frozenset({"10.1038/nature12345", self.COLL}))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None and corrected.value == "dataset"

    def test_doc_type_outside_whitelist_noop(self):
        # collection de type `book` (improbable) : type conservé
        assert effective_metadata(_view(doc_type="book", doi=self.COLL)).doc_type is None

    def test_wins_over_title_supplement_rule(self):
        # même résultat (dataset) ; la règle DOI, appliquée d'abord, est créditée
        corrected = effective_metadata(
            _view(doc_type="other", doi=self.COLL, title="Additional file 1 of X")
        ).doc_type
        assert corrected is not None
        assert corrected.rule == MetadataCorrectionRule.DOI_FIGSHARE_COLLECTION_TO_DATASET


class TestPreprintRelationRule:
    def test_declared_preprint_retyped_even_without_doc_type(self):
        # Crossref donne un `doc_type` nul, mais déclare `is-preprint-of`.
        corrected = effective_metadata(_view(doc_type=None, self_declared_preprint=True)).doc_type
        assert corrected is not None
        assert corrected.value == "preprint"
        assert corrected.rule == MetadataCorrectionRule.PREPRINT_RELATION_TO_PREPRINT

    def test_declared_preprint_overrides_article(self):
        corrected = effective_metadata(
            _view(doc_type="article", self_declared_preprint=True)
        ).doc_type
        assert corrected is not None
        assert corrected.value == "preprint"

    def test_no_declaration_no_retyping(self):
        assert (
            effective_metadata(_view(doc_type="article", self_declared_preprint=False)).doc_type
            is None
        )


class TestEffectiveMetadataScope:
    def test_no_signals_no_correction(self):
        corrected = effective_metadata(_view())
        assert corrected.doc_type is None


class TestPublication:
    def test_regle_sur_la_revue_rejouee(self):
        corrected = effective_metadata(
            _publication(doc_type="preprint", serial_id=7, serial_type="media")
        ).doc_type
        assert corrected is not None
        assert corrected.rule == MetadataCorrectionRule.SERIAL_TYPE_MEDIA_TO_MEDIA

    def test_faits_propres_aux_enregistrements_sources_inconnus(self):
        view = _publication(doc_type="article")
        assert (view.urls, view.self_declared_preprint, view.source, view.author_count) == (
            None,
            None,
            None,
            None,
        )


class TestFaitInconnu:
    @pytest.mark.parametrize("expected", [True, False])
    def test_predicat_sur_un_fait_inconnu_faux(self, expected):
        assert not _check_predicate(
            _view(in_proceedings_volume=None), "in_proceedings_volume", expected
        )


class TestPresentationRules:
    @pytest.mark.parametrize("group_title", ["oral", "PICO"])
    def test_presentation_orale_vers_conference(self, group_title: str):
        corrected = effective_metadata(_view(doc_type="other", group_title=group_title)).doc_type
        assert corrected is not None
        assert corrected.value == "conference"
        assert corrected.rule is MetadataCorrectionRule.PRESENTATION_ORAL_TO_CONFERENCE

    def test_session_d_affichage_vers_poster(self):
        corrected = effective_metadata(_view(doc_type="other", group_title="display")).doc_type
        assert corrected is not None
        assert corrected.value == "poster"

    def test_categorie_de_preprint_ignoree(self):
        assert effective_metadata(_view(doc_type="preprint", group_title="oral")).doc_type is None
