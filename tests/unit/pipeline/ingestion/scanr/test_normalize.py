"""Tests unitaires de `pipeline.ingestion.scanr.normalize`.

Couvre l'enregistrement source construit par `scanr_source_record`, l'éditeur, le conteneur et la lecture des auteurs par `build_scanr_author_records` (ORCID et IdRef, rôles, adresses des affiliations et leurs pays). Fonctions pures et `MagicMock`, sans base de données.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from domain.persons.contributor_name import ContributorName
from domain.serials.issns import SerialIssn
from pipeline.ingestion.common.locations import LocationFacts
from pipeline.ingestion.common.normalizer import PublisherFacts
from pipeline.ingestion.common.source_records import SourceRecordUpsert
from pipeline.ingestion.scanr.normalize import (
    ScanrNormalizer,
    build_scanr_author_records,
    get_container_facts,
    get_locations,
    get_publisher,
    get_title,
    scanr_source_record,
)
from pipeline.transformation.publishing.find_or_create import Containers
from tests.helpers.normalize_doubles import identifier_values, staging_row

_NO_CONTAINERS = Containers(has_series=False, monograph_id=None)


class TestScanrSourceRecordLicense:
    """Seule la licence d'une localisation d'éditeur est normalisée ; celle d'une archive reste brute dans `meta`."""

    def _call(self, evidence: dict) -> SourceRecordUpsert:
        return scanr_source_record({"oaEvidence": evidence}, 1, "sc-1", _NO_CONTAINERS)

    def test_licence_de_l_editeur_normalisee(self):
        captured = self._call({"hostType": "publisher", "license": "cc-by"})
        assert captured.license == "cc-by"
        assert captured.source_extras == {"license": "cc-by"}

    def test_licence_d_archive_gardee_brute(self):
        authorisation = "https://about.hal.science/hal-authorisation-v1/"
        captured = self._call({"hostType": "repository", "license": authorisation})
        assert captured.license is None
        assert captured.source_extras == {"license": authorisation}


class TestScanrSourceRecordBiblio:
    def _call(self, doc) -> SourceRecordUpsert:
        return scanr_source_record(doc, staging_id=1, scanr_id="sc-1", containers=_NO_CONTAINERS)

    def test_biblio_none_when_no_source_fields(self):
        captured = self._call({})
        assert captured.biblio is None

    def test_biblio_publisher_only(self):
        captured = self._call({"source": {"publisher": "Elsevier"}})
        assert captured.biblio == {"publisher": "Elsevier"}


class TestScanrSourceRecordExternalIds:
    def _call(self, doc) -> SourceRecordUpsert:
        return scanr_source_record(doc, staging_id=1, scanr_id="sc-1", containers=_NO_CONTAINERS)

    def test_every_doi_of_the_external_ids(self):
        doc = {
            "externalIds": [
                {"type": "doi", "id": "10.1/primary"},
                {"type": "doi", "id": "10.2/anie"},
                {"type": "hal", "id": "hal-1"},
            ]
        }
        captured = self._call(doc)
        assert identifier_values(captured)["doi"] == ["10.1/primary", "10.2/anie"]


# ── build_scanr_author_records ─────────────────────


