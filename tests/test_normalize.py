"""Tests des fonctions de parsing des normaliseurs (pas besoin de DB)."""



# ── OpenAlex ─────────────────────────────────────────────────────

from processing.normalize_openalex import (
    extract_short_id,
    is_hal_primary_location,
    is_repository_source,
)
from utils.doc_types import _SOURCE_MAPS, map_doc_type
from utils.doc_types import _VALID_DOC_TYPES as VALID_DOC_TYPES_SET
from utils.hal import extract_hal_id_from_url


class TestOAExtractShortId:
    def test_standard_url(self):
        assert extract_short_id("https://openalex.org/W2741809807") == "W2741809807"

    def test_already_short(self):
        assert extract_short_id("W123") == "W123"

    def test_none(self):
        assert extract_short_id(None) == ""

    def test_empty(self):
        assert extract_short_id("") == ""


class TestOAIsHalPrimaryLocation:
    def test_hal_url(self):
        work = {"primary_location": {
            "landing_page_url": "https://hal.science/hal-04123456",
            "source": {}
        }}
        assert is_hal_primary_location(work) is True

    def test_tel_url(self):
        work = {"primary_location": {
            "landing_page_url": "https://theses.hal.science/tel-04123456",
            "source": {}
        }}
        assert is_hal_primary_location(work) is True

    def test_halshs_url(self):
        work = {"primary_location": {
            "landing_page_url": "https://shs.hal.science/halshs-01234567",
            "source": {}
        }}
        assert is_hal_primary_location(work) is True

    def test_not_hal(self):
        work = {"primary_location": {
            "landing_page_url": "https://doi.org/10.1234/test",
            "source": {"type": "journal"}
        }}
        assert is_hal_primary_location(work) is False

    def test_hal_repository_source(self):
        work = {"primary_location": {
            "landing_page_url": "https://example.com/something",
            "source": {
                "type": "repository",
                "display_name": "HAL",
                "homepage_url": "https://hal.archives-ouvertes.fr"
            }
        }}
        assert is_hal_primary_location(work) is True

    def test_no_location(self):
        assert is_hal_primary_location({}) is False
        assert is_hal_primary_location({"primary_location": None}) is False


class TestOAExtractHalIdFromUrl:
    def test_standard(self):
        assert extract_hal_id_from_url("https://hal.science/hal-04123456") == "hal-04123456"

    def test_with_version(self):
        assert extract_hal_id_from_url("https://hal.science/hal-04123456v2") == "hal-04123456"

    def test_tel(self):
        assert extract_hal_id_from_url("https://theses.hal.science/tel-01234567") == "tel-01234567"

    def test_inserm(self):
        assert extract_hal_id_from_url("https://hal.science/inserm-00123456") == "inserm-00123456"

    def test_no_match(self):
        assert extract_hal_id_from_url("https://doi.org/10.1234/test") is None

    def test_none(self):
        assert extract_hal_id_from_url(None) is None


class TestOAIsRepositorySource:
    def test_repository(self):
        work = {"primary_location": {"source": {"type": "repository"}}}
        assert is_repository_source(work) is True

    def test_journal(self):
        work = {"primary_location": {"source": {"type": "journal"}}}
        assert is_repository_source(work) is False

    def test_no_source(self):
        assert is_repository_source({}) is False


class TestOADocTypeMap:
    def test_covers_common_types(self):
        for t in ["article", "review", "book", "book-chapter",
                   "proceedings-article", "preprint", "dissertation"]:
            assert map_doc_type(t, "openalex") != "other", f"{t} non mappé"

    def test_all_values_valid(self):
        for v in _SOURCE_MAPS["openalex"].values():
            assert v in VALID_DOC_TYPES_SET, f"Type inconnu : {v}"


# ── HAL ──────────────────────────────────────────────────────────

from processing.normalize_hal import (
    as_str,
    get_title,
    parse_author_structures,
)


class TestHALAsStr:
    def test_none(self):
        assert as_str(None) is None

    def test_string(self):
        assert as_str("hello") == "hello"

    def test_list_single(self):
        assert as_str(["hello"]) == "hello"

    def test_list_multiple(self):
        assert as_str(["first", "second"]) == "first"

    def test_list_empty(self):
        assert as_str([]) is None

    def test_number(self):
        assert as_str(42) == "42"


class TestHALGetTitle:
    def test_string(self):
        assert get_title({"title_s": "Mon titre"}) == "Mon titre"

    def test_list(self):
        assert get_title({"title_s": ["Titre FR", "Title EN"]}) == "Titre FR"

    def test_fallback_label(self):
        assert get_title({"label_s": "Le label"}) == "Le label"

    def test_empty(self):
        assert get_title({}) == ""


class TestHALParseAuthorStructures:
    def test_standard_entry(self):
        doc = {
            "authIdHasStructure_fs": [
                "49236-749496_FacetSep_Dupont Jean_JoinSep_1234_FacetSep_LIMOS"
            ]
        }
        result = parse_author_structures(doc)
        assert result == {49236: {1234}}

    def test_multiple_structures(self):
        doc = {
            "authIdHasStructure_fs": [
                "100-200_FacetSep_Nom_JoinSep_1_FacetSep_Lab1",
                "100-200_FacetSep_Nom_JoinSep_2_FacetSep_Lab2",
            ]
        }
        result = parse_author_structures(doc)
        assert result == {100: {1, 2}}

    def test_multiple_authors(self):
        doc = {
            "authIdHasStructure_fs": [
                "100-200_FacetSep_Alice_JoinSep_1_FacetSep_Lab1",
                "300-400_FacetSep_Bob_JoinSep_2_FacetSep_Lab2",
            ]
        }
        result = parse_author_structures(doc)
        assert result == {100: {1}, 300: {2}}

    def test_empty(self):
        assert parse_author_structures({}) == {}
        assert parse_author_structures({"authIdHasStructure_fs": []}) == {}

    def test_malformed_entry(self):
        doc = {"authIdHasStructure_fs": ["garbage_data"]}
        assert parse_author_structures(doc) == {}

    def test_non_numeric_ids(self):
        doc = {"authIdHasStructure_fs": [
            "abc-def_FacetSep_Nom_JoinSep_xyz_FacetSep_Lab"
        ]}
        assert parse_author_structures(doc) == {}


