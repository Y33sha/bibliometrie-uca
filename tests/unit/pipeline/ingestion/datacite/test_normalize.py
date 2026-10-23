"""Normaliseur DataCite : parsing des auteurs, données bibliographiques, conteneurs et enregistrement source.

Le format DataCite loge ses métadonnées sous `attributes` et nomme ses auteurs `creators`. Un nœud sans DOI est refusé. L'enregistrement source est construit sans entrée-sortie.
"""

from unittest.mock import MagicMock

from domain.journals.issns import JournalIssn
from domain.persons.contributor_name import ContributorName
from pipeline.ingestion.common.normalizer import PublisherFacts
from pipeline.ingestion.datacite.normalize import (
    DataciteNormalizer,
    build_datacite_author_records,
    datacite_doi,
    datacite_source_record,
    get_biblio,
    get_container_facts,
)
from pipeline.transformation.publishing.find_or_create import Containers
from tests.helpers.normalize_doubles import staging_row


def _normalizer() -> DataciteNormalizer:
    return DataciteNormalizer(
        conn=MagicMock(),
        logger=MagicMock(),
        staging_store=MagicMock(),
        record_store=MagicMock(),
        container_stores=MagicMock(),
        publisher_store=MagicMock(),
        contribution_store=MagicMock(),
    )


class TestAuthorRecords:
    def test_orcid_url_and_bare(self):
        attrs = {
            "creators": [
                {
                    "givenName": "Jane",
                    "familyName": "Doe",
                    "nameType": "Personal",
                    "nameIdentifiers": [
                        {
                            "nameIdentifier": "https://orcid.org/0000-0002-1825-0097",
                            "nameIdentifierScheme": "ORCID",
                        }
                    ],
                },
                {
                    "name": "Bare, O.",
                    "nameType": "Personal",
                    "nameIdentifiers": [
                        {"nameIdentifier": "0000-0001-5109-3700", "nameIdentifierScheme": "ORCID"}
                    ],
                },
            ]
        }
        recs = build_datacite_author_records(attrs)
        assert [r.identifiers for r in recs] == [
            {"orcid": "0000-0002-1825-0097"},
            {"orcid": "0000-0001-5109-3700"},
        ]

    def test_orcid_via_scheme_uri(self):
        """`schemeUri` désignant orcid.org tient lieu de `nameIdentifierScheme`."""
        attrs = {
            "creators": [
                {
                    "name": "Doe, J.",
                    "nameType": "Personal",
                    "nameIdentifiers": [
                        {
                            "nameIdentifier": "0000-0002-1825-0097",
                            "schemeUri": "https://orcid.org",
                        }
                    ],
                }
            ]
        }
        assert build_datacite_author_records(attrs)[0].identifiers == {
            "orcid": "0000-0002-1825-0097"
        }

    def test_scheme_uri_hosted_elsewhere(self):
        """`orcid.org` dans le chemin d'un autre hôte ne qualifie pas l'identifiant."""
        attrs = {
            "creators": [
                {
                    "name": "Doe, J.",
                    "nameType": "Personal",
                    "nameIdentifiers": [
                        {
                            "nameIdentifier": "0000-0002-1825-0097",
                            "schemeUri": "https://exemple.fr/orcid.org/",
                        }
                    ],
                }
            ]
        }
        assert build_datacite_author_records(attrs)[0].identifiers is None

    def test_shared_orcid_kept_on_each_record(self):
        """La lecture rend l'ORCID de chaque creator tel que la source le donne ; le writer neutralise ceux que partagent plusieurs contributions sources."""
        attrs = {
            "creators": [
                {
                    "name": "Acharya, S.",
                    "nameIdentifiers": [
                        {"nameIdentifier": "0000-0002-1825-0097", "nameIdentifierScheme": "ORCID"}
                    ],
                },
                {
                    "name": "Das, S.",
                    "nameIdentifiers": [
                        {"nameIdentifier": "0000-0002-1825-0097", "nameIdentifierScheme": "ORCID"}
                    ],
                },
            ]
        }
        recs = build_datacite_author_records(attrs)
        assert [r.identifiers for r in recs] == [
            {"orcid": "0000-0002-1825-0097"},
            {"orcid": "0000-0002-1825-0097"},
        ]

    def test_organizational_est_collectif(self):
        attrs = {
            "creators": [
                {"name": "Big Lab", "nameType": "Organizational"},
                {"givenName": "A", "familyName": "B", "nameType": "Personal"},
            ]
        }
        recs = build_datacite_author_records(attrs)
        assert [(r.position, r.name.display(), r.collective) for r in recs] == [
            (0, "Big Lab", True),
            (1, "A B", False),
        ]

    def test_given_family_prioritaires(self):
        attrs = {"creators": [{"name": "Doe, Jane", "givenName": "Jane", "familyName": "Doe"}]}
        assert build_datacite_author_records(attrs)[0].name == ContributorName(
            last_name="Doe", first_name="Jane"
        )

    def test_name_fallback_to_name_field(self):
        attrs = {"creators": [{"name": "Cher"}]}
        assert build_datacite_author_records(attrs)[0].name == ContributorName(raw="Cher")

    def test_family_name_sans_given_name_reste_chaine_brute(self):
        # `familyName` seul porte souvent le nom complet.
        attrs = {"creators": [{"familyName": "Mathieu Durand"}]}
        assert build_datacite_author_records(attrs)[0].name == ContributorName(raw="Mathieu Durand")

    def test_affiliation_string_and_object(self):
        attrs = {
            "creators": [
                {
                    "name": "X",
                    "affiliation": [
                        "Plain affil",
                        {"name": "Object affil", "affiliationIdentifier": "https://ror.org/x"},
                    ],
                }
            ]
        }
        addresses = build_datacite_author_records(attrs)[0].addresses
        assert [a.text for a in addresses] == ["Plain affil", "Object affil"]

    def test_roles_default_author(self):
        attrs = {"creators": [{"name": "X"}]}
        assert build_datacite_author_records(attrs)[0].roles == ["author"]


