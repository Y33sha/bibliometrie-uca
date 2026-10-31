"""Tests unitaires des fonctions pures de `pipeline.ingestion.crossref.normalize`.

Couvre les fonctions qui lisent un payload Crossref brut, et les méthodes `parse` et `publisher` de `CrossrefNormalizer`.

Les fonctions de `pipeline.ingestion.crossref.payload` sont testées dans `test_payload.py`. Ici, seul leur appel est vérifié.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from domain.persons.contributor_name import ContributorName
from domain.publications.licenses import License
from domain.serials.issns import IssnSupport, SerialIssn
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from pipeline.ingestion.common.locations import LocationFacts
from pipeline.ingestion.common.normalizer import PublisherFacts
from pipeline.ingestion.crossref.normalize import (
    CrossrefNormalizer,
    _author_affiliations,
    _author_name,
    build_crossref_author_records,
    crossref_identifiers,
    crossref_source_record,
    get_abstract,
    get_biblio,
    get_cited_by_count,
    get_container_facts,
    get_container_title,
    get_doi,
    get_isbns,
    get_issns,
    get_keywords,
    get_language,
    get_locations,
    get_publication_year,
    get_publisher_name,
    get_title,
)
from pipeline.transformation.publishing.find_or_create import Containers
from tests.helpers.normalize_doubles import identifier_values, staging_row


class TestGetLocations:
    def test_page_de_resolution_du_doi_avec_la_licence_de_la_version_editeur(self):
        msg = {
            "resource": {"primary": {"URL": "https://linkinghub.elsevier.com/retrieve/pii/X"}},
            "license": [
                {"URL": "https://creativecommons.org/licenses/by/4.0/", "content-version": "vor"}
            ],
            "link": [{"URL": "https://api.elsevier.com/content/article/PII:X"}],
        }
        assert get_locations(msg) == [
            LocationFacts(
                url="https://linkinghub.elsevier.com/retrieve/pii/X", license=License.CC_BY
            )
        ]

    def test_sans_page_de_resolution(self):
        assert get_locations({"link": [{"URL": "https://api.wiley.com/x"}]}) == []


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
        # Certains payloads donnent `title` en chaîne.
        assert get_title({"title": "Direct title"}) == "Direct title"

    def test_strips_whitespace(self):
        assert get_title({"title": ["  Spaced  "]}) == "Spaced"

    def test_reduces_whitespace(self):
        assert get_title({"title": ["Imprimitive\n   complex  reflection groups"]}) == (
            "Imprimitive complex reflection groups"
        )

    def test_none_when_empty_list(self):
        assert get_title({"title": []}) is None

    def test_none_when_first_is_empty_string(self):
        assert get_title({"title": ["   "]}) is None

    def test_none_when_absent(self):
        assert get_title({}) is None

    def test_none_when_first_non_string(self):
        # Un premier élément autre qu'une chaîne donne None, sans conversion.
        assert get_title({"title": [12345]}) is None


class TestGetPublicationYear:
    def test_delegates_to_domain(self):
        # Le détail est testé dans `test_payload.py`.
        assert get_publication_year({"published": {"date-parts": [[2024]]}}) == 2024

    def test_none_when_unparseable(self):
        assert get_publication_year({}) is None


class TestGetContainerTitle:
    def test_first_element_of_list(self):
        assert get_container_title({"container-title": ["J Phys", "Alt"]}) == "J Phys"

    def test_string_direct(self):
        assert get_container_title({"container-title": "J Phys"}) == "J Phys"

    def test_none_when_empty_list(self):
        assert get_container_title({"container-title": []}) is None

    def test_none_when_first_entry_is_blank(self):
        # Une entrée vide en tête donne None.
        assert get_container_title({"container-title": ["  "]}) is None

    def test_none_when_absent(self):
        assert get_container_title({}) is None

    def test_strips_whitespace(self):
        assert get_container_title({"container-title": ["  J Phys  "]}) == "J Phys"


class TestGetIssns:
    def test_delegates_to_domain(self):
        # Le détail de `parse_crossref_issns` est testé dans `test_payload.py`.
        issn, eissn = get_issns({"ISSN": ["1234-5679"], "issn-type": []})
        assert issn == "1234-5679" or eissn == "1234-5679"


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
        # Les espaces de bord sont retirés, les valeurs vides écartées.
        assert get_keywords({"subject": ["  A  ", "", "   ", "B"]}) == ["A", "B"]

    def test_filters_non_strings(self):
        assert get_keywords({"subject": ["A", 123, None, "B"]}) == ["A", "B"]

    def test_none_when_empty_list(self):
        # Une liste vide donne None.
        assert get_keywords({"subject": []}) is None

    def test_none_when_not_list(self):
        assert get_keywords({"subject": "not-a-list"}) is None

    def test_none_when_absent(self):
        assert get_keywords({}) is None


class TestGetAbstract:
    def test_strips_jats_tags(self):
        # Les balises JATS sont retirées par `strip_jats_tags`.
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
        # Un résumé fait seulement de balises donne None.
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


class TestGetIsbns:
    def test_issn_reste_hors_des_isbn(self):
        """L'ISSN identifie la revue : il figure dans `biblio.journal`."""
        assert get_isbns({"ISSN": ["1234-5679"]}) == ([], [])

    def test_isbn_only(self):
        assert get_isbns({"ISBN": ["978-0-12345-678-9"]}) == (["978-0-12345-678-9"], [])

    def test_electronic_isbn_goes_to_eisbn(self):
        """`isbn-type` donne le support de chaque ISBN."""
        result = get_isbns(
            {
                "ISBN": ["978-3-030-04869-3", "978-3-030-04870-9"],
                "isbn-type": [
                    {"value": "978-3-030-04869-3", "type": "print"},
                    {"value": "978-3-030-04870-9", "type": "electronic"},
                ],
            }
        )
        assert result == (["978-3-030-04869-3"], ["978-3-030-04870-9"])

    def test_filters_non_strings(self):
        assert get_isbns({"ISBN": ["978-0-12345-678-9", 12345, None]}) == (
            ["978-0-12345-678-9"],
            [],
        )


