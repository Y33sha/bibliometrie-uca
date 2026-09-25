"""Tests unitaires de domain.sources.crossref (helpers purs)."""

from domain.dates import today
from domain.sources.crossref import (
    crossref_raw_doc_type,
    extract_crossref_conference,
    extract_crossref_meta,
    extract_crossref_pub_year,
    parse_crossref_issns,
    strip_jats_tags,
)


def _date_field(year: int) -> dict:
    return {"date-parts": [[year, 6, 15]]}


_NEXT_YEAR = today().year + 1


class TestExtractCrossrefPubYearOrder:
    def test_prefers_published_over_issued(self):
        msg = {
            "published": _date_field(2024),
            "issued": _date_field(2025),
        }
        assert extract_crossref_pub_year(msg, max_year=_NEXT_YEAR) == 2024

    def test_falls_back_to_issued_when_published_missing(self):
        msg = {"issued": _date_field(2024)}
        assert extract_crossref_pub_year(msg, max_year=_NEXT_YEAR) == 2024

    def test_falls_back_through_online_then_print(self):
        msg = {"published-online": _date_field(2023)}
        assert extract_crossref_pub_year(msg, max_year=_NEXT_YEAR) == 2023
        msg = {"published-print": _date_field(2022)}
        assert extract_crossref_pub_year(msg, max_year=_NEXT_YEAR) == 2022

    def test_thesis_falls_back_to_approved(self):
        """Cas réel : thèse ABES (10.70675) dont `issued` est vide et seule la soutenance est datée."""
        msg = {
            "type": "dissertation",
            "issued": {"date-parts": [[None]]},
            "approved": {"date-parts": [[2023, 12, 11]]},
        }
        assert extract_crossref_pub_year(msg, max_year=_NEXT_YEAR) == 2023


class TestExtractCrossrefPubYearFutureBound:
    """Garde-fou : les éditeurs déposent parfois des dates de "futur numéro"
    (2030+, parfois 2080, 2200…). Au-dessus de max_year, on retourne None
    — process_work skippe la normalisation et laisse les autres sources
    arbitrer."""

    def test_skips_far_future(self):
        msg = {"published": _date_field(2030), "issued": _date_field(2030)}
        assert extract_crossref_pub_year(msg, max_year=_NEXT_YEAR) is None

    def test_accepts_max_year(self):
        """Un preprint légitimement daté de l'année suivante reste accepté."""
        msg = {"published": _date_field(_NEXT_YEAR)}
        assert extract_crossref_pub_year(msg, max_year=_NEXT_YEAR) == _NEXT_YEAR

    def test_rejects_year_above_max(self):
        msg = {"published": _date_field(_NEXT_YEAR + 1)}
        assert extract_crossref_pub_year(msg, max_year=_NEXT_YEAR) is None

    def test_falls_back_when_first_field_in_future(self):
        """Hypothèse rare mais correcte : si published est en futur mais
        un fallback est passé, on prend le fallback."""
        future = _NEXT_YEAR + 5
        msg = {
            "published": _date_field(future),
            "issued": _date_field(future),
            "published-online": _date_field(2024),
        }
        assert extract_crossref_pub_year(msg, max_year=_NEXT_YEAR) == 2024


class TestExtractCrossrefPubYearMalformed:
    def test_missing_all_fields(self):
        assert extract_crossref_pub_year({}, max_year=_NEXT_YEAR) is None

    def test_empty_date_parts(self):
        assert (
            extract_crossref_pub_year({"published": {"date-parts": []}}, max_year=_NEXT_YEAR)
            is None
        )

    def test_invalid_year_string(self):
        assert (
            extract_crossref_pub_year({"published": {"date-parts": [["abc"]]}}, max_year=_NEXT_YEAR)
            is None
        )

    def test_pre_1500_rejected(self):
        """Bornage bas : un DOI antérieur à 1500 est manifestement aberrant."""
        assert (
            extract_crossref_pub_year({"published": _date_field(1200)}, max_year=_NEXT_YEAR) is None
        )

    def test_1500_accepted(self):
        assert (
            extract_crossref_pub_year({"published": _date_field(1500)}, max_year=_NEXT_YEAR) == 1500
        )


class TestParseCrossrefIssns:
    def test_separates_print_and_electronic(self):
        msg = {
            "issn-type": [
                {"type": "print", "value": "1234-5678"},
                {"type": "electronic", "value": "8765-4321"},
            ]
        }
        assert parse_crossref_issns(msg) == ("1234-5678", "8765-4321")

    def test_only_electronic(self):
        msg = {"issn-type": [{"type": "electronic", "value": "8765-4321"}]}
        assert parse_crossref_issns(msg) == (None, "8765-4321")

    def test_falls_back_to_plain_issn(self):
        msg = {"ISSN": ["1234-5678", "8765-4321"]}
        assert parse_crossref_issns(msg) == ("1234-5678", None)

    def test_empty(self):
        assert parse_crossref_issns({}) == (None, None)

    def test_ignores_malformed_entries(self):
        msg = {
            "issn-type": [
                {"type": "print"},  # pas de value
                {"value": "1234-5678"},  # pas de type → ignoré
                {"type": "print", "value": "  "},  # vide
                {"type": "print", "value": "1111-2222"},  # OK
            ]
        }
        assert parse_crossref_issns(msg) == ("1111-2222", None)

    def test_a_second_electronic_issn_is_not_taken_for_print(self):
        msg = {
            "issn-type": [
                {"type": "electronic", "value": "8765-4321"},
                {"type": "electronic", "value": "1111-2222"},
            ]
        }
        assert parse_crossref_issns(msg) == (None, "8765-4321")

    def test_non_textual_plain_issn_ignored(self):
        assert parse_crossref_issns({"ISSN": [None]}) == (None, None)