class TestBuildScanrAuthorRecords:
    def test_no_authors(self):
        assert build_scanr_author_records({}) == []

    def test_skip_without_full_name(self):
        assert build_scanr_author_records({"authors": [{"role": "author"}]}) == []

    def test_identifiers_and_role(self):
        doc = {
            "authors": [
                {
                    "fullName": "Marie Dupont",
                    "role": "author",
                    "denormalized": {
                        "orcid": "https://orcid.org/0000-0001-2345-6789",
                        "idref": "123456789",
                    },
                }
            ]
        }
        rec = build_scanr_author_records(doc)[0]
        assert rec.name == ContributorName(raw="Marie Dupont")
        assert rec.identifiers == {"orcid": "0000-0001-2345-6789", "idref": "123456789"}
        assert rec.roles == ["author"]

    def test_affiliation_becomes_address_with_detected_countries(self):
        doc = {
            "authors": [
                {
                    "fullName": "X",
                    "affiliations": [
                        {"name": "Lab A", "detected_countries": ["FR", "fr", "BE", "--"]}
                    ],
                }
            ]
        }
        rec = build_scanr_author_records(doc)[0]
        assert [a.text for a in rec.addresses] == ["Lab A"]
        # Les pays de l'adresse sont les pays d'autorité, en minuscules, dédupliqués et triés ; les pays suggérés sont ignorés.
        assert rec.addresses[0].countries == ["be", "fr"]

    def test_le_nom_de_l_affiliation_n_ecrase_pas_celui_de_l_auteur(self):
        doc = {"authors": [{"fullName": "Marie Dupont", "affiliations": [{"name": "Lab A"}]}]}
        assert build_scanr_author_records(doc)[0].name == ContributorName(raw="Marie Dupont")

    def test_une_personne_listee_pour_plusieurs_roles_forme_une_contribution_source(self):
        doc = {
            "authors": [
                {"fullName": "Anis Limami", "role": "author"},
                {
                    "fullName": "Paul Durand",
                    "role": "membrejury",
                    "affiliations": [{"name": "Lab A"}],
                },
                {"fullName": "Jean Martin", "role": "directeurthese"},
                {
                    "fullName": "Paul Durand",
                    "role": "rapporteur",
                    "affiliations": [{"name": "Lab B"}],
                },
            ]
        }
        records = build_scanr_author_records(doc)
        assert [(r.position, r.name.raw, r.roles) for r in records] == [
            (0, "Anis Limami", ["author"]),
            (1, "Paul Durand", ["rapporteur"]),
            (2, "Jean Martin", ["thesis_director"]),
        ]
        assert [a.text for a in records[1].addresses] == ["Lab A", "Lab B"]

    def test_un_nom_repete_avec_le_meme_role_ou_d_autres_identifiants_reste_a_part(self):
        doc = {
            "authors": [
                {"fullName": "Paul Durand", "role": "author"},
                {"fullName": "Paul Durand", "role": "author"},
                {
                    "fullName": "Paul Durand",
                    "role": "rapporteur",
                    "denormalized": {"idref": "123456789"},
                },
            ]
        }
        assert len(build_scanr_author_records(doc)) == 3

    def test_affiliation_sans_nom_ne_donne_pas_son_pays_aux_autres(self):
        """Une affiliation sans nom ne donne aucune adresse, et son pays reste hors des autres adresses."""
        doc = {
            "authors": [
                {
                    "fullName": "Marie Dupont",
                    "affiliations": [
                        {"name": "  ", "detected_countries": ["FR"]},
                        {"name": "Lab A", "detected_countries": ["BE"]},
                    ],
                }
            ]
        }

        rec = build_scanr_author_records(doc)[0]

        assert [a.text for a in rec.addresses] == ["Lab A"]
        assert rec.addresses[0].countries == ["be"]

    def test_chaque_adresse_garde_les_pays_de_son_affiliation(self):
        doc = {
            "authors": [
                {
                    "fullName": "Marie Dupont",
                    "affiliations": [
                        {"name": "Lab Paris", "detected_countries": ["fr"]},
                        {"name": "Lab Boston", "detected_countries": ["us"]},
                    ],
                }
            ]
        }

        rec = build_scanr_author_records(doc)[0]

        assert [(a.text, a.countries) for a in rec.addresses] == [
            ("Lab Paris", ["fr"]),
            ("Lab Boston", ["us"]),
        ]


class TestGetTitle:
    def test_titre_multilingue(self):
        """ScanR renvoie un titre par langue ; celui de la langue par défaut fait foi."""
        assert get_title({"title": {"default": "Un titre", "en": "A title"}}) == "Un titre"

    def test_titre_en_clair(self):
        assert get_title({"title": "Un titre"}) == "Un titre"

    def test_titre_recopie_de_crossref_sans_mathml_aplati(self):
        title = "Measurement of \n                $$\\tau $$\n                    τ\n              polarisation"
        assert get_title({"title": {"default": title}}) == "Measurement of $$\\tau $$ polarisation"