class TestBiblio:
    def test_volume_issue_pages_from_container(self):
        attrs = {
            "publisher": "Some Press",
            "container": {
                "title": "J. Things",
                "volume": "12",
                "issue": "3",
                "firstPage": "100",
                "lastPage": "110",
                "identifier": "1234-5679",
                "identifierType": "ISSN",
            },
        }
        biblio = get_biblio(attrs)
        assert biblio["volume"] == "12"
        assert biblio["issue"] == "3"
        assert biblio["first_page"] == "100"
        assert biblio["last_page"] == "110"
        assert biblio["publisher"] == "Some Press"
        assert biblio["journal"] == {"title": "J. Things", "issn": "1234-5679"}

    def test_none_when_empty(self):
        assert get_biblio({}) is None


class TestCreatorsIllisibles:
    def test_creators_qui_ne_sont_pas_une_liste(self):
        assert build_datacite_author_records({"creators": {"name": "X"}}) == []

    def test_creator_qui_n_est_pas_un_objet(self):
        attrs = {"creators": ["Doe, J.", {"name": "Roe, R."}]}
        assert [r.name.display() for r in build_datacite_author_records(attrs)] == ["Roe, R."]

    def test_creator_sans_nom_ignore(self):
        attrs = {"creators": [{"nameType": "Personal"}, {"name": "Roe, R."}]}
        assert [r.name.display() for r in build_datacite_author_records(attrs)] == ["Roe, R."]

    def test_identifiant_qui_n_est_pas_un_objet_ignore(self):
        attrs = {"creators": [{"name": "Doe, J.", "nameIdentifiers": ["0000-0002-1825-0097"]}]}
        assert build_datacite_author_records(attrs)[0].identifiers is None


