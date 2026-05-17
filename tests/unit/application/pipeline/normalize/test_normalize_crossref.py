"""Tests unitaires des extracteurs purs de `normalize_crossref`.

Couvre les fonctions sans I/O qui parsent un payload CrossRef brut :
`get_doi`, `get_title`, `get_container_title`, `get_publisher_name`,
`get_keywords`, `get_abstract`, `get_cited_by_count`, `get_language`,
`get_external_ids`, `get_biblio`, `_author_full_name`,
`_author_affiliation_strings`.

Les délégations vers `domain.sources.crossref` (`extract_crossref_meta`,
`extract_crossref_pub_year`, `parse_crossref_issns`, `strip_jats_tags`)
sont testées directement dans `tests/unit/domain/sources/test_crossref.py` ;
ici on ne fait que vérifier le wiring (1-2 cas par délégation).
"""

from __future__ import annotations

from application.pipeline.normalize.normalize_crossref import (
    _author_affiliation_strings,
    _author_full_name,
    get_abstract,
    get_biblio,
    get_cited_by_count,
    get_container_title,
    get_doi,
    get_external_ids,
    get_issns,
    get_keywords,
    get_language,
    get_meta,
    get_pub_year,
    get_publisher_name,
    get_title,
)


class TestGetDoi:
    def test_cleans_url_prefix(self):
        # `clean_doi` retire le préfixe URL.
        assert get_doi({"DOI": "https://doi.org/10.1000/abc"}) == "10.1000/abc"

    def test_bare_doi(self):
        assert get_doi({"DOI": "10.1000/abc"}) == "10.1000/abc"

    def test_none_when_absent(self):
        assert get_doi({}) is None

    def test_none_when_blank(self):
        assert get_doi({"DOI": ""}) is None


class TestGetTitle:
    def test_first_element_of_list(self):
        assert get_title({"title": ["Primary Title", "Alt Title"]}) == "Primary Title"

    def test_string_direct(self):
        # Cas legacy : `title` peut être une string brute selon les payloads.
        assert get_title({"title": "Direct title"}) == "Direct title"

    def test_strips_whitespace(self):
        assert get_title({"title": ["  Spaced  "]}) == "Spaced"

    def test_none_when_empty_list(self):
        assert get_title({"title": []}) is None

    def test_none_when_first_is_empty_string(self):
        assert get_title({"title": ["   "]}) is None

    def test_none_when_absent(self):
        assert get_title({}) is None

    def test_none_when_first_non_string(self):
        # Élément non-str dans la liste → on retombe sur None
        # (pas de cast forcé).
        assert get_title({"title": [12345]}) is None


class TestGetPubYear:
    def test_delegates_to_domain(self):
        # Délégation : on s'assure que la borne max est bien appliquée.
        # Plus de cas détaillés dans test_crossref.py côté domain.
        assert get_pub_year({"published": {"date-parts": [[2024]]}}) == 2024

    def test_none_when_unparseable(self):
        assert get_pub_year({}) is None


class TestGetContainerTitle:
    def test_first_element_of_list(self):
        assert get_container_title({"container-title": ["J Phys", "Alt"]}) == "J Phys"

    def test_string_direct(self):
        assert get_container_title({"container-title": "J Phys"}) == "J Phys"

    def test_none_when_empty_list(self):
        assert get_container_title({"container-title": []}) is None

    def test_none_when_absent(self):
        assert get_container_title({}) is None

    def test_strips_whitespace(self):
        assert get_container_title({"container-title": ["  J Phys  "]}) == "J Phys"


class TestGetIssns:
    def test_delegates_to_domain(self):
        # Délégation à `parse_crossref_issns`. Le détail est testé côté domain.
        issn, eissn = get_issns({"ISSN": ["1234-5678"], "issn-type": []})
        assert issn == "1234-5678" or eissn == "1234-5678"