class TestEditeurEtConteneur:
    def test_sans_editeur_nomme_aucun_editeur(self):
        assert get_publisher({}) is None

    def test_editeur_de_la_source(self):
        assert get_publisher({"source": {"publisher": "Elsevier"}}) == PublisherFacts("Elsevier")

    def test_sans_titre_de_revue_aucune_revue(self):
        assert get_container_facts({}).journal_title is None

    def test_revue_et_ses_deux_issn(self):
        """Les identifiants de revue arrivent en liste, sans support : ils restent de support inconnu."""
        facts = get_container_facts(
            {"source": {"title": "J. Things", "journalIssns": ["1234-5679", "8765-4326"]}}
        )
        assert facts.journal_title == "J. Things"
        assert facts.issns == (SerialIssn(issn="1234-5679"), SerialIssn(issn="8765-4326"))

    def test_communication_volume_du_congres(self):
        facts = get_container_facts(
            {"type": "proceedings", "source": {"title": "2021 2nd International Conference"}}
        )
        assert facts.book_title == "2021 2nd International Conference"

    def test_chapitre_plateforme_sans_livre(self):
        """Cas réel : la source d'un chapitre ScanR est la plateforme de l'éditeur."""
        facts = get_container_facts(
            {"type": "book-chapter", "source": {"title": "Presses de Sciences Po eBooks"}}
        )
        assert facts.book_title is None


class TestThese:
    """La source d'une thèse ScanR est l'université de soutenance : elle ne donne aucun conteneur."""

    _DOC = {
        "type": "thesis",
        "source": {"title": "Université Clermont Auvergne (2021-...)", "publisher": "ABES"},
    }

    def test_aucun_conteneur(self):
        assert _normalizer().container_facts(self._DOC) is None

    def test_ni_titre_de_conteneur_ni_revue_dans_la_biblio(self):
        captured = scanr_source_record(self._DOC, 1, "nnt2023clfac001", _NO_CONTAINERS)
        assert captured.container_title is None
        assert captured.biblio == {"publisher": "ABES"}


class TestScanrSourceRecordMetadonnees:
    def test_metadonnees_d_un_article(self):
        doc = {
            "title": {"default": "Un titre"},
            "year": 2024,
            "type": "journal-article",
            "externalIds": [{"type": "doi", "id": "10.1/a"}],
            "isOa": False,
        }

        record = scanr_source_record(
            doc, 1, "doi10.1/a", Containers(has_series=True, monograph_id=None)
        )

        assert record.title == "Un titre"
        assert record.raw_doc_type == "journal-article"
        assert identifier_values(record)["doi"] == ["10.1/a"]
        assert "nnt" not in identifier_values(record)
        assert (
            record.container_title is None
        )  # la revue existe : son titre reste hors de container_title
        assert record.raw_language is None  # absente de la source

    def test_titre_de_contenant_conserve_faute_de_revue(self):
        doc = {"source": {"title": "Actes du colloque"}}

        record = scanr_source_record(doc, 1, "sc-1", _NO_CONTAINERS)

        assert record.container_title == "Actes du colloque"

    def test_these_reconnue_a_son_identifiant(self):
        """La source encode les thèses en préfixant leur numéro national."""
        record = scanr_source_record({}, 1, "these2021CLFAC030", _NO_CONTAINERS)

        assert identifier_values(record) == {"nnt": ["2021CLFAC030"]}


