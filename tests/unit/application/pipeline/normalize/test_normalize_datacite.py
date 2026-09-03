"""Normalizer DataCite : parsing des auteurs, données bibliographiques, et boucle de traitement.

Le format DataCite loge ses métadonnées sous `attributes` et nomme ses auteurs `creators` — dont ceux qui sont des institutions, écartés. La boucle, elle, décide de ce qu'elle refuse : un payload vide, des métadonnées illisibles, un DOI absent, un titre ou une année manquants. Chaque refus marque la ligne de staging traitée, sans quoi elle reviendrait à chaque passe.

Aucune entrée-sortie : les ports d'écriture sont doublés (cf. conftest), et les créations d'éditeur et de revue sont remplacées.
"""

from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize import normalize_datacite
from application.pipeline.normalize.normalize_datacite import (
    DataciteNormalizer,
    build_datacite_author_records,
    get_biblio,
    process_authorships,
    process_work,
    upsert_journal,
    upsert_publisher,
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
        assert [r.person_identifiers for r in recs] == [
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
        assert build_datacite_author_records(attrs)[0].person_identifiers == {
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
        assert build_datacite_author_records(attrs)[0].person_identifiers is None

    def test_shared_orcid_marked_dubious(self):
        """Même ORCID sur 2 creators (dépôt de collaboration) → requalifié `_dubious`."""
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
        assert [r.person_identifiers for r in recs] == [
            {"orcid_dubious": "0000-0002-1825-0097"},
            {"orcid_dubious": "0000-0002-1825-0097"},
        ]

    def test_skips_organizational(self):
        attrs = {
            "creators": [
                {"name": "Big Lab", "nameType": "Organizational"},
                {"givenName": "A", "familyName": "B", "nameType": "Personal"},
            ]
        }
        recs = build_datacite_author_records(attrs)
        assert [r.raw_name for r in recs] == ["A B"]

    def test_name_reconstruction_prefers_given_family(self):
        attrs = {"creators": [{"name": "Doe, Jane", "givenName": "Jane", "familyName": "Doe"}]}
        assert build_datacite_author_records(attrs)[0].raw_name == "Jane Doe"

    def test_name_fallback_to_name_field(self):
        attrs = {"creators": [{"name": "Cher"}]}
        assert build_datacite_author_records(attrs)[0].raw_name == "Cher"

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
                "identifier": "1234-5678",
                "identifierType": "ISSN",
            },
        }
        biblio = get_biblio(attrs)
        assert biblio["volume"] == "12"
        assert biblio["issue"] == "3"
        assert biblio["first_page"] == "100"
        assert biblio["last_page"] == "110"
        assert biblio["publisher"] == "Some Press"
        assert biblio["journal"] == {"title": "J. Things", "issn": "1234-5678"}

    def test_none_when_empty(self):
        assert get_biblio({}) is None


class TestCreatorsIllisibles:
    def test_creators_qui_ne_sont_pas_une_liste(self):
        assert build_datacite_author_records({"creators": {"name": "X"}}) == []

    def test_creator_qui_n_est_pas_un_objet(self):
        attrs = {"creators": ["Doe, J.", {"name": "Roe, R."}]}
        assert [r.raw_name for r in build_datacite_author_records(attrs)] == ["Roe, R."]

    def test_creator_sans_nom_ignore(self):
        attrs = {"creators": [{"nameType": "Personal"}, {"name": "Roe, R."}]}
        assert [r.raw_name for r in build_datacite_author_records(attrs)] == ["Roe, R."]

    def test_identifiant_qui_n_est_pas_un_objet_ignore(self):
        attrs = {"creators": [{"name": "Doe, J.", "nameIdentifiers": ["0000-0002-1825-0097"]}]}
        assert build_datacite_author_records(attrs)[0].person_identifiers is None


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
        assert build_datacite_author_records(attrs)[0].person_identifiers == {
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
        assert build_datacite_author_records(attrs)[0].person_identifiers == {
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


class TestProcessAuthorships:
    def test_confie_les_signatures_au_writer_partage(self, monkeypatch):
        """Les creators deviennent les signatures du document versé ; une institution n'en est pas une."""
        vus: dict[str, object] = {}
        monkeypatch.setattr(
            normalize_datacite,
            "write_source_authorships",
            lambda conn, queries, source, spid, records: vus.update(
                source=source, spid=spid, records=records
            ),
        )
        attrs = {
            "creators": [
                {"name": "Doe, J.", "nameType": "Personal"},
                {"name": "Big Lab", "nameType": "Organizational"},
            ]
        }

        process_authorships(MagicMock(), MagicMock(), attrs, 555)

        assert (vus["source"], vus["spid"]) == ("datacite", 555)
        assert [r.raw_name for r in vus["records"]] == ["Doe, J."]


class TestUpsertPublisher:
    def test_sans_editeur_nomme_rien_n_est_cree(self):
        assert upsert_publisher({}, publisher_repo=MagicMock()) is None

    def test_editeur_nomme_est_cree(self, monkeypatch):
        vus: list[str] = []
        monkeypatch.setattr(
            normalize_datacite,
            "find_or_create_publisher",
            lambda name, *, repo: vus.append(name) or 7,
        )

        assert upsert_publisher({"publisher": "Zenodo"}, publisher_repo=MagicMock()) == 7
        assert vus == ["Zenodo"]


class TestUpsertJournal:
    def test_sans_titre_de_contenant_aucune_revue(self):
        """La majorité des dépôts DataCite sont des jeux de données, sans revue qui les porte."""
        assert upsert_journal({}, None, journal_repo=MagicMock()) is None

    def test_contenant_titre_cree_la_revue(self, monkeypatch):
        vus: dict[str, object] = {}
        monkeypatch.setattr(
            normalize_datacite,
            "find_or_create_journal",
            lambda title, **kw: vus.update(title=title, **kw) or 3,
        )
        attrs = {
            "container": {"title": "J. Things", "identifier": "1234-5678", "identifierType": "ISSN"}
        }

        assert upsert_journal(attrs, 7, journal_repo=MagicMock()) == 3
        assert vus["title"] == "J. Things"
        assert vus["issn"] == "1234-5678"
        assert vus["publisher_id"] == 7


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


class TestProcessWork:
    def _kwargs(self, queries, staging_queries):
        return {
            "journal_repo": MagicMock(),
            "publisher_repo": MagicMock(),
            "publication_repo": MagicMock(),
            "staging_queries": staging_queries,
            "authorship_queries": MagicMock(),
        }

    @pytest.fixture(autouse=True)
    def _sans_editeur_ni_revue(self, monkeypatch):
        """Les créations d'éditeur et de revue ont leurs propres tests : la boucle s'en passe."""
        monkeypatch.setattr(normalize_datacite, "upsert_publisher", lambda a, **kw: None)
        monkeypatch.setattr(normalize_datacite, "upsert_journal", lambda a, p, **kw: None)
        monkeypatch.setattr(normalize_datacite, "process_authorships", lambda *a, **kw: None)

    def _run(self, raw, source_publication_queries, staging_queries, staging_row, logger, doi=None):
        row = staging_row(staging_id=42, raw=raw, doi=doi)
        return process_work(
            MagicMock(),
            source_publication_queries,
            logger,
            row,
            **self._kwargs(source_publication_queries, staging_queries),
        )

    def test_document_verse_et_ligne_marquee(
        self, source_publication_queries, staging_queries, staging_row, logger
    ):
        rendu = self._run(
            {"attributes": _attributs()},
            source_publication_queries,
            staging_queries,
            staging_row,
            logger,
        )

        assert rendu is True
        assert staging_queries.marked_done == [42]
        (document,) = source_publication_queries.upserted_documents
        assert document.source == "datacite"
        assert document.doi == "10.5281/zenodo.1"
        assert document.title == "Un jeu de données"
        assert document.pub_year == 2024
        assert document.oa_status is None  # DataCite ne renseigne pas l'accès ouvert

    def test_dois_apparentes_rassembles(
        self, source_publication_queries, staging_queries, staging_row, logger
    ):
        attributs = _attributs(
            relatedIdentifiers=[
                {
                    "relatedIdentifier": "10.5281/zenodo.0",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsVersionOf",
                }
            ]
        )

        self._run(
            {"attributes": attributs},
            source_publication_queries,
            staging_queries,
            staging_row,
            logger,
        )

        (document,) = source_publication_queries.upserted_documents
        assert document.external_ids == {"related_dois": ["10.5281/zenodo.0"]}

    def test_payload_vide_est_passe(
        self, source_publication_queries, staging_queries, staging_row, logger
    ):
        """Une ligne sans contenu — souche d'un document introuvable — est marquée sans verdict."""
        rendu = self._run(None, source_publication_queries, staging_queries, staging_row, logger)

        assert rendu is None
        assert staging_queries.marked_done == [42]
        assert source_publication_queries.upserted_documents == []

    @pytest.mark.parametrize(
        ("raw", "motif"),
        [
            ({"attributes": "pas un objet"}, "métadonnées illisibles"),
            ({"attributes": {"titles": [{"title": "T"}], "publicationYear": 2024}}, "sans DOI"),
            ({"attributes": {"doi": "10.1/a", "publicationYear": 2024}}, "sans titre"),
            ({"attributes": {"doi": "10.1/a", "titles": [{"title": "T"}]}}, "sans année"),
        ],
    )
    def test_document_refuse_mais_ligne_marquee(
        self, raw, motif, source_publication_queries, staging_queries, staging_row, logger
    ):
        rendu = self._run(raw, source_publication_queries, staging_queries, staging_row, logger)

        assert rendu is False, motif
        assert staging_queries.marked_done == [42]  # sans quoi la ligne reviendrait à chaque passe
        assert source_publication_queries.upserted_documents == []

    def test_doi_repris_du_staging_a_defaut_des_metadonnees(
        self, source_publication_queries, staging_queries, staging_row, logger
    ):
        attributs = _attributs()
        del attributs["doi"]

        rendu = self._run(
            {"attributes": attributs},
            source_publication_queries,
            staging_queries,
            staging_row,
            logger,
            doi="10.5281/zenodo.9",
        )

        assert rendu is True
        assert source_publication_queries.upserted_documents[0].doi == "10.5281/zenodo.9"


def test_le_normalizer_delegue_a_la_boucle(monkeypatch, staging_row):
    """La classe ne fait que rassembler ses dépendances et passer la main."""
    vus: dict[str, object] = {}
    monkeypatch.setattr(
        normalize_datacite,
        "process_work",
        lambda conn, queries, logger, row, **kw: vus.update(row=row, **kw) or True,
    )
    normalizer = DataciteNormalizer(
        conn=MagicMock(),
        logger=MagicMock(),
        staging_queries=MagicMock(),
        queries=MagicMock(),
        journal_repo_factory=lambda c: MagicMock(),
        publisher_repo_factory=lambda c: MagicMock(),
        publication_repo_factory=lambda c: MagicMock(),
        authorship_queries=MagicMock(),
    )
    normalizer.preload_caches(MagicMock())  # instancie les repositories sur la connexion
    row = staging_row()

    assert normalizer.process_work(MagicMock(), row) is True
    assert vus["row"] is row