class TestCrossrefIdentifiers:
    def test_doi_primaire(self):
        assert crossref_identifiers({}, "10.1/x") == (
            SourceIdentifier(SourceIdentifierType.DOI, "10.1/x", SourceIdentifierRole.PRIMARY),
        )

    def test_isbn_secondaire_d_un_livre_lie_d_un_chapitre(self):
        isbn = {"ISBN": ["978-0-12345-678-9"]}
        book = crossref_identifiers({**isbn, "type": "book"}, "10.1/x")
        chapter = crossref_identifiers({**isbn, "type": "book-chapter"}, "10.1/x")
        assert book[1].role is SourceIdentifierRole.SECONDARY
        assert chapter[1].role is SourceIdentifierRole.RELATED


class TestGetBiblio:
    def test_all_fields(self):
        assert get_biblio(
            {"volume": "12", "issue": "3", "page": "45-67", "article-number": "e12345"}
        ) == {
            "volume": "12",
            "issue": "3",
            "first_page": "45",
            "last_page": "67",
            "article_number": "e12345",
        }

    def test_page_seule_egale_au_numero_d_article_ecartee(self):
        assert get_biblio({"page": "e12345", "article-number": "e12345"}) == {
            "article_number": "e12345"
        }

    def test_page_seule_gardee(self):
        assert get_biblio({"page": "1191"}) == {"first_page": "1191"}

    def test_partial_fields(self):
        # Seuls les champs présents et non-vides sont inclus.
        assert get_biblio({"volume": "12", "issue": ""}) == {"volume": "12"}

    def test_strips_whitespace(self):
        assert get_biblio({"volume": "  12  "}) == {"volume": "12"}

    def test_renames_article_number_key(self):
        # `article-number` de Crossref devient `article_number`.
        assert get_biblio({"article-number": "e1"}) == {"article_number": "e1"}

    def test_none_when_empty(self):
        assert get_biblio({}) is None

    def test_none_when_all_blank(self):
        assert get_biblio({"volume": "", "issue": "  ", "page": None}) is None

    def test_publisher_extracted(self):
        assert get_biblio({"publisher": "Elsevier"}) == {"publisher": "Elsevier"}

    def test_serial_built_from_container_title_and_issns(self):
        # `issn-type` donne le support de chaque ISSN ; la liste `ISSN` seule alimente `issn`.
        msg = {
            "container-title": ["Journal of Physics"],
            "issn-type": [
                {"type": "print", "value": "0022-3727"},
                {"type": "electronic", "value": "1361-6463"},
            ],
        }
        biblio = get_biblio(msg)
        assert biblio is not None
        assert biblio["journal"] == {
            "title": "Journal of Physics",
            "issn": "0022-3727",
            "eissn": "1361-6463",
        }

    def test_serial_title_only_when_no_issns(self):
        assert get_biblio({"container-title": ["J. Phys."]}) == {
            "journal": {"title": "J. Phys."},
        }


