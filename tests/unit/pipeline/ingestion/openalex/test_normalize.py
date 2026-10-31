"""Tests unitaires de `pipeline.ingestion.openalex.normalize`.

Couvre les fonctions de lecture d'un work OpenAlex, la lecture des auteurs et les méthodes de `OpenalexNormalizer`. Les stores du normaliseur sont des doublures, sans base de données.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from domain.persons.contributor_name import ContributorName
from domain.platforms.platform import PlatformType
from domain.publications.licenses import License
from domain.serials.issns import SerialIssn
from domain.source_records.identifiers import normalize_identifiers
from pipeline.ingestion.common.locations import LocationFacts, PlatformFacts
from pipeline.ingestion.common.normalizer import PublisherFacts
from pipeline.ingestion.common.source_records import SourceRecordUpsert
from pipeline.ingestion.openalex.normalize import (
    OpenalexNormalizer,
    _extract_openalex_orcid,
    build_openalex_author_records,
    extract_impact,
    extract_locations_data,
    extract_topics,
    get_container_facts,
    get_locations,
    get_publisher,
    openalex_source_record,
    reconstruct_abstract,
)
from pipeline.transformation.publishing.find_or_create import Containers
from tests.helpers.normalize_doubles import (
    FakeSourceRecordStore,
    FakeStagingStore,
    identifier_values,
    staging_row,
)

# ── extract_locations_data ───────────────────────────────────────


def _location_ids(work, id_type):
    _, identifiers = extract_locations_data(work)
    kept, _ = normalize_identifiers(identifiers)
    return [i.value for i in kept if i.id_type == id_type]


class TestExtractLocationsData:
    def test_empty_locations(self):
        assert extract_locations_data({}) == ([], [])

    def test_dedup_urls(self):
        work = {
            "locations": [
                {"landing_page_url": "https://a.com/x", "pdf_url": "https://a.com/x.pdf"},
                {"landing_page_url": "https://a.com/x", "pdf_url": "https://a.com/x.pdf"},
            ]
        }
        urls, _ = extract_locations_data(work)
        assert urls == ["https://a.com/x", "https://a.com/x.pdf"]

    def test_skips_falsy_urls(self):
        work = {"locations": [{"landing_page_url": None, "pdf_url": "https://b.com"}]}
        urls, _ = extract_locations_data(work)
        assert urls == ["https://b.com"]

    def test_collects_all_location_dois(self):
        """Les DOI sont collectés dans les URL doi.org et les location.id `doi:`."""
        work = {
            "locations": [
                {"landing_page_url": "https://doi.org/10.1/a", "id": "doi:10.1/a"},
                {"landing_page_url": "https://doi.org/10.2/b"},
                {"id": "doi:10.3/c"},
            ]
        }
        assert _location_ids(work, "doi") == ["10.1/a", "10.2/b", "10.3/c"]

    def test_collects_hal_ids_from_urls_and_location_id(self):
        """Les hal_id sont collectés dans les URL et les location.id OAI-PMH, y compris quand seule la location.id contient le hal_id."""
        work = {
            "locations": [
                {"landing_page_url": "https://doi.org/10.1/x", "id": "doi:10.1/x"},
                {
                    "landing_page_url": "https://hal.science/hal-04000111",
                    "id": "pmh:oai:HAL:hal-04000111v1",
                },
                {"landing_page_url": None, "id": "pmh:oai:HAL:hal-04000222v1"},
            ]
        }
        assert _location_ids(work, "hal_id") == ["hal-04000111", "hal-04000222"]

    def test_no_hal_id(self):
        work = {"locations": [{"landing_page_url": "https://doi.org/10.1/x", "id": "doi:10.1/x"}]}
        assert _location_ids(work, "hal_id") == []


class TestOpenalexIdentifiers:
    def test_doi_du_work_derive_quand_la_localisation_principale_le_donne(self):
        work = {
            "doi": "https://doi.org/10.1/x",
            "primary_location": {"landing_page_url": "https://doi.org/10.1/x"},
            "locations": [{"landing_page_url": "https://doi.org/10.1/x"}],
        }
        record = openalex_source_record(work, 1, Containers(False, None))
        kept, _ = normalize_identifiers(record.identifiers)
        assert [(str(i.id_type), i.value, str(i.role)) for i in kept] == [
            ("doi", "10.1/x", "derived")
        ]

    def test_doi_du_work_secondaire_sous_une_localisation_principale_hal(self):
        work = {
            "doi": "https://doi.org/10.1/x",
            "primary_location": {"landing_page_url": "https://hal.science/hal-04000111"},
            "locations": [
                {"landing_page_url": "https://hal.science/hal-04000111"},
                {"landing_page_url": "https://doi.org/10.1/x"},
            ],
        }
        record = openalex_source_record(work, 1, Containers(False, None))
        kept, _ = normalize_identifiers(record.identifiers)
        assert {(str(i.id_type), i.value, str(i.role)) for i in kept} == {
            ("doi", "10.1/x", "secondary"),
            ("hal_id", "hal-04000111", "derived"),
        }


# ── get_locations ────────────────────────────────────────────────


class TestGetLocations:
    def test_un_serveur_de_preprints_de_la_liste_prend_son_type(self):
        work = {
            "locations": [
                {
                    "landing_page_url": "https://arxiv.org/abs/2103.11769",
                    "source": {
                        "id": "https://openalex.org/S4306400194",
                        "type": "repository",
                        "display_name": "arXiv (Cornell University)",
                    },
                }
            ]
        }
        [location] = get_locations(work)
        assert location.platform is not None
        assert (location.platform.name, location.platform.platform_type) == (
            "arXiv",
            PlatformType.PREPRINT_SERVER,
        )

    def test_un_entrepot_donne_sa_plateforme_et_son_identifiant_oai(self):
        work = {
            "locations": [
                {
                    "id": "pmh:oai:HAL:hal-03608693v1",
                    "landing_page_url": "https://hal.science/hal-03608693",
                    "pdf_url": "https://hal.science/hal-03608693/document",
                    "version": "submittedVersion",
                    "license": "cc-by",
                    "is_oa": True,
                    "source": {
                        "id": "https://openalex.org/S4306402512",
                        "type": "repository",
                        "display_name": "HAL (Le Centre pour la Communication Scientifique Directe)",
                    },
                }
            ]
        }
        assert get_locations(work) == [
            LocationFacts(
                url="https://hal.science/hal-03608693",
                pdf_url="https://hal.science/hal-03608693/document",
                oai_id="oai:HAL:hal-03608693v1",
                version="submittedVersion",
                license=License.CC_BY,
                is_oa=True,
                platform=PlatformFacts("S4306402512", "HAL", PlatformType.REPOSITORY),
            )
        ]

    def test_une_page_pubmed_rangee_sous_pmc_devient_la_page_pmc(self):
        source = {
            "id": "https://openalex.org/S2764455111",
            "type": "repository",
            "display_name": "PubMed Central",
        }
        work = {
            "locations": [
                {
                    "landing_page_url": "https://pubmed.ncbi.nlm.nih.gov/41760695/",
                    "pdf_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12988236/pdf/a.pdf",
                    "source": source,
                },
                {"landing_page_url": "https://pubmed.ncbi.nlm.nih.gov/1/", "source": source},
            ]
        }
        with_pdf, without_pdf = get_locations(work)
        assert with_pdf.url == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12988236/"
        assert without_pdf.url == "https://pubmed.ncbi.nlm.nih.gov/1/"

    def test_une_revue_ne_donne_pas_de_plateforme(self):
        work = {
            "locations": [
                {
                    "id": "doi:10.1038/x",
                    "landing_page_url": "https://doi.org/10.1038/x",
                    "source": {"id": "https://openalex.org/S1", "type": "journal"},
                }
            ]
        }
        [location] = get_locations(work)
        assert (location.platform, location.oai_id) == (None, None)

    def test_localisation_sans_url_ecartee(self):
        work = {
            "locations": [
                {"landing_page_url": None, "pdf_url": None},
                {"landing_page_url": None, "pdf_url": "https://arxiv.org/pdf/2103.11769"},
            ]
        }
        assert [loc.url for loc in get_locations(work)] == ["https://arxiv.org/pdf/2103.11769"]


# ── reconstruct_abstract ─────────────────────────────────────────


class TestReconstructAbstract:
    def test_none_input(self):
        assert reconstruct_abstract(None) is None

    def test_empty_dict(self):
        assert reconstruct_abstract({}) is None

    def test_simple_reconstruction(self):
        # "Hello world" : positions 0 et 1
        inverted = {"Hello": [0], "world": [1]}
        assert reconstruct_abstract(inverted) == "Hello world"

    def test_multiple_occurrences(self):
        # "the cat the dog" : 'the' aux positions 0 et 2
        inverted = {"the": [0, 2], "cat": [1], "dog": [3]}
        assert reconstruct_abstract(inverted) == "the cat the dog"

    def test_inverted_index_with_no_positions(self):
        """Un inverted index aux positions vides donne None."""
        assert reconstruct_abstract({"word": []}) is None


# ── extract_topics ───────────────────────────────────────────────


class TestExtractTopics:
    def test_none_topics(self):
        assert extract_topics({}) is None

    def test_empty_topics(self):
        assert extract_topics({"topics": []}) is None

    def test_basic_topic(self):
        work = {
            "topics": [
                {
                    "display_name": "Theory of Computation",
                    "domain": {"display_name": "Computer Science"},
                    "field": {"display_name": "Algorithms"},
                    "subfield": {"display_name": "Complexity"},
                    "score": 0.8,
                }
            ]
        }
        topics = extract_topics(work)
        assert topics is not None
        assert topics[0]["domain"] == "Computer Science"
        assert topics[0]["field"] == "Algorithms"
        assert topics[0]["subfield"] == "Complexity"
        assert topics[0]["topic"] == "Theory of Computation"
        assert topics[0]["score"] == 0.8

    def test_topic_no_score(self):
        work = {"topics": [{"display_name": "Math"}]}
        topics = extract_topics(work)
        assert topics is not None
        assert "score" not in topics[0]

    def test_topic_with_no_displayable_fields(self):
        """Un topic sans champ exploitable est écarté."""
        work = {"topics": [{"foo": "bar"}]}  # ni domain, ni field, ni subfield, ni display_name
        assert extract_topics(work) is None


# ── extract_impact ───────────────────────────────────────────────


class TestExtractImpact:
    def test_indicateurs_de_citation(self):
        work = {
            "cited_by_count": 21,
            "fwci": 1.5035,
            "citation_normalized_percentile": {
                "value": 0.7717646,
                "is_in_top_1_percent": False,
                "is_in_top_10_percent": False,
            },
        }
        assert extract_impact(work).to_json() == {
            "cited_by_count": 21,
            "fwci": 1.5035,
            "citation_percentile": 0.7717646,
            "top_10_percent": False,
            "top_1_percent": False,
        }

    def test_indicateurs_nuls_omis(self):
        work = {"cited_by_count": 0, "fwci": None, "citation_normalized_percentile": None}
        assert extract_impact(work).to_json() == {"cited_by_count": 0}


# ── _extract_openalex_orcid ──────────────────────────────────────


class TestExtractOpenalexOrcid:
    def test_empty_authorship(self):
        assert _extract_openalex_orcid({}) is None

    def test_raw_orcid_present(self):
        result = _extract_openalex_orcid({"raw_orcid": "https://orcid.org/0000-0001-2345-6789"})
        assert result == "https://orcid.org/0000-0001-2345-6789"

    def test_author_orcid_ignored(self):
        """Seul `raw_orcid` est lu : `author.orcid`, qui vient de l'auteur désambiguïsé par OpenAlex, est ignoré."""
        assert _extract_openalex_orcid({"author": {"orcid": "0000-0001-2345-6789"}}) is None

    def test_no_raw_orcid(self):
        assert _extract_openalex_orcid({"raw_orcid": None}) is None