class TestHALDocTypeMap:
    def test_covers_common_types(self):
        for t in ["ART", "COMM", "OUV", "COUV", "THESE", "HDR"]:
            assert map_doc_type(t, "hal") != "other", f"{t} non mappé"

    def test_all_values_valid(self):
        for v in _SOURCE_MAPS["hal"].values():
            assert v in VALID_DOC_TYPES_SET, f"Type inconnu : {v}"


# ── WoS ──────────────────────────────────────────────────────────

from processing.normalize_wos import (
    _get_api_title,
    _safe_list,
    map_oa_status,
)
from processing.normalize_wos import (
    map_doc_type as wos_map_doc_type,
)


class TestWoSMapDocType:
    def test_simple(self):
        assert wos_map_doc_type("Article") == "article"
        assert wos_map_doc_type("Review") == "review"

    def test_composite(self):
        assert wos_map_doc_type("Article; Proceedings Paper") == "article"

    def test_composite_other_first(self):
        """Si le premier type est 'erratum', cherche un type plus significatif."""
        assert wos_map_doc_type("Correction; Article") == "erratum"

    def test_none(self):
        assert wos_map_doc_type(None) == "other"

    def test_unknown(self):
        assert wos_map_doc_type("Unknown Type XYZ") == "other"

    def test_case_insensitive(self):
        assert wos_map_doc_type("ARTICLE") == "article"


class TestWoSMapOaStatus:
    def test_gold(self):
        assert map_oa_status("gold") == "gold"

    def test_priority(self):
        assert map_oa_status("gold, green") == "gold"
        assert map_oa_status("green, hybrid") == "hybrid"

    def test_none(self):
        assert map_oa_status(None) == "unknown"

    def test_empty(self):
        assert map_oa_status("") == "unknown"


class TestWoSSafeList:
    def test_list(self):
        assert _safe_list([1, 2]) == [1, 2]

    def test_dict(self):
        assert _safe_list({"a": 1}) == [{"a": 1}]

    def test_none(self):
        assert _safe_list(None) == []


class TestWoSGetApiTitle:
    def test_item_title(self):
        static = {"summary": {"titles": {"title": [
            {"type": "item", "content": "Mon article"},
            {"type": "source", "content": "Ma revue"},
        ]}}}
        assert _get_api_title(static, "item") == "Mon article"
        assert _get_api_title(static, "source") == "Ma revue"

    def test_single_title_dict(self):
        static = {"summary": {"titles": {"title":
            {"type": "item", "content": "Unique"}
        }}}
        assert _get_api_title(static, "item") == "Unique"

    def test_not_found(self):
        static = {"summary": {"titles": {"title": []}}}
        assert _get_api_title(static, "item") is None


class TestWoSDocTypeMap:
    def test_covers_common_types(self):
        for t in ["article", "review", "book", "book chapter",
                   "proceedings paper", "editorial material"]:
            assert map_doc_type(t, "wos") != "other", f"{t} non mappé"


# ── NNT ─────────────────────────────────────────────────────────

from utils.nnt import extract_nnt_from_openalex, is_theses_fr_source, normalize_nnt


class TestNormalizeNnt:
    def test_standard(self):
        assert normalize_nnt("2023UCFA0069") == "2023UCFA0069"

    def test_lowercase(self):
        assert normalize_nnt("2023ucfa0069") == "2023UCFA0069"

    def test_whitespace(self):
        assert normalize_nnt("  2023UCFA0069  ") == "2023UCFA0069"

    def test_none(self):
        assert normalize_nnt(None) is None

    def test_empty(self):
        assert normalize_nnt("") is None


class TestIsThesesFrSource:
    def test_display_name(self):
        work = {"primary_location": {
            "source": {"display_name": "theses.fr (ABES)"},
            "landing_page_url": ""
        }}
        assert is_theses_fr_source(work) is True

    def test_url(self):
        work = {"primary_location": {
            "source": {},
            "landing_page_url": "http://www.theses.fr/2023UCFA0069/document"
        }}
        assert is_theses_fr_source(work) is True

    def test_not_theses(self):
        work = {"primary_location": {
            "source": {"display_name": "Elsevier"},
            "landing_page_url": "https://doi.org/10.1234"
        }}
        assert is_theses_fr_source(work) is False

    def test_no_location(self):
        assert is_theses_fr_source({}) is False


class TestExtractNntFromOpenalex:
    def test_pmh_format(self):
        work = {"primary_location": {
            "id": "pmh:2023UCFA0069",
            "landing_page_url": ""
        }}
        assert extract_nnt_from_openalex(work) == "2023UCFA0069"

    def test_url_format(self):
        work = {"primary_location": {
            "id": "",
            "landing_page_url": "http://www.theses.fr/2023UCFA0069/document"
        }}
        assert extract_nnt_from_openalex(work) == "2023UCFA0069"

    def test_no_nnt(self):
        work = {"primary_location": {
            "id": "",
            "landing_page_url": "https://doi.org/10.1234"
        }}
        assert extract_nnt_from_openalex(work) is None

    def test_no_location(self):
        assert extract_nnt_from_openalex({}) is None
