"""Tests de la reconnaissance des structures par leurs formes de nom."""

from domain.structures.name_forms import is_short_form
from domain.structures.structure import StructureType
from pipeline.transformation.structures.name_recognition import (
    MatchableNameForm,
    StructureNameMatcher,
)


def _form(
    structure_id,
    form_text,
    form_normalized=None,
    requires_context_of=None,
    form_id=None,
    is_word_boundary=False,
    is_excluding=False,
    structure_type=StructureType.LABO,
):
    """Renvoie une MatchableNameForm de test. Comme en base, une forme courte a toujours `is_word_boundary`."""
    normalized = form_normalized or form_text.lower()
    return MatchableNameForm(
        id=form_id or structure_id * 100,
        structure_id=structure_id,
        form_text=normalized,
        is_word_boundary=is_word_boundary or is_short_form(normalized),
        is_excluding=is_excluding,
        requires_context_of=requires_context_of,
        structure_type=structure_type,
    )


def _matches(form: MatchableNameForm, text: str) -> bool:
    """Renvoie vrai si `form`, seule, est reconnue dans `text`."""
    return bool(StructureNameMatcher([form]).resolve(text))


# Reconnaissance d'une forme : sous-chaîne ou mot entier


class TestFormMatching:
    def test_long_substring(self):
        """Une forme de plus de six caractères est cherchée comme sous-chaîne."""
        assert _matches(_form(1, "clermont", "clermont"), "univ clermont auvergne") is True

    def test_long_not_found(self):
        assert _matches(_form(1, "grenoble", "grenoble"), "univ clermont auvergne") is False

    def test_short_word_boundary(self):
        """Une forme de six caractères au plus est cherchée comme mot entier."""
        form = _form(1, "limos", "limos")
        assert _matches(form, "limos clermont") is True
        assert _matches(form, "polimos lab") is False

    def test_short_at_end(self):
        assert _matches(_form(1, "limos", "limos"), "lab limos") is True

    def test_short_alone(self):
        assert _matches(_form(1, "limos", "limos"), "limos") is True

    def test_word_boundary_flag(self):
        """Une forme à `is_word_boundary` est cherchée comme mot entier, quelle que soit sa longueur."""
        form = _form(1, "clermont", is_word_boundary=True)
        assert _matches(form, "clermont ferrand") is True
        assert _matches(form, "preclermont") is False

    def test_empty_form(self):
        assert _matches(_form(1, "", form_normalized=""), "some text") is False


# StructureNameMatcher.resolve