class TestChampsIgnores:
    def test_donnee_bibliographique_qui_n_est_pas_du_texte(self):
        """Un volume numérique plutôt que textuel n'est pas repris : le champ attend une chaîne."""
        biblio = get_biblio({"container": {"title": "J. Things", "volume": 12, "issue": "3"}})
        assert "volume" not in biblio
        assert biblio["issue"] == "3"

    def test_identifiant_d_un_autre_registre_ignore(self):
        """Un creator peut porter plusieurs identifiants : seul celui d'ORCID est retenu."""
        attrs = {
            "creators": [
                {
                    "name": "Doe, J.",
                    "nameIdentifiers": [
                        {"nameIdentifier": "0000000121032683", "nameIdentifierScheme": "ISNI"},
                        {
                            "nameIdentifier": "0000-0002-1825-0097",
                            "nameIdentifierScheme": "ORCID",
                        },
                    ],
                }
            ]
        }
        assert build_datacite_author_records(attrs)[0].identifiers == {
            "orcid": "0000-0002-1825-0097"
        }

    def test_identifiant_orcid_illisible_ignore(self):
        """Le registre est le bon, la valeur non : on continue de chercher."""
        attrs = {
            "creators": [
                {
                    "name": "Doe, J.",
                    "nameIdentifiers": [
                        {"nameIdentifier": "pas-un-orcid", "nameIdentifierScheme": "ORCID"},
                        {
                            "nameIdentifier": "0000-0002-1825-0097",
                            "nameIdentifierScheme": "ORCID",
                        },
                    ],
                }
            ]
        }
        assert build_datacite_author_records(attrs)[0].identifiers == {
            "orcid": "0000-0002-1825-0097"
        }

    def test_affiliations_sans_texte_exploitable(self):
        attrs = {
            "creators": [
                {
                    "name": "Doe, J.",
                    "affiliation": [
                        "  ",
                        {"affiliationIdentifier": "https://ror.org/x"},
                        "Un labo",
                    ],
                }
            ]
        }
        addresses = build_datacite_author_records(attrs)[0].addresses
        assert [a.text for a in addresses] == ["Un labo"]


class TestAuthorBlock:
    def test_creators_deviennent_les_contributions_sources(self):
        """Le bloc auteurs du normaliseur porte les `creators`, que `author_records` lit."""
        normalizer = _normalizer()
        attrs = {
            "creators": [
                {"name": "Doe, J.", "nameType": "Personal"},
                {"name": "Big Lab", "nameType": "Organizational"},
            ]
        }

        records = normalizer.author_records(normalizer.author_block(attrs))

        assert [r.name.display() for r in records] == ["Doe, J.", "Big Lab"]


class TestPublisher:
    def test_sans_editeur_nomme_aucun_editeur(self):
        assert _normalizer().publisher({}) is None

    def test_editeur_nomme(self):
        assert _normalizer().publisher({"publisher": "Zenodo"}) == PublisherFacts("Zenodo")


class TestContainers:
    def test_sans_titre_de_contenant_aucun_conteneur(self):
        """La majorité des dépôts DataCite sont des jeux de données, sans revue qui les porte."""
        facts = _normalizer().container_facts({})
        assert (facts.journal_title, facts.collection_title, facts.book_title) == (None, None, None)

    def test_revue_identifiee_par_son_issn(self):
        attrs = {
            "types": {"resourceTypeGeneral": "JournalArticle"},
            "container": {
                "title": "J. Things",
                "identifier": "1234-5679",
                "identifierType": "ISSN",
            },
        }
        facts = get_container_facts(attrs)
        assert (facts.journal_title, facts.issns) == ("J. Things", (JournalIssn(issn="1234-5679"),))
        assert (facts.collection_title, facts.book_title) == ("J. Things", None)

    def test_chapitre_livre_du_contenant(self):
        attrs = {
            "types": {"resourceTypeGeneral": "BookChapter"},
            "container": {"title": "Transmission and Gender"},
        }
        facts = get_container_facts(attrs)
        assert (facts.raw_doc_type, facts.book_title) == ("BookChapter", "Transmission and Gender")

    def test_revue_au_type_libre_nomme_la_revue(self):
        """Cas réel : ATeM dépose ses articles sous le type générique `Text`, « Journal article » en texte libre."""
        attrs = {
            "types": {"resourceTypeGeneral": "Text", "resourceType": "Journal article"},
            "container": {"title": "ATeM Archiv für Textmusikforschung", "type": "Series"},
        }

        facts = get_container_facts(attrs)

        assert facts.journal_title == "ATeM Archiv für Textmusikforschung"

    def test_copie_d_entrepot_sans_revue(self):
        """Cas réel : l'entrepôt du GSI dépose une copie d'article ; DataCite découpe mal sa citation en conteneur."""
        attrs = {
            "types": {"resourceTypeGeneral": "Text", "resourceType": "Journal article"},
            "container": {
                "title": "Physics letters / B 777",
                "firstPage": "151",
                "lastPage": "162 (2018). doi:10.1016/j.physletb.2017.12.021",
                "type": "Series",
            },
        }
        facts = get_container_facts(attrs)
        assert (facts.journal_title, facts.book_title) == (None, None)

    def test_livre_sans_conteneur_garde_titre_et_isbn(self):
        """Cas réel : Classiques Garnier décrit la collection par ses seuls ISSN, sans titre."""
        attrs = {
            "types": {"resourceTypeGeneral": "Book", "resourceType": "Book"},
            "titles": [{"title": "Éléments et Matières"}],
            "container": {"identifier": "2493-8947", "identifierType": "LISSN", "type": "Series"},
            "identifiers": [{"identifier": "978-2-406-09785-3", "identifierType": "ISBN"}],
        }
        facts = get_container_facts(attrs)
        assert facts.document_title == "Éléments et Matières"
        assert facts.isbns == ("9782406097853",)
        assert facts.journal_title is None


