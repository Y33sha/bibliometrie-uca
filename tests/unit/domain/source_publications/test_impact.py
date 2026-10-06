"""Tests de `domain.source_publications.impact`."""

from domain.source_publications.impact import Impact


class TestImpactToJson:
    def test_aucun_indicateur(self):
        assert Impact().to_json() is None

    def test_seuls_les_indicateurs_renseignes(self):
        assert Impact(cited_by_count=12, fwci=1.5).to_json() == {"cited_by_count": 12, "fwci": 1.5}

    def test_zero_et_faux_conserves(self):
        """Zéro citation et « hors top 10 % » sont des valeurs connues."""
        assert Impact(cited_by_count=0, top_10_percent=False).to_json() == {
            "cited_by_count": 0,
            "top_10_percent": False,
        }