class TestAuthorName:
    def test_given_and_family(self):
        assert _author_name({"given": "Jean", "family": "Dupont"}) == ContributorName(
            last_name="Dupont", first_name="Jean"
        )

    def test_family_only(self):
        assert _author_name({"family": "Dupont"}) == ContributorName(last_name="Dupont")

    def test_given_only(self):
        # Auteur avec un prénom et sans nom de famille : le nom reste brut.
        assert _author_name({"given": "Jean"}) == ContributorName(raw="Jean")

    def test_strips_whitespace(self):
        assert _author_name({"given": "  Jean  ", "family": "  Dupont  "}) == ContributorName(
            last_name="Dupont", first_name="Jean"
        )

    def test_none_when_both_absent(self):
        assert _author_name({}) is None

    def test_none_when_both_blank(self):
        assert _author_name({"given": "  ", "family": "  "}) is None


def _texts(author: dict) -> list[str]:
    return [a.text for a in _author_affiliations(author)[0]]


class TestAuthorAffiliations:
    def test_extracts_names(self):
        assert _texts({"affiliation": [{"name": "UCA"}, {"name": "CNRS"}]}) == ["UCA", "CNRS"]

    def test_strips_names(self):
        assert _texts({"affiliation": [{"name": "  UCA  "}]}) == ["UCA"]

    def test_skips_entries_without_name(self):
        assert _texts({"affiliation": [{"name": "UCA"}, {"id": "x"}, {"name": ""}]}) == ["UCA"]

    def test_empty_when_absent(self):
        assert _texts({}) == []


# ── build_crossref_author_records ──────────────────


class TestBuildCrossrefAuthorRecords:
    def test_no_authors(self):
        assert build_crossref_author_records({}) == []

    def test_author_not_list(self):
        assert build_crossref_author_records({"author": "nope"}) == []

    def test_skip_without_name(self):
        assert build_crossref_author_records({"author": [{}]}) == []

    def test_full_record(self):
        msg = {
            "author": [
                {
                    "given": "Jean",
                    "family": "Dupont",
                    "ORCID": "https://orcid.org/0000-0001-2345-6789",
                    "sequence": "first",
                    "affiliation": [{"name": "UCA"}],
                }
            ]
        }
        rec = build_crossref_author_records(msg)[0]
        assert rec.name == ContributorName(last_name="Dupont", first_name="Jean")
        # Le rôle par défaut est `author`.
        assert rec.roles == ["author"]
        assert rec.identifiers == {"orcid": "0000-0001-2345-6789"}
        assert [a.text for a in rec.addresses] == ["UCA"]
        assert rec.addresses[0].countries is None

    def test_bare_author_no_identifiers(self):
        rec = build_crossref_author_records({"author": [{"family": "Dupont"}]})[0]
        assert rec.identifiers is None

    def test_name_seul_est_collectif(self):
        """Une entrée à `name` seul est une contribution source collective, à sa position dans la source."""
        msg = {
            "author": [
                {"family": "Dupont", "given": "Jean"},
                {"name": "for the PREDISTIM working group"},
            ]
        }
        recs = build_crossref_author_records(msg)
        assert [(r.position, r.name.display(), r.collective) for r in recs] == [
            (0, "Jean Dupont", False),
            (1, "for the PREDISTIM working group", True),
        ]

    def test_shared_orcid_kept_on_each_record(self):
        """La lecture renvoie l'ORCID de chaque auteur tel que la source le donne. L'écriture des contributions sources neutralise les ORCID partagés par plusieurs contributions sources."""
        msg = {
            "author": [
                {"family": "Acharya", "ORCID": "https://orcid.org/0000-0001-2345-6789"},
                {"family": "Das", "ORCID": "https://orcid.org/0000-0001-2345-6789"},
            ]
        }
        recs = build_crossref_author_records(msg)
        assert [r.identifiers for r in recs] == [
            {"orcid": "0000-0001-2345-6789"},
            {"orcid": "0000-0001-2345-6789"},
        ]