class TestStripJatsTags:
    def test_strips_simple_jats(self):
        assert strip_jats_tags("<jats:p>Hello</jats:p>") == "Hello"

    def test_strips_nested(self):
        assert strip_jats_tags("<jats:sec><jats:p>Body</jats:p></jats:sec>") == "Body"

    def test_no_tags_unchanged(self):
        assert strip_jats_tags("Plain text.") == "Plain text."

    def test_keeps_inequalities(self):
        # Le préfixe `jats:` est exigé : un encadrement scientifique n'est pas une balise.
        assert strip_jats_tags("mesuré pour 2.96<yCMS<3.53 GeV") == "mesuré pour 2.96<yCMS<3.53 GeV"
        assert strip_jats_tags("p < 0.001, ES = 0.20) puis n > 40") == (
            "p < 0.001, ES = 0.20) puis n > 40"
        )

    def test_keeps_html_markup(self):
        """Le formatage HTML relève de l'affichage, non des balises JATS."""
        assert strip_jats_tags("Surface <i>en italique</i> et <111>") == (
            "Surface <i>en italique</i> et <111>"
        )

    def test_runs_of_opening_angles_scan_linearly(self):
        """Le parcours d'une suite de `<` sans fermeture reste proportionnel à sa longueur."""
        import time

        start = time.perf_counter()
        strip_jats_tags("<A" * 100_000)
        assert time.perf_counter() - start < 1.0


class TestExtractCrossrefMeta:
    def test_keeps_whitelisted(self):
        msg = {
            "license": [{"URL": "https://x"}],
            "funder": [{"name": "ANR"}],
            "relation": {"is-supplemented-by": []},
            "references-count": 42,
            "indexed": {"timestamp": 1234567890},
            "title": ["ignored"],  # hors whitelist
        }
        meta = extract_crossref_meta(msg)
        assert meta is not None
        assert meta == {
            "license": [{"URL": "https://x"}],
            "funder": [{"name": "ANR"}],
            "relation": {"is-supplemented-by": []},
            "references_count": 42,
            "indexed": 1234567890,
        }

    def test_drops_zero_references_count(self):
        meta = extract_crossref_meta({"references-count": 0})
        assert meta is None

    def test_keeps_a_single_reference(self):
        assert extract_crossref_meta({"references-count": 1}) == {"references_count": 1}

    def test_falls_back_to_indexed_date_time(self):
        meta = extract_crossref_meta({"indexed": {"date-time": "2024-01-01T00:00:00Z"}})
        assert meta == {"indexed": "2024-01-01T00:00:00Z"}

    def test_returns_none_when_empty(self):
        assert extract_crossref_meta({}) is None

    def test_keeps_group_title_of_posted_content(self):
        meta = extract_crossref_meta({"type": "posted-content", "group-title": "oral"})
        assert meta == {"group_title": "oral"}

    def test_ignores_group_title_of_other_types(self):
        assert extract_crossref_meta({"type": "journal-article", "group-title": "x"}) is None

    def test_keeps_conference(self):
        meta = extract_crossref_meta({"event": {"name": "EUROCALL 2022"}})
        assert meta == {"conference": {"name": "EUROCALL 2022"}}


def _conference_assertion(name: str, value: str) -> dict:
    return {"group": {"name": "ConferenceInfo"}, "name": name, "value": value}


class TestExtractCrossrefConference:
    def test_event_of_proceedings_article(self):
        msg = {"type": "proceedings-article", "event": {"name": "SODA", "acronym": "SODA25"}}
        assert extract_crossref_conference(msg) == {"name": "SODA", "acronym": "SODA25"}

    def test_springer_assertions_of_book_chapter(self):
        """Cas réel : chapitre de Lecture Notes in Computer Science issu du congrès WG 2018."""
        msg = {
            "type": "book-chapter",
            "assertion": [
                _conference_assertion("conference_acronym", "WG"),
                _conference_assertion(
                    "conference_name",
                    "International Workshop on Graph-Theoretic Concepts in Computer Science",
                ),
                _conference_assertion("conference_city", "Cottbus"),
                {"group": {"name": "ArticleHistory"}, "name": "first_online", "value": "2018"},
            ],
        }
        assert extract_crossref_conference(msg) == {
            "name": "International Workshop on Graph-Theoretic Concepts in Computer Science",
            "acronym": "WG",
        }

    def test_acronym_without_name_is_ignored(self):
        msg = {"assertion": [_conference_assertion("conference_acronym", "WG")]}
        assert extract_crossref_conference(msg) is None

    def test_blank_name_is_ignored(self):
        assert extract_crossref_conference({"event": {"name": "  "}}) is None


class TestCrossrefRawDocType:
    def test_type_suivi_du_sous_type(self):
        assert crossref_raw_doc_type({"type": "posted-content", "subtype": "other"}) == (
            "posted-content_other"
        )

    def test_type_seul(self):
        assert crossref_raw_doc_type({"type": "journal-article"}) == "journal-article"