# ── get_publisher ────────────────────────────────────────────────


class TestGetPublisher:
    def test_no_publisher_name(self):
        assert get_publisher({}) is None

    def test_happy_path(self):
        work = {
            "primary_location": {
                "source": {
                    "host_organization_name": "Elsevier",
                    "host_organization": "https://openalex.org/P1",
                }
            }
        }
        assert get_publisher(work) == PublisherFacts("Elsevier", "P1")

    def test_no_host_organization_id(self):
        """Sans `host_organization`, l'éditeur est sans identifiant OpenAlex."""
        work = {"primary_location": {"source": {"host_organization_name": "X"}}}
        assert get_publisher(work) == PublisherFacts("X", None)


# ── conteneurs (branches issn/eissn/oa_model) ───────────────────


class TestContainerDescription:
    def test_repository_source_sans_modele_oa(self):
        work = {
            "primary_location": {
                "source": {
                    "display_name": "Repo",
                    "id": "https://openalex.org/S1",
                    "type": "repository",
                }
            }
        }
        facts = get_container_facts(work)
        assert facts.oa_model is None
        assert facts.openalex_id == "S1"

    def test_serial_full_oa(self):
        work = {
            "primary_location": {"source": {"display_name": "OA", "type": "journal", "is_oa": True}}
        }
        assert get_container_facts(work).oa_model == "full_oa"

    def test_serial_subscription(self):
        work = {"primary_location": {"source": {"display_name": "Sub", "type": "journal"}}}
        assert get_container_facts(work).oa_model == "subscription"

    def test_issns_sans_support_et_issnl(self):
        """OpenAlex ne donne pas le support de ses ISSN : ils restent de support inconnu ; `issn_l` a le drapeau ISSN-L."""
        work = {
            "primary_location": {
                "source": {
                    "display_name": "J",
                    "issn_l": "1111-1119",
                    "issn": ["1111-1119", "2222-2227", "3333-3335"],
                }
            }
        }
        facts = get_container_facts(work)
        assert facts.issns == (
            SerialIssn(issn="1111-1119", linking=True),
            SerialIssn(issn="2222-2227"),
            SerialIssn(issn="3333-3335"),
        )

    def test_collection_d_un_chapitre(self):
        work = {
            "type": "book-chapter",
            "primary_location": {
                "source": {
                    "display_name": "Lecture notes in computer science",
                    "type": "book series",
                }
            },
        }
        facts = get_container_facts(work)
        assert facts.collection_title == "Lecture notes in computer science"
        assert facts.book_title is None

    def test_congres_volume_d_actes(self):
        work = {
            "type": "article",
            "primary_location": {"source": {"display_name": "2021 ICCAS", "type": "conference"}},
        }
        facts = get_container_facts(work)
        assert (facts.book_title, facts.collection_title) == ("2021 ICCAS", None)