class TestScanrSourceRecordIdentifiants:
    def _call(self, doc, scanr_id: str = "sc-1") -> SourceRecordUpsert:
        return scanr_source_record(doc, staging_id=1, scanr_id=scanr_id, containers=_NO_CONTAINERS)

    def test_identifiant_pubmed(self):
        document = self._call({"externalIds": [{"type": "pmid", "id": "12345678"}]})

        assert identifier_values(document) == {"pmid": ["12345678"]}

    def test_identifiants_incomplets_ignores(self):
        """Une entrée sans type ni valeur ne désigne rien."""
        document = self._call(
            {"externalIds": ["pas un objet", {"type": "hal"}, {"id": "hal-1"}, {}]}
        )

        assert identifier_values(document) == {}

    def test_registre_inconnu_ignore(self):
        document = self._call({"externalIds": [{"type": "openalex", "id": "W1"}]})

        assert identifier_values(document) == {}


class TestScanrSourceRecordChamps:
    def _call(self, doc, scanr_id: str = "sc-1") -> SourceRecordUpsert:
        return scanr_source_record(doc, staging_id=1, scanr_id=scanr_id, containers=_NO_CONTAINERS)

    def test_mots_cles_en_liste(self):
        document = self._call({"keywords": {"default": ["climat", " océan "]}})

        assert document.keywords == ["climat", "océan"]

    def test_mots_cles_en_une_seule_chaine(self):
        document = self._call({"keywords": {"default": "climat, océan"}})

        assert document.keywords == ["climat", "océan"]

    def test_sans_mot_cle(self):
        assert self._call({"keywords": {"default": None}}).keywords is None

    def test_concepts_wikidata_et_mots_cles_rejoignent_les_mots_cles(self):
        """Les libellés s'ajoutent aux mots-clés de l'enregistrement source, sans doublon de casse."""
        document = self._call(
            {
                "keywords": {"default": ["Cirrhose"]},
                "domains": [
                    {"type": "wikidata", "code": "Q147778", "label": {"default": "cirrhose"}},
                    {"type": "wikidata", "code": "Q929737", "label": {"default": "Liver Disease"}},
                    {"type": "keyword", "label": {"default": "TIRF"}},
                ],
            }
        )

        assert document.keywords == ["Cirrhose", "Liver Disease", "TIRF"]
        assert document.topics is None

    def test_vedettes_sudoc_en_sujets(self):
        vedette = {"type": "sudoc", "code": "027219046", "label": {"default": "Analgésie"}}

        document = self._call({"domains": [vedette]})

        assert document.topics == [vedette]
        assert document.keywords is None

    def test_topics_openalex_ignores(self):
        """Le champ `topics` de ScanR reprend les topics OpenAlex : il est ignoré, la source OpenAlex les fournit."""
        document = self._call({"topics": [{"id": "T11207", "display_name": "Alcohol Consumption"}]})

        assert document.topics is None

    def test_citations_cumulees_sur_les_annees(self):
        document = self._call({"cited_by_counts_by_year": {"2023": 4, "2024": 6}})

        assert document.impact == {"cited_by_count": 10}

    def test_adresses_du_document_dedupliquees(self):
        """Les URL viennent du document et de la preuve d'open access, sans doublon."""
        document = self._call(
            {
                "landingPage": "https://exemple.fr/a",
                "doiUrl": "https://doi.org/10.1/a",
                "oaEvidence": {
                    "landingPageUrl": "https://exemple.fr/a",
                    "pdfUrl": "https://x/p.pdf",
                },
            }
        )

        assert document.urls == [
            "https://exemple.fr/a",
            "https://doi.org/10.1/a",
            "https://x/p.pdf",
        ]

    def test_resume_de_la_langue_par_defaut(self):
        assert self._call({"summary": {"default": "Un résumé"}}).abstract == "Un résumé"


def _normalizer() -> ScanrNormalizer:
    return ScanrNormalizer(
        conn=MagicMock(),
        logger=MagicMock(),
        staging_store=MagicMock(),
        record_store=MagicMock(),
        monograph_store=MagicMock(),
        publisher_store=MagicMock(),
        contribution_store=MagicMock(),
        location_store=MagicMock(),
        embargo_store=MagicMock(),
    )


