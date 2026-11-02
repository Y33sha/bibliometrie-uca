"""Retrait de l'intitulé de tête d'un résumé par `domain.normalize.clean_abstract`, sur des débuts de résumés réels."""

import pytest

from domain.normalize import clean_abstract


@pytest.mark.parametrize(
    ("abstract", "expected"),
    [
        ("Abstract The aim of this study", "The aim of this study"),
        ("Abstract\n\n                    Background: patients", "Background: patients"),
        ("Abstract. We establish", "We establish"),
        ("Abstract : Afin de limiter", "Afin de limiter"),
        ("Résumé : Cette thèse", "Cette thèse"),
        ("RESUME Gene expression is governed", "Gene expression is governed"),
        ("SUMMARY The results", "The results"),
        ("Abstract $$ D^+ $$ decays", "$$ D^+ $$ decays"),
        ("<title>Abstract</title> <p>Background</p>", "<p>Background</p>"),
        ("<jats:title>SUMMARY</jats:title><jats:p>Text</jats:p>", "<jats:p>Text</jats:p>"),
        ("Abstract Summary\nViral genes", "Viral genes"),
    ],
)
def test_retire_l_intitule(abstract: str, expected: str) -> None:
    assert clean_abstract(abstract) == expected


@pytest.mark.parametrize(
    "abstract",
    [
        "Summary statistics are reported",
        "Résumé de la thèse en français : Le clouage",
        "Abstract art is a movement",
        "The abstract of this paper",
    ],
)
def test_garde_une_phrase_qui_commence_par_le_mot(abstract: str) -> None:
    assert clean_abstract(abstract) == abstract


def test_resume_vide() -> None:
    assert clean_abstract(None) is None
    assert clean_abstract("") == ""