def _attributs(**surcharges) -> dict:
    """Métadonnées DataCite minimales et acceptables, que chaque test dégrade à sa guise."""
    return {
        "doi": "10.5281/zenodo.1",
        "titles": [{"title": "Un jeu de données"}],
        "publicationYear": 2024,
        "types": {"resourceTypeGeneral": "Dataset"},
        "creators": [{"name": "Doe, J.", "nameType": "Personal"}],
        **surcharges,
    }


class TestSourceRecord:
    def test_champs_de_l_enregistrement_source(self):
        attributs = _attributs()

        document = datacite_source_record(
            attributs, 42, datacite_doi(attributs, None), Containers(None, None)
        )

        assert document.source == "datacite"
        assert document.source_id == "10.5281/zenodo.1"
        assert document.staging_id == 42
        assert document.doi == "10.5281/zenodo.1"
        assert document.title == "Un jeu de données"
        assert document.publication_year == 2024
        assert document.oa_status is None  # DataCite ne renseigne pas l'accès ouvert

    def test_dois_apparentes_rassembles(self):
        attributs = _attributs(
            relatedIdentifiers=[
                {
                    "relatedIdentifier": "10.5281/zenodo.0",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsVersionOf",
                }
            ]
        )

        document = datacite_source_record(attributs, 42, "10.5281/zenodo.1", Containers(None, None))

        assert document.external_ids == {"related_dois": ["10.5281/zenodo.0"]}

    def test_titre_du_conteneur_garde_sans_revue_resolue(self):
        attributs = _attributs(container={"title": "Une collection"})

        sans_revue = datacite_source_record(attributs, 42, "10.5281/zenodo.1", Containers(None, 8))
        avec_revue = datacite_source_record(attributs, 42, "10.5281/zenodo.1", Containers(3, None))

        assert (sans_revue.journal_id, sans_revue.monograph_id) == (None, 8)
        assert sans_revue.container_title == "Une collection"
        assert (avec_revue.journal_id, avec_revue.container_title) == (3, None)


class TestDoi:
    def test_doi_des_metadonnees_prioritaire(self):
        assert datacite_doi(_attributs(), "10.5281/zenodo.9") == "10.5281/zenodo.1"

    def test_doi_repris_du_staging_a_defaut_des_metadonnees(self):
        attributs = _attributs()
        del attributs["doi"]
        row = staging_row(staging_id=42, raw={"attributes": attributs}, doi="10.5281/zenodo.9")
        normalizer = _normalizer()

        document = normalizer.source_record(row, normalizer.parse(row), Containers(None, None))

        assert document.doi == "10.5281/zenodo.9"

    def test_document_refuse_sans_doi(self):
        raw = {"attributes": {"titles": [{"title": "T"}], "publicationYear": 2024}}
        assert _normalizer().parse(staging_row(raw=raw)) is None

    def test_parse_rend_les_attributs(self):
        attributs = _attributs()
        assert _normalizer().parse(staging_row(raw={"attributes": attributs})) is attributs


def test_metadonnees_minimales_d_attributs_illisibles():
    normalizer = _normalizer()
    assert normalizer.minimal_metadata(staging_row(raw={"attributes": "pas un objet"})) == (
        None,
        None,
    )
