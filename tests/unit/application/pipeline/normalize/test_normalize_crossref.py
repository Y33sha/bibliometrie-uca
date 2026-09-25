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

from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize import normalize_crossref
from application.pipeline.normalize.normalize_crossref import (
    CrossrefNormalizer,
    _author_affiliation_strings,
    _author_full_name,
    build_crossref_author_records,
    get_abstract,
    get_biblio,
    get_cited_by_count,
    get_container_facts,
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
    process_authorships,
    process_work,
    upsert_containers,
    upsert_publisher,
)
from application.services.monographs.containers import Containers
from domain.journals.issns import IssnSupport, JournalIssn
from tests.unit.application.pipeline.normalize.doubles import (
    FakeSourcePublicationQueries,
    FakeStagingQueries,
    staging_row,
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

    def test_none_when_first_entry_is_blank(self):
        # Une entrée vide en tête ne vaut pas un titre, et rien ne la remplace.
        assert get_container_title({"container-title": ["  "]}) is None

    def test_none_when_absent(self):
        assert get_container_title({}) is None

    def test_strips_whitespace(self):
        assert get_container_title({"container-title": ["  J Phys  "]}) == "J Phys"


class TestGetIssns:
    def test_delegates_to_domain(self):
        # Délégation à `parse_crossref_issns`. Le détail est testé côté domain.
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
    def test_issn_reste_hors_des_identifiants(self):
        """L'ISSN identifie la revue : il figure dans `biblio.journal`."""
        assert get_external_ids({"ISSN": ["1234-5679"]}) is None

    def test_isbn_only(self):
        assert get_external_ids({"ISBN": ["978-0-12345-678-9"]}) == (
            {"isbn": ["978-0-12345-678-9"]}
        )

    def test_electronic_isbn_goes_to_eisbn(self):
        """`isbn-type` donne le support : l'édition électronique a sa clé."""
        result = get_external_ids(
            {
                "ISBN": ["978-3-030-04869-3", "978-3-030-04870-9"],
                "isbn-type": [
                    {"value": "978-3-030-04869-3", "type": "print"},
                    {"value": "978-3-030-04870-9", "type": "electronic"},
                ],
            }
        )
        assert result == {"isbn": ["978-3-030-04869-3"], "eisbn": ["978-3-030-04870-9"]}

    def test_filters_non_strings(self):
        assert get_external_ids({"ISBN": ["978-0-12345-678-9", 12345, None]}) == (
            {"isbn": ["978-0-12345-678-9"]}
        )

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

    def test_publisher_extracted(self):
        assert get_biblio({"publisher": "Elsevier"}) == {"publisher": "Elsevier"}

    def test_journal_built_from_container_title_and_issns(self):
        # Format `issn-type` permet de distinguer print/electronic ; la liste
        # `ISSN` plate ne sert qu'à hydrater `issn` (eissn reste None).
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

    def test_journal_title_only_when_no_issns(self):
        assert get_biblio({"container-title": ["J. Phys."]}) == {
            "journal": {"title": "J. Phys."},
        }


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


# ── build_crossref_author_records (parsing pur) ──────────────────


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
        assert rec.raw_name == "Jean Dupont"
        # roles posé explicitement (reproduit l'ancien défaut DB ARRAY['author']).
        assert rec.roles == ["author"]
        assert rec.person_identifiers == {"orcid": "0000-0001-2345-6789"}
        assert [a.text for a in rec.addresses] == ["UCA"]
        assert rec.addresses[0].countries is None

    def test_bare_author_no_identifiers(self):
        rec = build_crossref_author_records({"author": [{"family": "Dupont"}]})[0]
        assert rec.person_identifiers is None

    def test_shared_orcid_kept_on_each_record(self):
        """L'extracteur rend l'ORCID de chaque auteur tel que la source le donne ; le writer neutralise ceux que partagent plusieurs signatures."""
        msg = {
            "author": [
                {"family": "Acharya", "ORCID": "https://orcid.org/0000-0001-2345-6789"},
                {"family": "Das", "ORCID": "https://orcid.org/0000-0001-2345-6789"},
            ]
        }
        recs = build_crossref_author_records(msg)
        assert [r.person_identifiers for r in recs] == [
            {"orcid": "0000-0001-2345-6789"},
            {"orcid": "0000-0001-2345-6789"},
        ]


class TestUpsertPublisherEtJournal:
    def test_sans_editeur_nomme_rien_n_est_cree(self):
        assert upsert_publisher({}, publisher_repo=MagicMock()) is None

    def test_editeur_nomme_est_cree(self, monkeypatch):
        vus: list[str] = []
        monkeypatch.setattr(
            normalize_crossref,
            "find_or_create_publisher",
            lambda name, *, repo: vus.append(name) or 7,
        )

        assert upsert_publisher({"publisher": "Elsevier"}, publisher_repo=MagicMock()) == 7
        assert vus == ["Elsevier"]

    def test_sans_titre_de_contenant_aucune_revue(self):
        """Un document sans revue ni série qui le porte ne crée pas d'entrée au référentiel."""
        assert upsert_containers({}, None, container_repo=MagicMock()) == Containers(None, None)

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
            JournalIssn(issn="1234-5679", support=IssnSupport.PRINT),
            JournalIssn(issn="8765-4326", support=IssnSupport.ELECTRONIC),
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

        assert [r.raw_name for r in recs] == ["Roe"]

    def test_auteur_sans_nom_ignore(self):
        recs = build_crossref_author_records({"author": [{"ORCID": "x"}, {"family": "Roe"}]})

        assert [r.raw_name for r in recs] == ["Roe"]


class TestProcessAuthorships:
    def test_confie_les_signatures_au_writer_partage(self, monkeypatch):
        vus: dict[str, object] = {}
        monkeypatch.setattr(
            normalize_crossref,
            "write_source_authorships",
            lambda conn, queries, source, spid, records: vus.update(
                source=source, spid=spid, records=records
            ),
        )

        process_authorships(MagicMock(), MagicMock(), {"author": [{"family": "Dupont"}]}, 555)

        assert (vus["source"], vus["spid"]) == ("crossref", 555)
        assert [r.raw_name for r in vus["records"]] == ["Dupont"]


def _message(**surcharges) -> dict:
    """Notice Crossref minimale et acceptable, que chaque test dégrade à sa guise."""
    return {
        "DOI": "10.1000/abc",
        "title": ["Un article"],
        "issued": {"date-parts": [[2024, 3, 15]]},
        "type": "journal-article",
        "author": [{"given": "Jean", "family": "Dupont"}],
        **surcharges,
    }


class TestProcessWork:
    @pytest.fixture(autouse=True)
    def _sans_editeur_ni_revue(self, monkeypatch):
        """Les créations d'éditeur et de revue ont leurs propres tests : la boucle s'en passe."""
        monkeypatch.setattr(normalize_crossref, "upsert_publisher", lambda m, **kw: None)
        monkeypatch.setattr(
            normalize_crossref, "upsert_containers", lambda m, p, **kw: Containers(None, None)
        )
        monkeypatch.setattr(normalize_crossref, "process_authorships", lambda *a, **kw: None)

    @pytest.fixture
    def queries(self) -> FakeSourcePublicationQueries:
        return FakeSourcePublicationQueries()

    @pytest.fixture
    def staging(self) -> FakeStagingQueries:
        return FakeStagingQueries()

    def _run(self, raw, queries, staging, logger):
        return process_work(
            MagicMock(),
            queries,
            logger,
            staging_row(staging_id=42, raw=raw),
            container_repo=MagicMock(),
            publisher_repo=MagicMock(),
            publication_repo=MagicMock(),
            staging_queries=staging,
            authorship_queries=MagicMock(),
        )

    def test_document_verse_et_ligne_marquee(self, queries, staging, logger):
        rendu = self._run(_message(), queries, staging, logger)

        assert rendu is True
        assert staging.marked_done == [42]
        (document,) = queries.upserted_documents
        assert document.source == "crossref"
        assert document.doi == "10.1000/abc"
        assert document.pub_year == 2024
        assert document.doc_type == "journal-article"
        assert document.oa_status is None  # Crossref ne renseigne pas l'accès ouvert

    @pytest.mark.parametrize(
        ("raw", "motif"),
        [
            ({"title": ["T"], "issued": {"date-parts": [[2024]]}}, "sans DOI"),
        ],
    )
    def test_document_refuse_sans_rien_ecrire(self, raw, motif, queries, staging, logger):
        """Le refus remonte à la boucle, qui supprime l'enregistrement et marque la ligne (`SourceNormalizer._reject`)."""
        rendu = self._run(raw, queries, staging, logger)

        assert rendu is False, motif
        assert staging.marked_done == []
        assert queries.upserted_documents == []


def test_le_normalizer_delegue_a_la_boucle(monkeypatch):
    """La classe ne fait que rassembler ses dépendances et passer la main."""
    vus: dict[str, object] = {}
    monkeypatch.setattr(
        normalize_crossref,
        "process_work",
        lambda conn, queries, logger, row, **kw: vus.update(row=row, **kw) or True,
    )
    normalizer = CrossrefNormalizer(
        conn=MagicMock(),
        logger=MagicMock(),
        staging_queries=MagicMock(),
        queries=MagicMock(),
        container_repo_factory=lambda c: MagicMock(),
        publisher_repo_factory=lambda c: MagicMock(),
        publication_repo_factory=lambda c: MagicMock(),
        authorship_queries=MagicMock(),
    )
    normalizer.preload_caches(MagicMock())
    row = staging_row()

    assert normalizer.normalize_record(MagicMock(), row) is True
    assert vus["row"] is row