# ── openalex_source_record (métadonnées canoniques) ──────────────

_NO_CONTAINERS = Containers(has_series=False, monograph_id=None)


class TestOpenalexSourceRecordMetadata:
    def test_minimal_work(self):
        record = openalex_source_record(
            {"title": "T", "publication_year": 2024}, staging_id=1, containers=_NO_CONTAINERS
        )
        assert record.title == "T"
        assert record.publication_year == 2024
        assert "doi" not in identifier_values(record)
        assert "nnt" not in identifier_values(record)

    def test_display_name_fallback(self):
        record = openalex_source_record(
            {"display_name": "DN"}, staging_id=1, containers=_NO_CONTAINERS
        )
        assert record.title == "DN"

    def test_with_series_no_container_title(self):
        """Une série décrite laisse `container_title` à None."""
        work = {
            "title": "T",
            "primary_location": {"source": {"display_name": "Some Source"}},
        }
        record = openalex_source_record(
            work, staging_id=1, containers=Containers(has_series=True, monograph_id=None)
        )
        assert record.container_title is None

    def test_conteneur_sans_revue(self):
        """Une source de congrès sans revue identifiée donne le titre du conteneur ; une archive non."""
        conference = {"display_name": "ICRA 2024", "type": "conference"}
        archive = {
            "display_name": "Zenodo (CERN European Organization for Nuclear Research)",
            "type": "repository",
        }
        titles = [
            openalex_source_record(
                {"title": "T", "primary_location": {"source": source}},
                staging_id=1,
                containers=_NO_CONTAINERS,
            ).container_title
            for source in (conference, archive)
        ]
        assert titles == ["ICRA 2024", None]