class TestScanrNormalizer:
    def test_entree_source_records_de_la_ligne_et_des_conteneurs(self):
        """L'identifiant ScanR de la ligne donne le NNT ; une revue identifiée laisse le titre du contenant vide."""
        row = staging_row(staging_id=42, source_id="these2021CLFAC030")
        doc = {
            "title": {"default": "Un titre"},
            "year": 2021,
            "type": "thesis",
            "source": {"title": "Revue"},
        }

        document = _normalizer().source_record(
            row, doc, Containers(has_series=True, monograph_id=5)
        )

        assert (document.source, document.source_id, document.staging_id) == (
            "scanr",
            "these2021CLFAC030",
            42,
        )
        assert document.title == "Un titre"
        assert document.monograph_id == 5
        assert document.container_title is None
        assert identifier_values(document) == {"nnt": ["2021CLFAC030"]}

    @pytest.mark.parametrize(
        ("raw", "attendu"),
        [({"year": 2024}, (None, 2024)), ({"title": {"default": "T"}}, ("T", None))],
    )
    def test_metadonnees_minimales(self, raw, attendu):
        assert _normalizer().minimal_metadata(staging_row(raw=raw)) == attendu


class TestGetLocations:
    def test_copie_chez_l_editeur_confondue_avec_la_page_du_document(self):
        """La page du document et celle de la copie ouverte diffèrent seulement par le schéma : une seule localisation."""
        doc = {
            "landingPage": "http://doi.org/10.1093/ehjcr/ytac172",
            "oaEvidence": {
                "hostType": "publisher",
                "landingPageUrl": "https://doi.org/10.1093/ehjcr/ytac172",
                "license": "cc-by-nc",
                "pdfUrl": "https://academic.oup.com/ehjcr/ytac172.pdf",
                "url": "https://academic.oup.com/ehjcr/ytac172.pdf",
                "version": "publishedVersion",
            },
        }
        assert get_locations(doc) == [
            LocationFacts(
                url="https://doi.org/10.1093/ehjcr/ytac172",
                pdf_url="https://academic.oup.com/ehjcr/ytac172.pdf",
                version="publishedVersion",
                license="cc-by-nc",
                is_oa=True,
            )
        ]

    def test_copie_dans_hal_et_page_de_l_editeur(self):
        doc = {
            "landingPage": "http://doi.org/10.1016/j.foodchem.2020.126376",
            "oaEvidence": {
                "hostType": "repository",
                "landingPageUrl": "https://hal.science/hal-02494286",
                "license": "other-oa",
                "url": "https://hal.science/hal-02494286",
                "version": "submittedVersion",
            },
        }
        hal, landing = get_locations(doc)
        assert hal == LocationFacts(
            url="https://hal.science/hal-02494286",
            version="submittedVersion",
            is_oa=True,
        )
        assert landing == LocationFacts(url="http://doi.org/10.1016/j.foodchem.2020.126376")

    def test_fichier_hal_rattache_a_la_page_du_meme_depot(self):
        doc = {
            "landingPage": "https://hal.science/halshs-01774949",
            "oaEvidence": {
                "hostType": "repository",
                "url": "https://shs.hal.science/halshs-01774949/document",
            },
        }
        assert get_locations(doc) == [
            LocationFacts(
                url="https://hal.science/halshs-01774949",
                pdf_url="https://shs.hal.science/halshs-01774949/document",
                is_oa=True,
            )
        ]

    def test_pdf_qui_repete_la_page_est_ecarte(self):
        doc = {
            "oaEvidence": {
                "landingPageUrl": "http://hdl.handle.net/11343/271783",
                "pdfUrl": "http://hdl.handle.net/11343/271783",
                "url": "http://hdl.handle.net/11343/271783",
            }
        }
        assert get_locations(doc) == [
            LocationFacts(url="http://hdl.handle.net/11343/271783", is_oa=True)
        ]

    def test_document_sans_copie_ouverte(self):
        assert get_locations({"landingPage": "https://theses.fr/2020CLFAC001"}) == [
            LocationFacts(url="https://theses.fr/2020CLFAC001")
        ]
        assert get_locations({}) == []