class TestResolve:
    def test_simple_match(self):
        forms = [_form(1, "limos", "limos", form_id=10)]
        result = StructureNameMatcher(forms).resolve("lab limos clermont")
        assert result == [(1, 10)]

    def test_no_match(self):
        forms = [_form(1, "grenoble", "grenoble")]
        result = StructureNameMatcher(forms).resolve("lab limos clermont")
        assert result == []

    def test_multiple_structures(self):
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(2, "clermont", "clermont", form_id=20),
        ]
        result = StructureNameMatcher(forms).resolve("limos clermont ferrand")
        assert len(result) == 2
        structure_ids = {sid for sid, _ in result}
        assert structure_ids == {1, 2}

    def test_deduplicate_same_structure(self):
        """Deux formes reconnues de la même structure donnent une seule occurrence."""
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(1, "laboratoire limos", "laboratoire limos", form_id=11),
        ]
        result = StructureNameMatcher(forms).resolve("laboratoire limos clermont")
        assert len(result) == 1
        assert result[0][0] == 1

    def test_context_satisfied(self):
        """Forme à `requires_context_of` : le contexte est présent."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[2]),
            _form(2, "clermont", "clermont", form_id=20),
        ]
        result = StructureNameMatcher(forms).resolve("limos clermont")
        structure_ids = {sid for sid, _ in result}
        assert 1 in structure_ids

    def test_context_not_satisfied(self):
        """Forme à `requires_context_of` : le contexte est absent."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[2]),
            _form(2, "grenoble", "grenoble", form_id=20),
        ]
        result = StructureNameMatcher(forms).resolve("limos clermont")
        structure_ids = {sid for sid, _ in result}
        assert 1 not in structure_ids

    def test_u999_paris_no_match_lrl(self):
        """« u999 », forme de LRL qui exige le contexte de l'UCA, reste sans effet dans une adresse parisienne sans l'UCA."""
        forms = [
            _form(
                217, "u999", "u999", form_id=1566, is_word_boundary=True, requires_context_of=[169]
            ),  # LRL, nécessite UCA
            _form(169, "universite clermont auvergne", form_id=100),  # UCA
        ]
        text = (
            "pole des cardiopathies congenitales du nouveau ne a l adulte "
            "centre constitutif cardiopathies congenitales complexes m3c "
            "groupe hospitalier paris saint joseph hopital marie lannelongue "
            "inserm u999 universite paris saclay"
        )
        result = StructureNameMatcher(forms).resolve(text)
        matched_ids = {sid for sid, _ in result}
        assert 217 not in matched_ids  # LRL non reconnu

    def test_u999_clermont_matches_lrl(self):
        """« u999 » dans une adresse clermontoise qui cite l'UCA : LRL est reconnu."""
        forms = [
            _form(
                217, "u999", "u999", form_id=1566, is_word_boundary=True, requires_context_of=[169]
            ),
            _form(169, "universite clermont auvergne", form_id=100),
        ]
        text = "inserm u999 universite clermont auvergne"
        result = StructureNameMatcher(forms).resolve(text)
        matched_ids = {sid for sid, _ in result}
        assert 217 in matched_ids  # LRL reconnu
        assert 169 in matched_ids  # UCA aussi

    def test_site_serves_as_context_without_being_returned(self):
        """Un site satisfait le `requires_context_of` des formes qui l'invoquent, sans produire de rattachement."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[170]),
            _form(170, "aubiere", form_id=20, structure_type=StructureType.SITE),
        ]
        result = StructureNameMatcher(forms).resolve("limos aubiere")
        structure_ids = {sid for sid, _ in result}
        assert 1 in structure_ids
        assert 170 not in structure_ids

    def test_site_alone_yields_nothing(self):
        """Un texte où seule une forme de site est reconnue produit un résultat vide."""
        forms = [_form(170, "aubiere", form_id=20, structure_type=StructureType.SITE)]
        assert StructureNameMatcher(forms).resolve("2 rue des cezeaux aubiere") == []

    def test_context_must_itself_be_recognized(self):
        """Une forme de la structure de contexte, présente mais invalide faute de son propre contexte, ne satisfait pas le contexte.

        « territoires » (UMR Territoires) exige l'UCA ; « faculte » (UCA) exige le site de Clermont. Une faculté de Lyon ne fait pas reconnaître l'UMR Territoires.
        """
        forms = [
            _form(196, "territoires", form_id=1405, requires_context_of=[169]),
            _form(169, "faculte", form_id=1735, is_word_boundary=True, requires_context_of=[170]),
            _form(170, "clermont", form_id=20, structure_type=StructureType.SITE),
        ]
        matcher = StructureNameMatcher(forms)
        text = "dct droits contrats territoires universite lumiere lyon 2 faculte de droit"
        assert matcher.resolve(text) == []

    def test_chained_context(self):
        """Contexte en chaîne : le site reconnaît l'UCA, qui reconnaît l'UMR Territoires."""
        forms = [
            _form(196, "territoires", form_id=1405, requires_context_of=[169]),
            _form(169, "faculte", form_id=1735, is_word_boundary=True, requires_context_of=[170]),
            _form(170, "clermont", form_id=20, structure_type=StructureType.SITE),
        ]
        result = StructureNameMatcher(forms).resolve("umr territoires faculte clermont ferrand")
        assert {sid for sid, _ in result} == {169, 196}

    def test_excluded_structure_is_not_context(self):
        """Une structure écartée par une forme d'exclusion ne sert pas de contexte."""
        forms = [
            _form(1, "limos", form_id=10, requires_context_of=[99]),
            _form(99, "uca", form_id=99),
            _form(99, "uca cote d azur", form_id=98, is_excluding=True),
        ]
        assert StructureNameMatcher(forms).resolve("limos uca cote d azur") == []

    def test_context_tutelles(self):
        """`requires_context_of` désigne les structures de contexte par leur identifiant."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[99]),
            _form(99, "uca", "uca", form_id=99),
        ]
        result = StructureNameMatcher(forms).resolve("limos uca")
        structure_ids = {sid for sid, _ in result}
        assert 1 in structure_ids

    def test_excluding_form_blocks_structure(self):
        """Une forme d'exclusion reconnue retire sa structure des résultats, même si une autre forme de cette structure est reconnue."""
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(1, "limos paris", "limos paris", form_id=11, is_excluding=True),
        ]
        result = StructureNameMatcher(forms).resolve("lab limos paris")
        assert result == []

    def test_excluding_form_skipped_when_not_matching(self):
        """Une forme d'exclusion non reconnue, sur une autre structure, laisse le résultat intact."""
        forms = [
            _form(2, "grenoble", "grenoble", form_id=20, is_excluding=True),
            _form(1, "limos", "limos", form_id=10),
        ]
        result = StructureNameMatcher(forms).resolve("lab limos clermont")
        assert result == [(1, 10)]