# ── openalex_source_record (cas limites) ─────────────────────────


class TestOpenalexSourceRecord:
    def _call(self, work: dict) -> SourceRecordUpsert:
        return openalex_source_record(work, staging_id=1, containers=_NO_CONTAINERS)

    def test_keywords_list_of_strings(self):
        work = {"id": "https://openalex.org/W1", "keywords": ["a", "b"]}
        captured = self._call(work)
        assert captured.keywords == ["a", "b"]

    def test_keywords_list_of_dicts(self):
        work = {
            "id": "https://openalex.org/W1",
            "keywords": [{"keyword": "kw1"}, {"keyword": "kw2"}],
        }
        captured = self._call(work)
        assert captured.keywords == ["kw1", "kw2"]

    def test_keywords_not_a_list(self):
        work = {"id": "https://openalex.org/W1", "keywords": "scalar"}
        captured = self._call(work)
        assert captured.keywords is None

    def test_biblio_extracted(self):
        work = {
            "id": "https://openalex.org/W1",
            "biblio": {"volume": "10", "issue": "2", "first_page": "100", "last_page": "120"},
        }
        captured = self._call(work)
        assert captured.biblio == {
            "volume": "10",
            "issue": "2",
            "first_page": "100",
            "last_page": "120",
        }

    def test_biblio_partial_drops_empty_keys(self):
        work = {"id": "https://openalex.org/W1", "biblio": {"volume": "10"}}
        captured = self._call(work)
        assert captured.biblio == {"volume": "10"}

    def test_biblio_empty_is_none(self):
        captured = self._call({"id": "https://openalex.org/W1", "biblio": {}})
        assert captured.biblio is None

    def test_dois_of_the_work_and_its_locations(self):
        work = {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1/primary",
            "locations": [
                {"landing_page_url": "https://doi.org/10.1/primary"},
                {"id": "doi:10.2/preprint"},
            ],
        }
        captured = self._call(work)
        assert identifier_values(captured)["doi"] == ["10.1/primary", "10.2/preprint"]

    def test_doi_written_once_when_the_location_repeats_it(self):
        work = {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1/primary",
            "locations": [{"landing_page_url": "https://doi.org/10.1/primary"}],
        }
        captured = self._call(work)
        assert identifier_values(captured)["doi"] == ["10.1/primary"]

    def test_biblio_publisher_from_primary_location(self):
        work = {
            "id": "https://openalex.org/W1",
            "primary_location": {
                "source": {
                    "host_organization_name": "Elsevier",
                    "display_name": "Journal of Physics",
                    "id": "https://openalex.org/S123",
                    "issn": ["0022-3727", "1361-6463"],
                    "issn_l": "0022-3727",
                }
            },
        }
        captured = self._call(work)
        assert captured.biblio == {"publisher": "Elsevier"}

    def test_biblio_skipped_when_primary_is_repository(self):
        """Un entrepôt héberge le work sans le publier : ni éditeur ni revue dans biblio."""
        work = {
            "id": "https://openalex.org/W1",
            "primary_location": {
                "source": {
                    "type": "repository",
                    "display_name": "Zenodo",
                    "host_organization_name": "CERN",
                }
            },
        }
        captured = self._call(work)
        assert captured.biblio is None

    def test_ebook_platform_names_publisher_only(self):
        """Une plateforme d'ebooks donne l'éditeur, pas la revue."""
        work = {
            "id": "https://openalex.org/W1",
            "primary_location": {
                "source": {
                    "id": "https://openalex.org/S4306463240",
                    "type": "ebook platform",
                    "display_name": "ENS Éditions eBooks",
                    "host_organization_name": "École normale supérieure Editions",
                }
            },
        }
        captured = self._call(work)
        assert captured.biblio == {"publisher": "École normale supérieure Editions"}

    def test_theses_fr_nnt_passed_through_to_identifiers(self):
        """Le NNT d'une localisation principale theses.fr figure parmi les identifiants."""
        work = {
            "id": "https://openalex.org/W1",
            "primary_location": {"id": "pmh:2024CLFAC001", "source": {"display_name": "theses.fr"}},
        }
        captured = self._call(work)
        assert identifier_values(captured)
        assert identifier_values(captured)["nnt"] == ["2024CLFAC001"]


