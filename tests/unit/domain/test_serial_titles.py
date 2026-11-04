"""Tests de la lecture des titres de conteneurs (`domain.serials.titles`)."""

import pytest

from domain.serials.titles import (
    names_a_dated_event,
    names_ebook_platform,
    names_proceedings,
)


# Cas réels de la table serials.
def test_plateforme_d_ebooks():
    assert names_ebook_platform("ENS Éditions eBooks")
    assert names_ebook_platform("éditions Quae eBooks")
    assert not names_ebook_platform("Reti Medievali E-Book")
    assert not names_ebook_platform("eBooks")


def test_titre_d_actes():
    assert names_proceedings("Proceedings of the Samahang Pisika ng Pilipinas")
    assert names_proceedings(
        "Proceedings of the 36th Annual Conference of the European Association of Cognitive Ergonomics"
    )


@pytest.mark.parametrize(
    "title",
    [
        "Proceedings of the Wesley Historical Society",
        "Proceedings of the National Academy of Sciences",
        "Proceedings of the Institution of Civil Engineers - Structures and Buildings",
        "Physical Review Letters",
    ],
)
def test_revue_d_une_societe_savante(title):
    assert not names_proceedings(title)


def test_procedure_judiciaire():
    """Cas réel de la table monographs : un ouvrage de droit."""
    assert not names_proceedings("Third Parties in Criminal Proceedings")


# Cas réels de la table serials.
@pytest.mark.parametrize(
    "title",
    [
        "NuFACT 2022",
        "2024 IEEE SENSORS",
        "Goldschmidt2023 abstracts",
        "Deutscher Kongress für Orthopädie und Unfallchirurgie (DKOU 2024)",
        "ICC 2019 - 2019 IEEE International Conference on Communications (ICC)",
        "2025 IEEE 101st Vehicular Technology Conference (VTC2025-Spring)",
    ],
)
def test_edition_datee(title):
    assert names_a_dated_event(title)


@pytest.mark.parametrize(
    "title",
    [
        "A Companion to Contemporary British and Irish Poetry, 1960–2015",
        "Christian-Muslim Relations 1500 - 1900",
        "22 Seiten (2023).",
        "1-26 (2021).",
        "Journal of high energy physics 2018(7)",
        "Journal of Modern Philosophy Volume 3 Issue 0 2021",
        "Physical Review Letters",
    ],
)
def test_pas_d_edition_datee(title):
    assert not names_a_dated_event(title)