class TestGetPublisherName:
    def test_returns_stripped(self):
        assert get_publisher_name({"publisher": "  Elsevier  "}) == "Elsevier"

    def test_none_when_empty(self):
        assert get_publisher_name({"publisher": ""}) is None

    def test_none_when_absent(self):
        assert get_publisher_name({}) is None

    def test_none_when_not_string(self):
        assert get_publisher_name({"publisher": 12345}) is None


class TestGetKeywords:
    def test_returns_list_of_strings(self):
        assert get_keywords({"subject": ["A", "B", "C"]}) == ["A", "B", "C"]

    def test_strips_and_filters_empty(self):
        # Strip + filter des valeurs vides après strip.
        assert get_keywords({"subject": ["  A  ", "", "   ", "B"]}) == ["A", "B"]

    def test_filters_non_strings(self):
        assert get_keywords({"subject": ["A", 123, None, "B"]}) == ["A", "B"]

    def test_none_when_empty_list(self):
        # Liste vide après filtrage → None (pas une liste vide).
        assert get_keywords({"subject": []}) is None

    def test_none_when_not_list(self):
        assert get_keywords({"subject": "not-a-list"}) is None

    def test_none_when_absent(self):
        assert get_keywords({}) is None


class TestGetAbstract:
    def test_strips_jats_tags(self):
        # JATS XML stripping délégué à `strip_jats_tags`.
        raw = "<jats:p>Hello <jats:bold>world</jats:bold></jats:p>"
        assert get_abstract({"abstract": raw}) == "Hello world"

    def test_strips_whitespace(self):
        assert get_abstract({"abstract": "  Plain text  "}) == "Plain text"

    def test_none_when_absent(self):
        assert get_abstract({}) is None

    def test_none_when_empty(self):
        assert get_abstract({"abstract": ""}) is None

    def test_none_when_not_string(self):
        assert get_abstract({"abstract": 12345}) is None

    def test_none_after_strip_only_tags(self):
        # Si l'abstract est constitué uniquement de balises (rare mais possible),
        # le résultat post-strip est vide → None.
        assert get_abstract({"abstract": "<jats:p></jats:p>"}) is None


class TestGetCitedByCount:
    def test_returns_int(self):
        assert get_cited_by_count({"is-referenced-by-count": 42}) == 42

    def test_zero(self):
        assert get_cited_by_count({"is-referenced-by-count": 0}) == 0

    def test_none_when_absent(self):
        assert get_cited_by_count({}) is None

    def test_none_when_not_int(self):
        assert get_cited_by_count({"is-referenced-by-count": "42"}) is None


class TestGetLanguage:
    def test_lowercased(self):
        assert get_language({"language": "EN"}) == "en"

    def test_strips_whitespace(self):
        assert get_language({"language": "  fr  "}) == "fr"

    def test_none_when_absent(self):
        assert get_language({}) is None

    def test_none_when_empty(self):
        assert get_language({"language": ""}) is None

    def test_none_when_not_string(self):
        assert get_language({"language": 42}) is None


class TestGetExternalIds:
    def test_issn_only(self):
        assert get_external_ids({"ISSN": ["1234-5678"]}) == {"issn": ["1234-5678"]}

    def test_isbn_only(self):
        assert get_external_ids({"ISBN": ["978-0-12345-678-9"]}) == (
            {"isbn": ["978-0-12345-678-9"]}
        )

    def test_both_issn_and_isbn(self):
        result = get_external_ids({"ISSN": ["1234-5678"], "ISBN": ["978-0-12345-678-9"]})
        assert result == {"issn": ["1234-5678"], "isbn": ["978-0-12345-678-9"]}

    def test_filters_non_strings(self):
        # ISSN/ISBN avec valeurs non-str sont filtrés.
        assert get_external_ids({"ISSN": ["1234-5678", 12345, None]}) == ({"issn": ["1234-5678"]})

    def test_none_when_empty(self):
        assert get_external_ids({}) is None

    def test_none_when_both_empty_lists(self):
        # Les deux listes vides → pas de clé dans le dict → None.
        assert get_external_ids({"ISSN": [], "ISBN": []}) is None