# ── build_openalex_author_records ──────────────────


class TestBuildOpenalexAuthorRecords:
    def test_no_authorships(self):
        assert build_openalex_author_records({"authorships": []}) == []

    def test_shared_orcid_kept_on_each_record(self):
        """La lecture renvoie l'ORCID de chaque contribution source tel que la source le donne. L'écriture des contributions sources neutralise les ORCID partagés par plusieurs contributions sources."""
        work = {
            "authorships": [
                {
                    "raw_author_name": "S. Acharya",
                    "raw_orcid": "https://orcid.org/0000-0001-2345-6789",
                },
                {"raw_author_name": "S. Das", "raw_orcid": "https://orcid.org/0000-0001-2345-6789"},
            ]
        }
        recs = build_openalex_author_records(work)
        assert [r.identifiers for r in recs] == [
            {"orcid": "0000-0001-2345-6789"},
            {"orcid": "0000-0001-2345-6789"},
        ]

    def test_skip_without_raw_name(self):
        # Une authorship sans raw_author_name est ignorée.
        records = build_openalex_author_records(
            {"authorships": [{"author": {"display_name": "X"}}]}
        )
        assert records == []

    def test_orcid_corresponding_and_roles(self):
        work = {
            "authorships": [
                {
                    "raw_author_name": "DUPONT Marie",
                    "raw_orcid": "https://orcid.org/0000-0001-2345-6789",
                    # author.orcid divergent, ignoré : seul raw_orcid est lu.
                    "author": {"orcid": "https://orcid.org/9999-9999-9999-9999"},
                    "is_corresponding": True,
                    "raw_affiliation_strings": ["Univ Clermont"],
                    "institutions": [],
                }
            ]
        }
        rec = build_openalex_author_records(work)[0]
        assert rec.name == ContributorName(raw="DUPONT Marie")
        assert rec.is_corresponding is True
        # Le rôle par défaut est `author`.
        assert rec.roles == ["author"]
        assert rec.identifiers == {"orcid": "0000-0001-2345-6789"}
        assert [a.text for a in rec.addresses] == ["Univ Clermont"]

    def test_no_addr_without_affiliation_string(self):
        """Sans texte d'affiliation, la contribution source n'a pas d'adresse, même avec des institutions."""
        work = {
            "authorships": [
                {
                    "raw_author_name": "X",
                    "institutions": [{"id": "https://openalex.org/I1", "display_name": "Inst One"}],
                }
            ]
        }
        assert build_openalex_author_records(work)[0].addresses == []

    def test_no_addr_when_no_affiliation(self):
        work = {"authorships": [{"raw_author_name": "X", "institutions": []}]}
        assert build_openalex_author_records(work)[0].addresses == []

    def test_country_code_des_institutions_de_l_affiliation(self):
        """Les `country_code` des institutions de l'affiliation donnent les pays de son adresse, dédupliqués et en minuscules comme `countries.code`."""
        work = {
            "authorships": [
                {
                    "raw_author_name": "X",
                    "raw_affiliation_strings": ["Some affiliation"],
                    "affiliations": [
                        {
                            "raw_affiliation_string": "Some affiliation",
                            "institution_ids": [
                                "https://openalex.org/I1",
                                "https://openalex.org/I2",
                            ],
                        }
                    ],
                    "institutions": [
                        {
                            "id": "https://openalex.org/I1",
                            "display_name": "A",
                            "country_code": "FR",
                        },
                        {
                            "id": "https://openalex.org/I2",
                            "display_name": "B",
                            "country_code": "us",
                        },
                    ],
                }
            ]
        }
        assert build_openalex_author_records(work)[0].addresses[0].countries == ["fr", "us"]

    def test_each_address_gets_the_countries_of_its_own_affiliation(self):
        work = {
            "authorships": [
                {
                    "raw_author_name": "X",
                    "raw_affiliation_strings": ["Lab Paris", "Lab Boston"],
                    "affiliations": [
                        {
                            "raw_affiliation_string": "Lab Paris",
                            "institution_ids": ["https://openalex.org/I1"],
                        },
                        {
                            "raw_affiliation_string": "Lab Boston",
                            "institution_ids": ["https://openalex.org/I2"],
                        },
                    ],
                    "institutions": [
                        {
                            "id": "https://openalex.org/I1",
                            "display_name": "A",
                            "country_code": "FR",
                        },
                        {
                            "id": "https://openalex.org/I2",
                            "display_name": "B",
                            "country_code": "US",
                        },
                    ],
                }
            ]
        }
        addresses = build_openalex_author_records(work)[0].addresses
        assert [(a.text, a.countries) for a in addresses] == [
            ("Lab Paris", ["fr"]),
            ("Lab Boston", ["us"]),
        ]

    def test_no_country_code_no_country(self):
        work = {
            "authorships": [
                {
                    "raw_author_name": "X",
                    "raw_affiliation_strings": ["Some affiliation"],
                    "institutions": [{"id": "https://openalex.org/I1", "display_name": "A"}],
                }
            ]
        }
        assert build_openalex_author_records(work)[0].addresses[0].countries is None


