"""Tests du rapprochement des monographies de même titre (`domain.monographs.matching`)."""

from domain.monographs.matching import (
    MonographCandidate,
    MonographChoice,
    choose_monograph,
    duplicate_monographs,
)


def _m(mid: int, *, isbn: str | None = None, publisher: int | None = None) -> MonographCandidate:
    return MonographCandidate(mid, isbn, None, publisher)


class TestChooseMonograph:
    def test_sans_candidat_creation(self):
        assert choose_monograph([], publisher_id=1, has_isbn=False) == MonographChoice(None, True)

    def test_meme_editeur(self):
        assert (
            choose_monograph([_m(1, publisher=7)], publisher_id=7, has_isbn=False).monograph_id == 1
        )

    def test_editeurs_differents_creation(self):
        choice = choose_monograph([_m(1, publisher=7)], publisher_id=8, has_isbn=False)
        assert choice == MonographChoice(None, True)

    def test_editeur_absent_du_document(self):
        """Cas réel : HAL ne donne pas l'éditeur d'un livre de Classiques Garnier."""
        choice = choose_monograph([_m(1, publisher=14001)], publisher_id=None, has_isbn=False)
        assert choice.monograph_id == 1

    def test_editeur_absent_de_la_monographie(self):
        assert choose_monograph([_m(1)], publisher_id=7, has_isbn=False).monograph_id == 1

    def test_meme_editeur_avant_monographie_sans_editeur(self):
        candidates = [_m(1), _m(2, publisher=7)]
        assert choose_monograph(candidates, publisher_id=7, has_isbn=False).monograph_id == 2

    def test_document_a_isbn_rejoint_une_monographie_sans_isbn(self):
        candidates = [_m(1, isbn="9783030580803"), _m(2)]
        assert choose_monograph(candidates, publisher_id=None, has_isbn=True).monograph_id == 2

    def test_document_a_isbn_face_a_des_volumes_creation(self):
        candidates = [_m(1, isbn="9783030580803")]
        assert choose_monograph(candidates, publisher_id=None, has_isbn=True).create

    def test_entre_plusieurs_volumes_abstention(self):
        candidates = [_m(1, isbn="9783030580803"), _m(2, isbn="9782410013221")]
        assert choose_monograph(candidates, publisher_id=None, has_isbn=False) == MonographChoice(
            None, False
        )


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
