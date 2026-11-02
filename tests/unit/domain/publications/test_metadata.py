"""Règles sur les métadonnées d'une publication : rang des statuts open access, niveaux d'accès, titre (normalisation, longueur), métadonnées minimales."""

from domain.publications.metadata import (
    TITLE_NORMALIZED_MAX_LENGTH,
    has_minimal_publication_metadata,
    is_overlong_title,
    normalized_title,
)
from domain.publications.oa_status import ACCESS_LEVELS, OA_RANK


class TestAccessLevels:
    """Les niveaux d'accès répartissent les statuts open access : chaque statut appartient à un seul niveau."""

    def test_cover_every_status(self):
        classes = {s for statuses in ACCESS_LEVELS.values() for s in statuses}
        assert classes == set(OA_RANK)

    def test_do_not_overlap(self):
        total = sum(len(statuses) for statuses in ACCESS_LEVELS.values())
        assert total == len(OA_RANK)

    def test_open_is_more_open_than_embargo_than_closed(self):
        """L'ordre des niveaux suit celui des statuts qu'ils recouvrent."""
        rank = {level: {OA_RANK[s] for s in statuses} for level, statuses in ACCESS_LEVELS.items()}
        assert min(rank["open"]) > max(rank["embargo"]) > max(rank["closed"])


class TestNormalizedTitle:
    def test_html_decode_then_normalize(self):
        # `&amp;amp;` est décodé en `&`, puis retiré par la normalisation ; « œ » devient « oe ».
        assert normalized_title("Cœur &amp;amp; âme") == "coeur ame"

    def test_collapses_whitespace_and_lowercases(self):
        assert normalized_title("  ŒUVRE   complète ") == "oeuvre complete"

    def test_none_and_empty_give_empty_string(self):
        assert normalized_title(None) == ""
        assert normalized_title("") == ""

    def test_idempotent(self):
        once = normalized_title("Les Effets thermomécaniques")
        assert normalized_title(once) == once


class TestHasMinimalPublicationMetadata:
    def test_title_and_year_present(self):
        assert has_minimal_publication_metadata("Some title", 2024) is True

    def test_missing_title(self):
        assert has_minimal_publication_metadata(None, 2024) is False
        assert has_minimal_publication_metadata("", 2024) is False

    def test_missing_year(self):
        assert has_minimal_publication_metadata("Some title", None) is False

    def test_year_zero_treated_as_missing(self):
        """L'année 0 vaut une année absente."""
        assert has_minimal_publication_metadata("Some title", 0) is False

    def test_both_missing(self):
        assert has_minimal_publication_metadata(None, None) is False


class TestIsOverlongTitle:
    def test_seuil_inclus(self):
        assert is_overlong_title("a" * TITLE_NORMALIZED_MAX_LENGTH) is False
        assert is_overlong_title("a" * (TITLE_NORMALIZED_MAX_LENGTH + 1)) is True

    def test_longueur_du_titre_normalise(self):
        """Balises et ponctuation retirées, le titre tient sous le seuil."""
        title = "<b>" + "a" * TITLE_NORMALIZED_MAX_LENGTH + "</b>" + "!" * 50
        assert is_overlong_title(title) is False

    def test_titre_absent(self):
        assert is_overlong_title(None) is False
        assert is_overlong_title("") is False


class TestOaRank:
    def test_rank_order_is_strict(self):
        assert OA_RANK["diamond"] > OA_RANK["gold"] > OA_RANK["hybrid"]
        assert OA_RANK["hybrid"] > OA_RANK["green"] > OA_RANK["bronze"]
        assert OA_RANK["bronze"] > OA_RANK["embargoed"] > OA_RANK["closed"] > OA_RANK["unknown"]
