"""Tests de `domain.sources.hal.hal_domain_labels`.

Les entrées sont des valeurs réelles du champ `fr_domainAllCodeLabel_fs` de l'API HAL.
"""

from domain.sources.hal import hal_domain_labels


class TestHalDomainLabels:
    def test_single_level(self):
        assert hal_domain_labels("sdv_FacetSep_Sciences du Vivant [q-bio]") == [
            "Sciences du Vivant"
        ]

    def test_all_levels_of_the_path(self):
        entry = (
            "sdv.bbm.bm_FacetSep_Sciences du Vivant [q-bio]"
            "/Biochimie, Biologie Moléculaire/Biologie moléculaire"
        )
        assert hal_domain_labels(entry) == [
            "Sciences du Vivant",
            "Biochimie, Biologie Moléculaire",
            "Biologie moléculaire",
        ]

    def test_annotations_stripped_at_every_level(self):
        entry = "sdv.bbm.bc_FacetSep_Sciences du Vivant [q-bio]/Biochimie, Biologie Moléculaire/Biochimie [q-bio.BM]"
        assert hal_domain_labels(entry) == [
            "Sciences du Vivant",
            "Biochimie, Biologie Moléculaire",
            "Biochimie",
        ]

    def test_hyphen_in_code_segment(self):
        assert hal_domain_labels("info.info-bi_FacetSep_Informatique [cs]/Bio-informatique") == [
            "Informatique",
            "Bio-informatique",
        ]


class TestSlashInsideLabel:
    """La profondeur du code borne le découpage : un `/` du libellé de feuille reste dedans."""

    def test_conjunction_slash(self):
        assert hal_domain_labels("chim.theo_FacetSep_Chimie/Chimie théorique et/ou physique") == [
            "Chimie",
            "Chimie théorique et/ou physique",
        ]

    def test_spaced_slash(self):
        entry = "spi.opti_FacetSep_Sciences de l'ingénieur [physics]/Optique / photonique"
        assert hal_domain_labels(entry) == [
            "Sciences de l'ingénieur",
            "Optique / photonique",
        ]

    def test_slash_joining_two_levels_of_a_leaf(self):
        entry = (
            "spi.nano_FacetSep_Sciences de l'ingénieur [physics]"
            "/Micro et nanotechnologies/Microélectronique"
        )
        assert hal_domain_labels(entry) == [
            "Sciences de l'ingénieur",
            "Micro et nanotechnologies/Microélectronique",
        ]


class TestGenericLabels:
    """Les feuilles fourre-tout sont écartées ; leur parent porte le signal."""

    def test_autre(self):
        assert hal_domain_labels("chim.othe_FacetSep_Chimie/Autre") == ["Chimie"]

    def test_autre_with_annotation(self):
        assert hal_domain_labels("info.info-oh_FacetSep_Informatique [cs]/Autre [cs.OH]") == [
            "Informatique"
        ]

    def test_autres_plural(self):
        assert hal_domain_labels("stat.ot_FacetSep_Statistiques [stat]/Autres [stat.ML]") == [
            "Statistiques"
        ]


class TestMalformedEntries:
    def test_no_separator(self):
        assert hal_domain_labels("sdv.bbm.bm") == []

    def test_empty(self):
        assert hal_domain_labels("") == []

    def test_code_holding_a_label_path(self):
        """Quelques entrées du référentiel portent un chemin de libellés en guise de code."""
        entry = "Informatique [cs]/Biotechnologie_FacetSep_domain_Informatique [cs]/Biotechnologie"
        assert hal_domain_labels(entry) == []

    def test_empty_path(self):
        assert hal_domain_labels("sdv_FacetSep_") == []