class TestGetContainerFacts:
    def test_article_revue_et_ses_deux_issn(self):
        facts = get_container_facts(
            {
                "type": "journal-article",
                "container-title": ["J. Things"],
                "issn-type": [
                    {"type": "print", "value": "1234-5679"},
                    {"type": "electronic", "value": "8765-4326"},
                ],
            }
        )
        assert facts.journal_title == "J. Things"
        assert facts.issns == (
            SerialIssn(issn="1234-5679", support=IssnSupport.PRINT),
            SerialIssn(issn="8765-4326", support=IssnSupport.ELECTRONIC),
        )

    def test_chapitre_collection_puis_livre(self):
        """Cas réel : 10.1007/978-3-030-57997-5_58, chapitre d'un livre de la collection IFIP AICT."""
        facts = get_container_facts(
            {
                "type": "book-chapter",
                "container-title": [
                    "IFIP Advances in Information and Communication Technology",
                    "Advances in Production Management Systems",
                ],
                "ISSN": ["1868-4238"],
                "ISBN": ["9783030580803"],
            }
        )
        assert facts.collection_title == "IFIP Advances in Information and Communication Technology"
        assert facts.book_title == "Advances in Production Management Systems"
        assert facts.isbns == ("9783030580803",)

    def test_chapitre_sans_issn_livre_seul(self):
        facts = get_container_facts(
            {"type": "book-chapter", "container-title": ["Le Paris du Moyen Âge"]}
        )
        assert (facts.collection_title, facts.book_title) == (None, "Le Paris du Moyen Âge")

    def test_chapitre_d_une_collection_issu_d_un_congres(self):
        """Sous une collection à ISSN, le volume d'actes prend le nom du congrès déclaré."""
        facts = get_container_facts(
            {
                "type": "book-chapter",
                "container-title": ["Lecture Notes in Computer Science"],
                "ISSN": ["0302-9743"],
                "assertion": [
                    {"group": {"name": "ConferenceInfo"}, "name": "conference_name", "value": "WG"}
                ],
            }
        )
        assert facts.declares_conference is True
        assert (facts.collection_title, facts.book_title) == (
            "Lecture Notes in Computer Science",
            "WG",
        )

    def test_article_de_congres_collection_et_volume(self):
        """Cas réel : le volume suit la collection."""
        facts = get_container_facts(
            {
                "type": "proceedings-article",
                "container-title": [
                    "Annals of Computer Science and Information Systems",
                    "Proceedings of the 2019 Federated Conference on Computer Science and Information Systems",
                ],
                "ISSN": ["2300-5963"],
            }
        )
        assert (facts.collection_title, facts.book_title) == (
            "Annals of Computer Science and Information Systems",
            "Proceedings of the 2019 Federated Conference on Computer Science and Information Systems",
        )

    def test_volume_reconnu_a_sa_forme_quel_que_soit_l_ordre(self):
        facts = get_container_facts(
            {
                "type": "proceedings-article",
                "container-title": [
                    "Les journées de l'interdisciplinarité 2022",
                    "Les journées de l'interdisciplinarité",
                ],
                "ISSN": ["2300-5963"],
            }
        )
        assert (facts.collection_title, facts.book_title) == (
            "Les journées de l'interdisciplinarité",
            "Les journées de l'interdisciplinarité 2022",
        )

    def test_livre_titre_propre_et_collection(self):
        facts = get_container_facts(
            {
                "type": "book",
                "title": ["Ubiquitous Networking"],
                "container-title": ["Lecture Notes in Computer Science"],
                "ISBN": ["9783030580803", "9783030580810"],
                "isbn-type": [{"type": "electronic", "value": "9783030580810"}],
            }
        )
        assert facts.document_title == "Ubiquitous Networking"
        assert facts.collection_title == "Lecture Notes in Computer Science"
        assert (facts.isbns, facts.eisbns) == (("9783030580803",), ("9783030580810",))


