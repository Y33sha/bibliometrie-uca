"""Tests des extracteurs purs `domain.sources.datacite` et du mapping
doc_type DataCite."""

from domain.source_publications.doc_types import map_doc_type
from domain.sources.datacite import (
    extract_datacite_doc_type_token,
    extract_datacite_meta,
    extract_datacite_pub_year,
    extract_related_dois,
    get_abstract,
    get_cited_by_count,
    get_container,
    get_keywords,
    get_language,
    get_publisher_name,
    get_title,
)


class TestGetTitle:
    def test_skips_subtitle_type(self):
        attrs = {
            "titles": [
                {"title": "Sous-titre", "titleType": "Subtitle"},
                {"title": "Titre principal"},
            ]
        }
        assert get_title(attrs) == "Titre principal"

    def test_fallback_to_first_when_all_typed(self):
        attrs = {"titles": [{"title": "Alt", "titleType": "AlternativeTitle"}]}
        assert get_title(attrs) == "Alt"

    def test_none_when_empty(self):
        assert get_title({"titles": []}) is None


class TestPubYear:
    def test_valid(self):
        assert extract_datacite_pub_year({"publicationYear": 2020}, max_year=2027) == 2020

    def test_above_max(self):
        assert extract_datacite_pub_year({"publicationYear": 2999}, max_year=2027) is None

    def test_non_int(self):
        assert extract_datacite_pub_year({"publicationYear": None}, max_year=2027) is None


class TestPublisher:
    def test_string(self):
        assert get_publisher_name({"publisher": "Zenodo"}) == "Zenodo"

    def test_object(self):
        assert get_publisher_name({"publisher": {"name": "INRAE"}}) == "INRAE"

    def test_absent(self):
        assert get_publisher_name({}) is None

    def test_object_without_textual_name(self):
        assert get_publisher_name({"publisher": {"name": None}}) is None


class TestContainer:
    def test_not_an_object(self):
        assert get_container({"container": "Journal of Things"}) == (None, None)

    def test_issn_without_title(self):
        attrs = {"container": {"identifier": "1234-5678", "identifierType": "ISSN"}}
        assert get_container(attrs) == (None, "1234-5678")

    def test_issn_type_without_identifier(self):
        attrs = {"container": {"title": "X", "identifier": None, "identifierType": "ISSN"}}
        assert get_container(attrs) == ("X", None)

    def test_title_and_issn(self):
        attrs = {
            "container": {
                "title": "Journal of Things",
                "identifier": "1234-5678",
                "identifierType": "ISSN",
            }
        }
        assert get_container(attrs) == ("Journal of Things", "1234-5678")

    def test_issn_ignored_when_not_issn_type(self):
        attrs = {"container": {"title": "X", "identifier": "abc", "identifierType": "URL"}}
        assert get_container(attrs) == ("X", None)

    def test_empty(self):
        assert get_container({"container": {}}) == (None, None)


class TestAbstract:
    def test_prefers_abstract_type(self):
        attrs = {
            "descriptions": [
                {"description": "Methods text", "descriptionType": "Methods"},
                {"description": "Le résumé", "descriptionType": "Abstract"},
            ]
        }
        assert get_abstract(attrs) == "Le résumé"

    def test_fallback_first(self):
        attrs = {"descriptions": [{"description": "Texte", "descriptionType": "Other"}]}
        assert get_abstract(attrs) == "Texte"

    def test_skips_a_non_textual_description(self):
        attrs = {"descriptions": [{"description": None}, {"description": "Texte"}]}
        assert get_abstract(attrs) == "Texte"


class TestKeywords:
    def test_dedupe_preserve_order(self):
        attrs = {
            "subjects": [
                {"subject": "Sociology"},
                {"subject": "sociology"},
                {"subject": "Biology"},
            ]
        }
        assert get_keywords(attrs) == ["Sociology", "Biology"]

    def test_none_when_empty(self):
        assert get_keywords({"subjects": []}) is None


class TestDocTypeToken:
    def test_specific_general_wins(self):
        attrs = {"types": {"resourceTypeGeneral": "JournalArticle", "resourceType": "Article"}}
        assert extract_datacite_doc_type_token(attrs) == "JournalArticle"

    def test_preprint_general_over_article_resourcetype(self):
        attrs = {"types": {"resourceTypeGeneral": "Preprint", "resourceType": "Article"}}
        assert extract_datacite_doc_type_token(attrs) == "Preprint"

    def test_text_falls_back_to_resourcetype(self):
        attrs = {"types": {"resourceTypeGeneral": "Text", "resourceType": "Working Paper"}}
        assert extract_datacite_doc_type_token(attrs) == "Working Paper"

    def test_text_without_resourcetype(self):
        attrs = {"types": {"resourceTypeGeneral": "Text", "resourceType": ""}}
        assert extract_datacite_doc_type_token(attrs) == "Text"

    def test_other_falls_back_to_resourcetype(self):
        attrs = {"types": {"resourceTypeGeneral": "Other", "resourceType": "Poster"}}
        assert extract_datacite_doc_type_token(attrs) == "Poster"

    def test_resourcetype_without_general(self):
        attrs = {"types": {"resourceType": "Journal Article"}}
        assert extract_datacite_doc_type_token(attrs) == "Journal Article"


