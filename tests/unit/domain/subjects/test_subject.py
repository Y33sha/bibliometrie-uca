"""Tests de `domain.subjects.subject` : niveau et ancêtres d'un sujet, vedettes RAMEAU, disciplines de thèse."""

from domain.subjects.subject import (
    Subject,
    SubjectVocabulary,
    rameau_subject,
    theses_discipline_subject,
)


class TestSubject:
    def test_level_and_lineage(self):
        domain = Subject(SubjectVocabulary.OPENALEX, "domains/2", "Social Sciences")
        field = Subject(SubjectVocabulary.OPENALEX, "fields/20", "Economics", domain)
        assert (domain.level, field.level) == (1, 2)
        assert field.lineage() == [domain, field]


class TestRameauSubject:
    def test_ppn_upper_case(self):
        subject = rameau_subject("02750607x", " Béton armé -- Fissuration ")
        assert subject == Subject(
            SubjectVocabulary.RAMEAU, "02750607X", "Béton armé -- Fissuration"
        )

    def test_invalid_ppn_or_empty_label(self):
        assert rameau_subject("0275", "Béton armé") is None
        assert rameau_subject("027221083", " ") is None


class TestThesesDisciplineSubject:
    def test_code_is_the_normalized_label(self):
        first = theses_discipline_subject("Sciences Economiques")
        second = theses_discipline_subject("Sciences économiques")
        assert first is not None and second is not None
        assert first.code == second.code == "sciences economiques"

    def test_label_kept_as_given(self):
        subject = theses_discipline_subject(" Biologie santé ")
        assert subject is not None
        assert (subject.code, subject.label) == ("biologie sante", "Biologie santé")

    def test_empty_label(self):
        assert theses_discipline_subject("  ") is None