# ── OpenalexNormalizer (classe) ──────────────────────────────────


def _make_normalizer():
    return OpenalexNormalizer(
        conn=MagicMock(),
        logger=logging.getLogger("test"),
        staging_store=FakeStagingStore(),
        record_store=FakeSourceRecordStore(),
        monograph_store=MagicMock(),
        publisher_store=MagicMock(),
        contribution_store=MagicMock(),
        location_store=MagicMock(),
        embargo_store=MagicMock(),
    )


class TestOpenalexNormalizerClass:
    def test_metadonnees_minimales_d_un_work_sans_annee(self):
        """OpenAlex renvoie W3131333980 sans DOI ni année ; les métadonnées minimales donnent son titre et une année vide."""
        work = {"title": "Inequality of Opportunity, Inequality of Income and Economic Growth"}
        assert _make_normalizer().minimal_metadata(staging_row(raw=work)) == (work["title"], None)

    def test_editeur_et_conteneur_d_une_revue(self):
        work = {
            "primary_location": {
                "source": {
                    "display_name": "Journal of Physics",
                    "type": "journal",
                    "host_organization_name": "Elsevier",
                }
            }
        }
        norm = _make_normalizer()
        assert norm.publisher(work) == PublisherFacts("Elsevier", None)
        container = norm.container_facts(work)
        assert container is not None
        assert container.journal_title == "Journal of Physics"

    def test_plateforme_sans_editeur_ni_conteneur(self):
        """Une localisation principale de type `repository` ne désigne ni éditeur ni conteneur."""
        work = {
            "primary_location": {
                "source": {
                    "display_name": "Zenodo",
                    "type": "repository",
                    "host_organization_name": "CERN",
                }
            }
        }
        norm = _make_normalizer()
        assert norm.publisher(work) is None
        assert norm.container_facts(work) is None
