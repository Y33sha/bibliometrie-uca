"""Tests de `domain.sources.hal.hal_domain_subject`.

Les entrées sont des valeurs réelles du champ `fr_domainAllCodeLabel_fs` de l'API HAL.
"""

from domain.sources.hal import hal_domain_subject
from domain.subjects.subject import SubjectVocabulary


def _lineage(entry: str) -> list[tuple[str, str]]:
    """Renvoie le code et le libellé de chaque niveau du domaine lu, de la racine au domaine."""
    subject = hal_domain_subject(entry)
    return [] if subject is None else [(s.code, s.label) for s in subject.lineage()]


class TestHalDomainSubject:
    def test_single_level(self):
        subject = hal_domain_subject("sdv_FacetSep_Sciences du Vivant [q-bio]")
        assert subject is not None
        assert (subject.vocabulary, subject.code, subject.label, subject.level) == (
            SubjectVocabulary.HAL_DOMAIN,
            "sdv",
            "Sciences du Vivant",
            1,
        )

    def test_each_level_coded_by_a_prefix(self):
        entry = (
            "sdv.bbm.bm_FacetSep_Sciences du Vivant [q-bio]"
            "/Biochimie, Biologie Moléculaire/Biologie moléculaire"
        )
        assert _lineage(entry) == [
            ("sdv", "Sciences du Vivant"),
            ("sdv.bbm", "Biochimie, Biologie Moléculaire"),
            ("sdv.bbm.bm", "Biologie moléculaire"),
        ]

    def test_annotations_stripped_at_every_level(self):
        entry = "sdv.bbm.bc_FacetSep_Sciences du Vivant [q-bio]/Biochimie, Biologie Moléculaire/Biochimie [q-bio.BM]"
        assert [label for _, label in _lineage(entry)] == [
            "Sciences du Vivant",
            "Biochimie, Biologie Moléculaire",
            "Biochimie",
        ]

    def test_hyphen_in_code_segment(self):
        assert _lineage("info.info-bi_FacetSep_Informatique [cs]/Bio-informatique") == [
            ("info", "Informatique"),
            ("info.info-bi", "Bio-informatique"),
        ]


class TestSlashInsideLabel:
    """La profondeur du code borne le découpage : un `/` du libellé de feuille reste dedans."""

    def test_conjunction_slash(self):
        assert _lineage("chim.theo_FacetSep_Chimie/Chimie théorique et/ou physique") == [
            ("chim", "Chimie"),
            ("chim.theo", "Chimie théorique et/ou physique"),
        ]

    def test_spaced_slash(self):
        entry = "spi.opti_FacetSep_Sciences de l'ingénieur [physics]/Optique / photonique"
        assert [label for _, label in _lineage(entry)] == [
            "Sciences de l'ingénieur",
            "Optique / photonique",
        ]

    def test_slash_joining_two_levels_of_a_leaf(self):
        entry = (
            "spi.nano_FacetSep_Sciences de l'ingénieur [physics]"
            "/Micro et nanotechnologies/Microélectronique"
        )
        assert [label for _, label in _lineage(entry)] == [
            "Sciences de l'ingénieur",
            "Micro et nanotechnologies/Microélectronique",
        ]


class TestGenericLabels:
    """Les feuilles génériques (« Autre », « Autres ») sont écartées ; leur parent devient le domaine lu."""

    def test_autre(self):
        assert _lineage("chim.othe_FacetSep_Chimie/Autre") == [("chim", "Chimie")]

    def test_autre_with_annotation(self):
        assert _lineage("info.info-oh_FacetSep_Informatique [cs]/Autre [cs.OH]") == [
            ("info", "Informatique")
        ]

    def test_autres_plural(self):
        assert _lineage("stat.ot_FacetSep_Statistiques [stat]/Autres [stat.ML]") == [
            ("stat", "Statistiques")
        ]


class TestMalformedEntries:
    def test_no_separator(self):
        assert hal_domain_subject("sdv.bbm.bm") is None

    def test_empty(self):
        assert hal_domain_subject("") is None

    def test_code_holding_a_label_path(self):
        """Quelques entrées du référentiel ont pour code un chemin de libellés."""
        entry = "Informatique [cs]/Biotechnologie_FacetSep_domain_Informatique [cs]/Biotechnologie"
        assert hal_domain_subject(entry) is None

    def test_empty_path(self):
        assert hal_domain_subject("sdv_FacetSep_") is None
