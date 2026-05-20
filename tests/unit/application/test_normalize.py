"""Tests des fonctions de parsing des normaliseurs (pas besoin de DB)."""


# ── OpenAlex ─────────────────────────────────────────────────────

from application.pipeline.normalize.normalize_openalex import (
    extract_short_id,
)
from domain.publications.doc_types import _SOURCE_MAPS, map_doc_type
from domain.publications.doc_types import _VALID_DOC_TYPES as VALID_DOC_TYPES_SET
from domain.publications.identifiers import extract_hal_id_from_url


class TestOAExtractShortId:
    def test_standard_url(self):
        assert extract_short_id("https://openalex.org/W2741809807") == "W2741809807"

    def test_already_short(self):
        assert extract_short_id("W123") == "W123"

    def test_none(self):
        assert extract_short_id(None) == ""

    def test_empty(self):
        assert extract_short_id("") == ""


# is_hal_primary_location migré vers domain/sources/openalex.is_hal_location
# (cf. tests/unit/domain/sources/test_openalex.py).


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


# is_repository_source migré vers domain/sources/openalex.is_repository_location
# (cf. tests/unit/domain/sources/test_openalex.py).


class TestOADocTypeMap:
    def test_covers_common_types(self):
        for t in [
            "article",
            "review",
            "book",
            "book-chapter",
            "proceedings-article",
            "preprint",
            "dissertation",
        ]:
            assert map_doc_type(t, "openalex") != "other", f"{t} non mappé"

    def test_all_values_valid(self):
        for v in _SOURCE_MAPS["openalex"].values():
            assert v in VALID_DOC_TYPES_SET, f"Type inconnu : {v}"


# ── HAL ──────────────────────────────────────────────────────────

