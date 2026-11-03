"""Tests de la fusion des monographies de même titre (`domain.monographs.matching`)."""

from domain.monographs.matching import MonographCandidate, duplicate_monographs


def _m(mid: int, *, isbn: str | None = None, publisher: int | None = None) -> MonographCandidate:
    return MonographCandidate(mid, isbn, None, publisher)


class TestDuplicateMonographs:
    def test_monographie_sans_editeur_fusionne_dans_celle_qui_en_a_un(self):
        """Cas réel : « Pascal intempestif », une fois sans éditeur (HAL), une fois chez Classiques Garnier avec ISBN."""
        assert duplicate_monographs([_m(1), _m(2, isbn="9782406191094", publisher=14001)]) == [
            (2, 1)
        ]

    def test_editeurs_differents_restent(self):
        assert duplicate_monographs([_m(1, publisher=7), _m(2, publisher=8)]) == []

    def test_volumes_a_isbn_differents_restent(self):
        volumes = [_m(1, isbn="9783030580803"), _m(2, isbn="9782410013221")]
        assert duplicate_monographs(volumes) == []

    def test_monographie_compatible_avec_plusieurs_reste(self):
        """Sans éditeur ni ISBN, elle double l'une ou l'autre de deux monographies d'éditeurs différents."""
        group = [_m(1), _m(2, publisher=7), _m(3, publisher=8)]
        assert duplicate_monographs(group) == []