class TestAuteursIllisibles:
    def test_auteur_qui_n_est_pas_un_objet(self):
        recs = build_crossref_author_records({"author": ["Dupont, J.", {"family": "Roe"}]})

        assert [r.name.display() for r in recs] == ["Roe"]

    def test_auteur_sans_nom_ignore(self):
        recs = build_crossref_author_records({"author": [{"ORCID": "x"}, {"family": "Roe"}]})

        assert [r.name.display() for r in recs] == ["Roe"]


def _message(**surcharges) -> dict:
    """Renvoie un payload Crossref minimal et acceptable, dégradé par chaque test selon ses besoins."""
    return {
        "DOI": "10.1000/abc",
        "title": ["Un article"],
        "issued": {"date-parts": [[2024, 3, 15]]},
        "type": "journal-article",
        "author": [{"given": "Jean", "family": "Dupont"}],
        **surcharges,
    }


def _normalizer() -> CrossrefNormalizer:
    return CrossrefNormalizer(
        conn=MagicMock(),
        logger=MagicMock(),
        staging_store=MagicMock(),
        record_store=MagicMock(),
        container_stores=MagicMock(),
        publisher_store=MagicMock(),
        contribution_store=MagicMock(),
        location_store=MagicMock(),
        embargo_store=MagicMock(),
    )


class TestCrossrefSourceRecord:
    def test_champs_du_document(self):
        document = crossref_source_record(_message(), 42, Containers(None, None))

        assert document.source == "crossref"
        assert document.source_id == "10.1000/abc"
        assert document.staging_id == 42
        assert "10.1000/abc" in identifier_values(document)["doi"]
        assert document.publication_year == 2024
        assert document.raw_doc_type == "journal-article"

    def test_titre_de_conteneur_garde_sans_revue(self):
        msg = _message(**{"container-title": ["J. Things"]})

        document = crossref_source_record(msg, 42, Containers(None, 9))

        assert (document.serial_id, document.monograph_id) == (None, 9)
        assert document.container_title == "J. Things"

    def test_titre_de_conteneur_porte_par_la_revue(self):
        msg = _message(**{"container-title": ["J. Things"]})

        document = crossref_source_record(msg, 42, Containers(7, None))

        assert document.serial_id == 7
        assert document.container_title is None


class TestCrossrefNormalizer:
    def test_parse_rend_le_message(self):
        msg = _message()

        assert _normalizer().parse(staging_row(raw=msg)) is msg

    def test_parse_refuse_sans_doi(self):
        msg = {"title": ["T"], "issued": {"date-parts": [[2024]]}}

        assert _normalizer().parse(staging_row(raw=msg)) is None

    def test_editeur_nomme(self):
        assert _normalizer().publisher({"publisher": " Elsevier "}) == PublisherFacts("Elsevier")

    def test_sans_editeur_nomme(self):
        assert _normalizer().publisher({}) is None