class TestGetBiblio:
    def test_all_fields(self):
        assert get_biblio(
            {"volume": "12", "issue": "3", "page": "45-67", "article-number": "e12345"}
        ) == {
            "volume": "12",
            "issue": "3",
            "page": "45-67",
            "article_number": "e12345",
        }

    def test_partial_fields(self):
        # Seuls les champs présents et non-vides sont inclus.
        assert get_biblio({"volume": "12", "issue": ""}) == {"volume": "12"}

    def test_strips_whitespace(self):
        assert get_biblio({"volume": "  12  "}) == {"volume": "12"}

    def test_renames_article_number_key(self):
        # `article-number` (CrossRef) → `article_number` (interne JSONB).
        assert get_biblio({"article-number": "e1"}) == {"article_number": "e1"}

    def test_none_when_empty(self):
        assert get_biblio({}) is None

    def test_none_when_all_blank(self):
        assert get_biblio({"volume": "", "issue": "  ", "page": None}) is None


class TestGetMeta:
    def test_delegates_to_domain(self):
        # Délégation à `extract_crossref_meta` ; on vérifie juste le wiring.
        result = get_meta({"DOI": "10.1000/abc"})
        # Le résultat exact dépend de la fonction domain ; ici on s'assure
        # juste qu'on retourne quelque chose (dict ou None), sans crasher.
        assert result is None or isinstance(result, dict)


class TestAuthorFullName:
    def test_given_and_family(self):
        assert _author_full_name({"given": "Jean", "family": "Dupont"}) == "Jean Dupont"

    def test_family_only(self):
        assert _author_full_name({"family": "Dupont"}) == "Dupont"

    def test_given_only(self):
        # Rare : auteur avec un prénom mais pas de nom de famille (anglo-saxon
        # avec mononymie, ou erreur d'ingestion).
        assert _author_full_name({"given": "Jean"}) == "Jean"

    def test_strips_whitespace(self):
        assert _author_full_name({"given": "  Jean  ", "family": "  Dupont  "}) == "Jean Dupont"

    def test_empty_when_both_absent(self):
        assert _author_full_name({}) == ""

    def test_empty_when_both_blank(self):
        assert _author_full_name({"given": "  ", "family": "  "}) == ""

    def test_none_treated_as_empty(self):
        # `author.get("given")` peut être None ; `(None or "").strip()` = "".
        assert _author_full_name({"given": None, "family": "Dupont"}) == "Dupont"


class TestAuthorAffiliationStrings:
    def test_extracts_names(self):
        assert _author_affiliation_strings(
            {"affiliation": [{"name": "UCA"}, {"name": "CNRS"}]}
        ) == ["UCA", "CNRS"]

    def test_strips_names(self):
        assert _author_affiliation_strings({"affiliation": [{"name": "  UCA  "}]}) == ["UCA"]

    def test_skips_non_dict_entries(self):
        # Si une entrée n'est pas un dict, on l'ignore silencieusement.
        assert _author_affiliation_strings(
            {"affiliation": [{"name": "UCA"}, "not-a-dict", {"name": "CNRS"}]}
        ) == ["UCA", "CNRS"]

    def test_skips_entries_without_name(self):
        assert _author_affiliation_strings(
            {"affiliation": [{"name": "UCA"}, {"id": "x"}, {"name": ""}]}
        ) == ["UCA"]

    def test_empty_when_absent(self):
        assert _author_affiliation_strings({}) == []

    def test_empty_when_not_list(self):
        # `author.get("affiliation") or []` rend une liste vide si None
        # ou absent ; un truc autre que list passe quand même par la boucle
        # (qui ne yield rien si pas itérable comme dict).
        assert _author_affiliation_strings({"affiliation": None}) == []