class TestDocTypeMapping:
    def test_journal_article(self):
        assert map_doc_type("JournalArticle", "datacite") == "article"

    def test_working_paper_is_preprint(self):
        assert map_doc_type("Working Paper", "datacite") == "preprint"

    def test_dataset(self):
        assert map_doc_type("Dataset", "datacite") == "dataset"

    def test_text_is_other(self):
        assert map_doc_type("Text", "datacite") == "other"

    def test_book_chapter(self):
        assert map_doc_type("Book Chapter", "datacite") == "book_chapter"


class TestRelatedDois:
    def _attrs(self):
        return {
            "relatedIdentifiers": [
                {
                    "relatedIdentifier": "10.5281/zenodo.999",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsVersionOf",
                },
                {
                    "relatedIdentifier": "10.1234/cited",
                    "relatedIdentifierType": "DOI",
                    "relationType": "Cites",
                },
                {
                    "relatedIdentifier": "10.1234/suppl",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsSupplementTo",
                },
                {
                    "relatedIdentifier": "https://example.org/x",
                    "relatedIdentifierType": "URL",
                    "relationType": "IsVersionOf",
                },
                {
                    "relatedIdentifier": "10.5555/self",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsVersionOf",
                },
            ]
        }

    def test_filters_citations_and_self_and_non_doi(self):
        dois = extract_related_dois(self._attrs(), "10.5555/self")
        assert dois == ["10.5281/zenodo.999", "10.1234/suppl"]

    def test_meta_keeps_all_doi_relations_with_type(self):
        meta = extract_datacite_meta(self._attrs())
        related = meta["related_identifiers"]
        # Toutes les relations DOI (citations comprises), avec leur type ; pas les URL.
        types = {r["relation_type"] for r in related}
        assert types == {"IsVersionOf", "Cites", "IsSupplementTo"}
        assert all(r["doi"].startswith("10.") for r in related)

    def test_a_relation_needs_a_doi_and_a_relation_type(self):
        attrs = {
            "relatedIdentifiers": [
                {
                    "relatedIdentifier": "",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsPartOf",
                },
                {"relatedIdentifier": "10.1234/sans-type", "relatedIdentifierType": "DOI"},
                {
                    "relatedIdentifier": "10.1234/partie",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsPartOf",
                },
            ]
        }
        assert extract_datacite_meta(attrs) == {
            "related_identifiers": [{"doi": "10.1234/partie", "relation_type": "IsPartOf"}]
        }

    def test_related_dois_after_the_own_doi_are_kept_once(self):
        attrs = {
            "relatedIdentifiers": [
                {
                    "relatedIdentifier": "10.5555/self",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsVersionOf",
                },
                {
                    "relatedIdentifier": "10.5281/zenodo.999",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsVersionOf",
                },
                {
                    "relatedIdentifier": "10.5281/zenodo.999",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsSupplementTo",
                },
            ]
        }
        assert extract_related_dois(attrs, "10.5555/self") == ["10.5281/zenodo.999"]


class TestLanguage:
    def test_le_code_langue_est_rendu_en_minuscules(self):
        assert get_language({"language": "EN"}) == "en"

    def test_les_espaces_qui_entourent_sont_retires(self):
        assert get_language({"language": "  fr  "}) == "fr"

    def test_absent_ou_vide_ne_donne_rien(self):
        assert get_language({}) is None
        assert get_language({"language": "   "}) is None

    def test_une_valeur_qui_n_est_pas_du_texte_ne_donne_rien(self):
        assert get_language({"language": 42}) is None


class TestCitedByCount:
    def test_le_compte_est_rendu(self):
        assert get_cited_by_count({"citationCount": 17}) == 17

    def test_un_compte_nul_est_rendu(self):
        assert get_cited_by_count({"citationCount": 0}) == 0

    def test_absent_ou_d_une_autre_nature_ne_donne_rien(self):
        assert get_cited_by_count({}) is None
        assert get_cited_by_count({"citationCount": "17"}) is None


