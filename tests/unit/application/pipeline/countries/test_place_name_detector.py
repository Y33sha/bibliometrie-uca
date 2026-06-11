"""Tests unitaires de `PlaceNameDetector` (détection d'institutions, Aho-Corasick)."""

from application.pipeline.countries.place_name_detector import PlaceNameDetector


class TestPlaceNameDetector:
    def test_single_match(self):
        det = PlaceNameDetector({"universite lumiere lyon": "fr"})
        assert det.detect("lab x universite lumiere lyon cedex") == {"fr"}

    def test_match_anywhere_not_just_end(self):
        det = PlaceNameDetector({"university of warsaw": "pl"})
        assert det.detect("university of warsaw faculty of physics") == {"pl"}

    def test_word_boundary_no_partial_match(self):
        # La forme ne matche pas collée dans un mot plus long.
        det = PlaceNameDetector({"keio university": "jp"})
        assert det.detect("akeio university") == set()  # 'keio' collé après 'a'
        assert det.detect("keio universityx") == set()  # 'university' suivi de 'x'

    def test_multiple_countries_returns_all(self):
        det = PlaceNameDetector({"universite de liege": "be", "universite paris": "fr"})
        assert det.detect("universite de liege et universite paris") == {"be", "fr"}

    def test_no_match(self):
        det = PlaceNameDetector({"university of warsaw": "pl"})
        assert det.detect("institut de chimie cnrs") == set()

    def test_empty_forms(self):
        assert PlaceNameDetector({}).detect("university of warsaw") == set()

    def test_empty_text(self):
        assert PlaceNameDetector({"university of warsaw": "pl"}).detect("") == set()

    def test_iso_preserved(self):
        det = PlaceNameDetector({"keio university": "jp"})
        assert det.detect("keio university tokyo") == {"jp"}