from application.pipeline.normalize.normalize_hal import (
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
        assert result == {49236: {"1234"}}

    def test_multiple_structures(self):
        doc = {
            "authIdHasStructure_fs": [
                "100-200_FacetSep_Nom_JoinSep_1_FacetSep_Lab1",
                "100-200_FacetSep_Nom_JoinSep_2_FacetSep_Lab2",
            ]
        }
        result = parse_author_structures(doc)
        assert result == {100: {"1", "2"}}

    def test_multiple_authors(self):
        doc = {
            "authIdHasStructure_fs": [
                "100-200_FacetSep_Alice_JoinSep_1_FacetSep_Lab1",
                "300-400_FacetSep_Bob_JoinSep_2_FacetSep_Lab2",
            ]
        }
        result = parse_author_structures(doc)
        assert result == {100: {"1"}, 300: {"2"}}

    def test_empty(self):
        assert parse_author_structures({}) == {}
        assert parse_author_structures({"authIdHasStructure_fs": []}) == {}

    def test_malformed_entry(self):
        doc = {"authIdHasStructure_fs": ["garbage_data"]}
        assert parse_author_structures(doc) == {}

    def test_non_numeric_form_id(self):
        # form_id reste numérique (clé de groupement par auteur HAL),
        # mais struct_id est accepté tel quel (text natif HAL).
        doc = {"authIdHasStructure_fs": ["abc-def_FacetSep_Nom_JoinSep_xyz_FacetSep_Lab"]}
        assert parse_author_structures(doc) == {}

    def test_prefers_primary_structure(self):
        """authIdHasPrimaryStructure_fs (labos feuilles) prime sur
        authIdHasStructure_fs (arbre tutelles aplati). Évite de gonfler la
        table addresses avec les tutelles parentes."""
        doc = {
            "authIdHasPrimaryStructure_fs": [
                "100-200_FacetSep_Mouchet_JoinSep_1063691_FacetSep_IHRIM",
            ],
            "authIdHasStructure_fs": [
                "100-200_FacetSep_Mouchet_JoinSep_1063691_FacetSep_IHRIM",
                "100-200_FacetSep_Mouchet_JoinSep_6818_FacetSep_ENS Lyon",
                "100-200_FacetSep_Mouchet_JoinSep_441569_FacetSep_CNRS",
            ],
        }
        assert parse_author_structures(doc) == {100: {"1063691"}}

    def test_falls_back_to_all_structures_when_primary_empty(self):
        """Si Primary est vide (ancien doc HAL), fallback sur l'arbre complet
        plutôt que de perdre l'info d'affiliation."""
        doc = {
            "authIdHasPrimaryStructure_fs": [],
            "authIdHasStructure_fs": [
                "100-200_FacetSep_Nom_JoinSep_1_FacetSep_Lab",
            ],
        }
        assert parse_author_structures(doc) == {100: {"1"}}


class TestHALDocTypeMap:
    def test_covers_common_types(self):
        for t in ["ART", "COMM", "OUV", "COUV", "THESE", "HDR"]:
            assert map_doc_type(t, "hal") != "other", f"{t} non mappé"

    def test_all_values_valid(self):
        for v in _SOURCE_MAPS["hal"].values():
            assert v in VALID_DOC_TYPES_SET, f"Type inconnu : {v}"


# ── WoS ──────────────────────────────────────────────────────────

from application.pipeline.normalize.normalize_wos import (
    _get_api_title,
    _safe_list,
)


class TestWoSSafeList:
    def test_list(self):
        assert _safe_list([1, 2]) == [1, 2]

    def test_dict(self):
        assert _safe_list({"a": 1}) == [{"a": 1}]

    def test_none(self):
        assert _safe_list(None) == []


class TestWoSGetApiTitle:
    def test_item_title(self):
        static = {
            "summary": {
                "titles": {
                    "title": [
                        {"type": "item", "content": "Mon article"},
                        {"type": "source", "content": "Ma revue"},
                    ]
                }
            }
        }
        assert _get_api_title(static, "item") == "Mon article"
        assert _get_api_title(static, "source") == "Ma revue"

    def test_single_title_dict(self):
        static = {"summary": {"titles": {"title": {"type": "item", "content": "Unique"}}}}
        assert _get_api_title(static, "item") == "Unique"

    def test_not_found(self):
        static = {"summary": {"titles": {"title": []}}}
        assert _get_api_title(static, "item") is None


class TestWoSDocTypeMap:
    def test_covers_common_types(self):
        for t in [
            "article",
            "review",
            "book",
            "book chapter",
            "proceedings paper",
            "editorial material",
        ]:
            assert map_doc_type(t, "wos") != "other", f"{t} non mappé"


# ── CrossRef ────────────────────────────────────────────────────


class TestCrossRefDocTypeMap:
    def test_covers_common_types(self):
        for t in [
            "journal-article",
            "book-chapter",
            "book",
            "monograph",
            "edited-book",
            "proceedings-article",
            "posted-content",
            "dissertation",
            "peer-review",
            "report",
        ]:
            assert map_doc_type(t, "crossref") != "other", f"{t} non mappé"

    def test_all_values_valid(self):
        for v in _SOURCE_MAPS["crossref"].values():
            assert v in VALID_DOC_TYPES_SET, f"Type inconnu : {v}"


# ── arbitrate_doc_type_with_article_subtype : arbitrage type vs sous-type ──


class TestFirstDocTypeArbitration:
    """Arbitrage CrossRef (`journal-article`) vs sous-type plus précis."""

    @staticmethod
    def _src(source: str, doc_type: str | None) -> "SourcePublication":  # noqa: F821
        from domain.source_publications.source_publication import SourcePublication

        return SourcePublication(
            id=None, source=source, source_id="x", title="x", doc_type=doc_type
        )

    def _arbitrate(self):
        from domain.publications.aggregation import arbitrate_doc_type_with_article_subtype

        return arbitrate_doc_type_with_article_subtype

    def test_crossref_article_yields_to_hal_review(self):
        """CrossRef `journal-article` ne doit pas écraser un sous-type review fourni par HAL (priorité moindre)."""
        arbitrate = self._arbitrate()
        sources = [
            self._src("crossref", "journal-article"),  # priorité 2
            self._src("hal", "art_artrev"),  # priorité 4 → review
        ]
        assert arbitrate(sources) == "review"

    def test_crossref_book_chapter_kept(self):
        """CrossRef `book-chapter` est mappé directement, pas un sous-type d'article : la règle d'arbitrage ne s'applique pas."""
        arbitrate = self._arbitrate()
        sources = [
            self._src("crossref", "book-chapter"),
            self._src("hal", "art_artrev"),
        ]
        assert arbitrate(sources) == "book_chapter"

    def test_crossref_article_no_subtype_falls_back(self):
        """CrossRef `journal-article` sans sous-type ailleurs → article."""
        arbitrate = self._arbitrate()
        sources = [
            self._src("crossref", "journal-article"),
            self._src("hal", "art"),
        ]
        assert arbitrate(sources) == "article"

    def test_subtype_in_priority_source_kept(self):
        """Si la source prioritaire (theses) donne un type spécifique, l'arbitrage n'intervient pas."""
        arbitrate = self._arbitrate()
        sources = [
            self._src("theses", "thesis"),
            self._src("crossref", "journal-article"),
        ]
        assert arbitrate(sources) == "thesis"

    def test_empty_rows_returns_other(self):
        arbitrate = self._arbitrate()
        assert arbitrate([]) == "other"

    def test_all_null_doc_type_returns_other(self):
        arbitrate = self._arbitrate()
        sources = [
            self._src("crossref", None),
            self._src("hal", None),
        ]
        assert arbitrate(sources) == "other"


# ── NNT ─────────────────────────────────────────────────────────
# is_theses_fr_source / extract_nnt_from_openalex migrés vers
# domain/sources/openalex.py — voir tests/unit/domain/sources/test_openalex.py.

from domain.publications.identifiers import normalize_nnt


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


# ── theses.fr ────────────────────────────────────────────────────

from application.pipeline.normalize.normalize_theses import (
    _build_source_meta,
    extract_pub_metadata,
)


class TestThesesExtractPubMetadata:
    def test_soutenue(self):
        these = {
            "titrePrincipal": "Titre de la thèse",
            "dateSoutenance": "15/03/2023",
            "doi": "10.1234/test",
            "nnt": "2023ucfa0069",
        }
        meta = extract_pub_metadata(these)
        assert meta["title"] == "Titre de la thèse"
        assert meta["doc_type"] == "thesis"
        assert meta["pub_year"] == 2023
        assert meta["doi"] == "10.1234/test"
        assert meta["nnt"] == "2023UCFA0069"
        assert meta["oa_status"] == "closed"
        assert meta["journal_id"] is None
        assert meta["title_normalized"]  # non vide

    def test_en_cours_falls_back_to_inscription(self):
        these = {
            "titrePrincipal": "Thèse en cours",
            "datePremiereInscriptionDoctorat": "01/09/2022",
        }
        meta = extract_pub_metadata(these)
        assert meta["doc_type"] == "ongoing_thesis"
        assert meta["pub_year"] == 2022
        assert meta["doi"] is None
        assert meta["nnt"] is None

    def test_no_dates(self):
        meta = extract_pub_metadata({"titrePrincipal": "X"})
        assert meta["doc_type"] == "ongoing_thesis"
        assert meta["pub_year"] is None

    def test_malformed_date(self):
        """Date non parseable → pub_year reste None."""
        meta = extract_pub_metadata({"titrePrincipal": "X", "dateSoutenance": "date-invalide"})
        assert meta["pub_year"] is None

    def test_no_title(self):
        meta = extract_pub_metadata({})
        assert meta["title"] is None
        assert meta["title_normalized"] is None


class TestThesesBuildSourceMeta:
    def test_full(self):
        these = {
            "dateSoutenance": "15/03/2023",
            "datePremiereInscriptionDoctorat": "01/09/2020",
            "discipline": "Informatique",
            "ecolesDoctorale": [{"nom": "SPI", "ppn": "028"}, {"nom": ""}],
            "partenairesDeRecherche": [
                {"nom": "LIMOS", "type": "lab"},
                {"nom": "CNRS", "type": "org"},
            ],
        }
        meta = _build_source_meta(these)
        assert meta == {
            "date_soutenance": "2023-03-15",
            "date_inscription": "2020-09-01",
            "discipline": "Informatique",
            "ecoles_doctorales": [{"nom": "SPI", "ppn": "028"}],
            "partenaires": [
                {"nom": "LIMOS", "type": "lab"},
                {"nom": "CNRS", "type": "org"},
            ],
        }

    def test_empty(self):
        """Sans aucun champ exploitable → None."""
        assert _build_source_meta({}) is None

    def test_partial(self):
        meta = _build_source_meta({"discipline": "Physique"})
        assert meta == {"discipline": "Physique"}

    def test_filters_entries_without_nom(self):
        these = {
            "ecolesDoctorale": [{"nom": ""}, {"ppn": "123"}],
            "partenairesDeRecherche": [{"type": "lab"}],
        }
        assert _build_source_meta(these) is None


# ── authorship_roles ─────────────────────────────────────────────

from domain.publications.authorship_roles import map_role, merge_roles


class TestMapRole:
    def test_hal_standard(self):
        assert map_role("hal", "aut") == (["author"], False)

    def test_hal_corresponding(self):
        assert map_role("hal", "crp") == (["author"], True)

    def test_wos_author(self):
        assert map_role("wos", "author") == (["author"], False)

    def test_scanr_thesis_director(self):
        assert map_role("scanr", "directeurthese") == (["thesis_director"], False)

    def test_empty_role_defaults_to_author(self):
        assert map_role("hal", None) == (["author"], False)
        assert map_role("hal", "") == (["author"], False)

    def test_unknown_source_defaults_to_author(self):
        assert map_role("unknown", "aut") == (["author"], False)

    def test_unknown_role_returns_other(self):
        assert map_role("hal", "no_such_role_xyz") == (["other"], False)

    def test_case_insensitive_fallback(self):
        assert map_role("hal", "AUT") == (["author"], False)

    def test_strips_whitespace(self):
        assert map_role("hal", "  aut  ") == (["author"], False)


class TestMergeRoles:
    def test_single_role(self):
        assert merge_roles([["author"]]) == ["author"]

    def test_dedup(self):
        assert merge_roles([["author"], ["author"]]) == ["author"]

    def test_union(self):
        assert merge_roles([["author"], ["editor"]]) == ["author", "editor"]

    def test_sorted_output(self):
        """Le résultat est trié alphabétiquement."""
        result = merge_roles([["editor", "author", "translator"]])
        assert result == sorted(result)

    def test_drops_jury_member_when_specific_role_present(self):
        """Si thesis_director/rapporteur/jury_president → jury_member redondant."""
        assert "jury_member" not in merge_roles([["thesis_director", "jury_member"]])
        assert "jury_member" not in merge_roles([["rapporteur", "jury_member"]])
        assert "jury_member" not in merge_roles([["jury_president", "jury_member"]])

    def test_keeps_jury_member_alone(self):
        """Sans rôle spécifique, jury_member est conservé."""
        assert merge_roles([["jury_member"]]) == ["jury_member"]

    def test_empty(self):
        assert merge_roles([[]]) == []
        assert merge_roles([]) == []