class TestMeta:
    """Champs propres à DataCite conservés en JSONB : identifiants liés, licences, financeurs."""

    def test_les_licences_sont_conservees(self):
        attrs = {"rightsList": [{"rights": "CC-BY-4.0"}]}
        assert extract_datacite_meta(attrs) == {"rights": [{"rights": "CC-BY-4.0"}]}

    def test_les_financeurs_sont_conserves(self):
        attrs = {"fundingReferences": [{"funderName": "ANR"}]}
        assert extract_datacite_meta(attrs) == {"funding": [{"funderName": "ANR"}]}

    def test_les_identifiants_lies_portent_leur_type_de_relation(self):
        attrs = {
            "relatedIdentifiers": [
                {
                    "relatedIdentifierType": "DOI",
                    "relatedIdentifier": "10.5281/ZENODO.1",
                    "relationType": "IsVersionOf",
                }
            ]
        }
        meta = extract_datacite_meta(attrs)
        assert meta is not None
        assert meta["related_identifiers"] == [
            {"doi": "10.5281/zenodo.1", "relation_type": "IsVersionOf"}
        ]

    def test_les_trois_champs_se_composent(self):
        attrs = {
            "rightsList": [{"rights": "CC0"}],
            "fundingReferences": [{"funderName": "ERC"}],
        }
        meta = extract_datacite_meta(attrs)
        assert meta is not None
        assert set(meta) == {"rights", "funding"}

    def test_une_liste_vide_n_est_pas_conservee(self):
        assert extract_datacite_meta({"rightsList": [], "fundingReferences": []}) is None

    def test_une_valeur_qui_n_est_pas_une_liste_est_ecartee(self):
        assert extract_datacite_meta({"rightsList": "CC-BY", "fundingReferences": {}}) is None

    def test_sans_aucun_champ_il_n_y_a_pas_de_meta(self):
        assert extract_datacite_meta({}) is None


class TestEntreesAEcarterAvantLaBonne:
    """Chaque extracteur passe les entrées inexploitables et lit la suivante.

    Une source place ce qu'elle veut dans ses listes : une entrée d'une autre forme, ou au texte vide, précède parfois celle qui porte la valeur.
    """

    def test_le_titre_vient_de_la_premiere_entree_exploitable(self):
        attrs = {"titles": ["pas un objet", {"title": "   "}, {"title": "Le vrai titre"}]}
        assert get_title(attrs) == "Le vrai titre"

    def test_le_resume_vient_de_la_premiere_entree_exploitable(self):
        attrs = {
            "descriptions": [
                "pas un objet",
                {"description": "  "},
                {"description": "Le résumé", "descriptionType": "Abstract"},
            ]
        }
        assert get_abstract(attrs) == "Le résumé"

    def test_l_editeur_vient_de_la_premiere_entree_exploitable(self):
        assert get_publisher_name({"publisher": {"name": "Zenodo"}}) == "Zenodo"

    def test_les_mots_cles_ecartent_les_entrees_inexploitables(self):
        attrs = {"subjects": ["pas un objet", {"subject": "  "}, {"subject": "Biologie"}]}
        assert get_keywords(attrs) == ["Biologie"]

    def test_les_dois_lies_ecartent_les_entrees_inexploitables(self):
        attrs = {
            "relatedIdentifiers": [
                "pas un objet",
                {"relatedIdentifierType": "URL", "relatedIdentifier": "https://exemple.fr"},
                {
                    "relatedIdentifierType": "DOI",
                    "relatedIdentifier": "10.5281/ZENODO.2",
                    "relationType": "IsPartOf",
                },
            ]
        }
        meta = extract_datacite_meta(attrs)
        assert meta is not None
        assert meta["related_identifiers"] == [
            {"doi": "10.5281/zenodo.2", "relation_type": "IsPartOf"}
        ]


class TestBornesDeLAnnee:
    """L'année retenue tombe entre 1500 et `max_year`, bornes incluses."""

    def test_la_borne_basse_est_incluse(self):
        assert extract_datacite_pub_year({"publicationYear": 1500}, max_year=2030) == 1500

    def test_juste_en_dessous_de_la_borne_basse_est_ecarte(self):
        assert extract_datacite_pub_year({"publicationYear": 1499}, max_year=2030) is None

    def test_la_borne_haute_est_incluse(self):
        assert extract_datacite_pub_year({"publicationYear": 2030}, max_year=2030) == 2030

    def test_juste_au_dessus_de_la_borne_haute_est_ecarte(self):
        assert extract_datacite_pub_year({"publicationYear": 2031}, max_year=2030) is None
