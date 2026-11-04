"""Source OpenAlex d'une revue : type de revue, source retenue, revue qui reçoit un identifiant réclamé par plusieurs revues."""

import pytest

from domain.serials.openalex_sources import Claimant, holder, main_source, serial_type_of_source
from domain.serials.serial import SerialType
from domain.sources.openalex import OpenAlexSource


def _source(identifier: str, works_count: int) -> OpenAlexSource:
    return OpenAlexSource(identifier, (), "journal", (), works_count)


@pytest.mark.parametrize(
    ("source_type", "expected"),
    [
        ("journal", SerialType.JOURNAL),
        ("conference", SerialType.PROCEEDINGS),
        ("Book Series", SerialType.BOOK_SERIES),
        ("repository", None),
        (None, None),
    ],
)
def test_type_de_revue_d_un_type_de_source(source_type, expected):
    assert serial_type_of_source(source_type) == expected


def test_la_source_retenue_a_le_plus_de_works():
    assert main_source([_source("S2", 10), _source("S1", 500)]) == _source("S1", 500)


def test_a_egalite_de_works_le_plus_petit_identifiant():
    assert main_source([_source("S2", 10), _source("S1", 10)]) == _source("S1", 10)


def test_sans_source():
    assert main_source([]) is None


def test_l_identifiant_va_a_la_revue_qui_a_le_plus_de_publications():
    """Cas réel : la source de *JAMA* réunit l'ancien titre, sans publication, et le titre courant."""
    assert holder([Claimant(753, 0), Claimant(105862, 33)]) == 105862


def test_a_egalite_de_publications_le_plus_petit_identifiant():
    assert holder([Claimant(9, 4), Claimant(3, 4)]) == 3
