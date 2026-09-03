"""Tests unitaires de `application.pipeline.normalize.normalize_scanr`.

Couvre la construction de `biblio` dans `insert_scanr_document` et le parsing
auteurs pur `build_scanr_author_records` (orcid/idref, roles, affiliations →
adresses + pays détectés).

Pattern : `FakeSourcePublicationQueries` + `MagicMock`, pas de DB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize import normalize_scanr
from application.pipeline.normalize.normalize_scanr import (
    ScanrNormalizer,
    build_scanr_author_records,
    extract_doi,
    extract_pub_metadata,
    get_title,
    insert_scanr_document,
    process_authorships,
    process_work,
    upsert_journal,
    upsert_publisher,
)
from tests.unit.application.pipeline.normalize.doubles import (
    FakeSourcePublicationQueries,
    FakeStagingQueries,
    staging_row,
)

_EMPTY_PUB_META: dict[str, Any] = {
    "doi": None,
    "title": None,
    "pub_year": None,
    "doc_type": None,
    "nnt": None,
    "journal_id": None,
    "oa_status": None,
    "language": None,
    "container_title": None,
}


class TestInsertScanrDocumentBiblio:
    def _call(self, queries, doc) -> dict[str, Any]:
        insert_scanr_document(
            MagicMock(),
            queries,
            doc,
            staging_id=1,
            scanr_id="sc-1",
            pub_meta=_EMPTY_PUB_META,
        )
        return queries.upserted_documents[-1]

    def test_biblio_none_when_no_source_fields(self):
        captured = self._call(FakeSourcePublicationQueries(), {})
        assert captured.biblio is None

    def test_biblio_publisher_only(self):
        captured = self._call(FakeSourcePublicationQueries(), {"source": {"publisher": "Elsevier"}})
        assert captured.biblio == {"publisher": "Elsevier"}

    def test_biblio_journal_built_from_title_and_journal_issns(self):
        captured = self._call(
            FakeSourcePublicationQueries(),
            {
                "source": {
                    "title": "Journal of Physics",
                    "journalIssns": ["0022-3727", "1361-6463"],
                }
            },
        )
        assert captured.biblio == {
            "journal": {
                "title": "Journal of Physics",
                "issn": "0022-3727",
                "eissn": "1361-6463",
            }
        }

    def test_biblio_publisher_and_journal_together(self):
        captured = self._call(
            FakeSourcePublicationQueries(),
            {
                "source": {
                    "publisher": "Elsevier",
                    "title": "Journal of Physics",
                    "journalIssns": ["0022-3727"],
                }
            },
        )
        assert captured.biblio == {
            "publisher": "Elsevier",
            "journal": {"title": "Journal of Physics", "issn": "0022-3727"},
        }

    def test_biblio_journal_title_only(self):
        captured = self._call(FakeSourcePublicationQueries(), {"source": {"title": "J. Phys."}})
        assert captured.biblio == {"journal": {"title": "J. Phys."}}


class TestInsertScanrDocumentExternalIds:
    def _call(self, doc, pub_meta) -> dict[str, Any]:
        queries = FakeSourcePublicationQueries()
        insert_scanr_document(
            MagicMock(),
            queries,
            doc,
            staging_id=1,
            scanr_id="sc-1",
            pub_meta=pub_meta,
        )
        return queries.upserted_documents[-1]

    def test_related_dois_excludes_primary(self):
        doc = {
            "externalIds": [
                {"type": "doi", "id": "10.1/primary"},
                {"type": "doi", "id": "10.2/anie"},
                {"type": "hal", "id": "hal-1"},
            ]
        }
        captured = self._call(doc, {**_EMPTY_PUB_META, "doi": "10.1/primary"})
        assert captured.external_ids["related_dois"] == ["10.2/anie"]

    def test_related_dois_absent_when_only_primary(self):
        doc = {"externalIds": [{"type": "doi", "id": "10.1/primary"}]}
        captured = self._call(doc, {**_EMPTY_PUB_META, "doi": "10.1/primary"})
        assert "related_dois" not in (captured.external_ids or {})


# ── build_scanr_author_records (parsing pur) ─────────────────────


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
        assert rec.raw_name == "Marie Dupont"
        assert rec.person_identifiers == {"orcid": "0000-0001-2345-6789", "idref": "123456789"}
        assert rec.roles == ["author"]

    def test_affiliation_becomes_address_with_detected_countries(self):
        doc = {
            "authors": [
                {
                    "fullName": "X",
                    "affiliations": [{"name": "Lab A", "detected_countries": ["FR", "BE"]}],
                }
            ]
        }
        rec = build_scanr_author_records(doc)[0]
        assert [a.text for a in rec.addresses] == ["Lab A"]
        # detected_countries = pays d'autorité (dédupliqués, triés), jamais suggested.
        assert rec.addresses[0].countries == ["BE", "FR"]

    def test_affiliation_sans_nom_garde_son_pays(self):
        """Une affiliation réduite à son pays n'écrit pas d'adresse, mais son pays compte."""
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
        assert rec.addresses[0].countries == ["BE", "FR"]
        assert rec.addresses[0].suggested_countries is None


class TestExtractDoi:
    def test_doi_parmi_les_identifiants_externes(self):
        doc = {"externalIds": [{"type": "hal", "id": "hal-1"}, {"type": "doi", "id": "10.1/a"}]}

        assert extract_doi(doc) == "10.1/a"

    def test_sans_doi(self):
        assert extract_doi({"externalIds": [{"type": "hal", "id": "hal-1"}]}) is None
        assert extract_doi({}) is None


class TestGetTitle:
    def test_titre_multilingue(self):
        """ScanR rend un titre par langue ; celui de la langue par défaut fait foi."""
        assert get_title({"title": {"default": "Un titre", "en": "A title"}}) == "Un titre"

    def test_titre_en_clair(self):
        assert get_title({"title": "Un titre"}) == "Un titre"


class TestUpsertPublisherEtJournal:
    def test_sans_editeur_nomme_rien_n_est_cree(self):
        assert upsert_publisher({}, publisher_repo=MagicMock()) is None

    def test_editeur_nomme_est_cree(self, monkeypatch):
        vus: list[str] = []
        monkeypatch.setattr(
            normalize_scanr,
            "find_or_create_publisher",
            lambda name, *, repo: vus.append(name) or 7,
        )
        doc = {"source": {"publisher": "Elsevier"}}

        assert upsert_publisher(doc, publisher_repo=MagicMock()) == 7
        assert vus == ["Elsevier"]

    def test_sans_titre_de_revue_aucune_revue(self):
        assert upsert_journal({}, None, journal_repo=MagicMock()) is None

    def test_revue_creee_avec_ses_deux_issn(self, monkeypatch):
        """Les identifiants de revue arrivent en liste : le premier est celui du papier, le second celui de l'édition en ligne."""
        vus: dict[str, object] = {}
        monkeypatch.setattr(
            normalize_scanr,
            "find_or_create_journal",
            lambda title, **kw: vus.update(title=title, **kw) or 3,
        )
        doc = {"source": {"title": "J. Things", "journalIssns": ["1234-5678", "8765-4321"]}}

        assert upsert_journal(doc, 7, journal_repo=MagicMock()) == 3
        assert (vus["issn"], vus["eissn"]) == ("1234-5678", "8765-4321")
        assert vus["publisher_id"] == 7


class TestExtractPubMetadata:
    def test_metadonnees_d_un_article(self):
        doc = {
            "title": {"default": "Un titre"},
            "year": 2024,
            "type": "journal-article",
            "externalIds": [{"type": "doi", "id": "10.1/a"}],
            "isOa": False,
        }

        meta = extract_pub_metadata(doc, journal_id=3, scanr_id="doi10.1/a")

        assert meta["title"] == "Un titre"
        assert meta["pub_year"] == 2024
        assert meta["doi"] == "10.1/a"
        assert meta["oa_status"] == "closed"
        assert meta["nnt"] is None
        assert meta["container_title"] is None  # la revue est créée : son titre n'est pas recopié
        assert meta["language"] is None  # la source ne l'expose pas

    def test_titre_de_contenant_conserve_faute_de_revue(self):
        doc = {"source": {"title": "Actes du colloque"}}

        meta = extract_pub_metadata(doc, journal_id=None)

        assert meta["container_title"] == "Actes du colloque"

    def test_these_reconnue_a_son_identifiant(self):
        """La source encode les thèses en préfixant leur numéro national."""
        meta = extract_pub_metadata({}, journal_id=None, scanr_id="these2021CLFAC030")

        assert meta["nnt"] == "2021CLFAC030"


class TestInsertScanrDocumentIdentifiants:
    def _call(self, doc, pub_meta=None) -> Any:
        queries = FakeSourcePublicationQueries()
        insert_scanr_document(
            MagicMock(),
            queries,
            doc,
            staging_id=1,
            scanr_id="sc-1",
            pub_meta=pub_meta or _EMPTY_PUB_META,
        )
        return queries.upserted_documents[-1]

    def test_numero_de_these_repris_des_metadonnees(self):
        document = self._call({}, {**_EMPTY_PUB_META, "nnt": "2021CLFAC030"})

        assert document.external_ids == {"nnt": "2021CLFAC030"}

    def test_identifiant_pubmed(self):
        document = self._call({"externalIds": [{"type": "pmid", "id": "12345678"}]})

        assert document.external_ids == {"pmid": "12345678"}

    def test_identifiants_incomplets_ignores(self):
        """Une entrée sans type ni valeur ne désigne rien."""
        document = self._call(
            {"externalIds": ["pas un objet", {"type": "hal"}, {"id": "hal-1"}, {}]}
        )

        assert document.external_ids is None

    def test_registre_inconnu_ignore(self):
        document = self._call({"externalIds": [{"type": "openalex", "id": "W1"}]})

        assert document.external_ids is None


class TestInsertScanrDocumentChamps:
    def _call(self, doc, pub_meta=None) -> Any:
        queries = FakeSourcePublicationQueries()
        insert_scanr_document(
            MagicMock(),
            queries,
            doc,
            staging_id=1,
            scanr_id="sc-1",
            pub_meta=pub_meta or _EMPTY_PUB_META,
        )
        return queries.upserted_documents[-1]

    def test_mots_cles_en_liste(self):
        document = self._call({"keywords": {"default": ["climat", " océan "]}})

        assert document.keywords == ["climat", "océan"]

    def test_mots_cles_en_une_seule_chaine(self):
        document = self._call({"keywords": {"default": "climat, océan"}})

        assert document.keywords == ["climat", "océan"]

    def test_sans_mot_cle(self):
        assert self._call({"keywords": {"default": None}}).keywords is None

    def test_disciplines_a_defaut_de_sujets(self):
        """La source expose deux vocabulaires : le second sert quand le premier est vide."""
        document = self._call({"domains": [{"label": "Physique"}]})

        assert document.topics == [{"label": "Physique"}]

    def test_sujets_prioritaires_sur_les_disciplines(self):
        document = self._call({"topics": [{"label": "Climat"}], "domains": [{"label": "Physique"}]})

        assert document.topics == [{"label": "Climat"}]

    def test_citations_cumulees_sur_les_annees(self):
        document = self._call({"cited_by_counts_by_year": {"2023": 4, "2024": 6}})

        assert document.cited_by_count == 10

    def test_adresses_du_document_dedupliquees(self):
        """Les adresses viennent du document et du constat d'accès ouvert : les doublons tombent."""
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


class TestProcessAuthorships:
    def test_confie_les_signatures_au_writer_partage(self, monkeypatch):
        vus: dict[str, object] = {}
        monkeypatch.setattr(
            normalize_scanr,
            "write_source_authorships",
            lambda conn, queries, source, spid, records: vus.update(
                source=source, spid=spid, records=records
            ),
        )

        process_authorships(MagicMock(), MagicMock(), {"authors": []}, 555)

        assert (vus["source"], vus["spid"]) == ("scanr", 555)


class TestProcessWork:
    @pytest.fixture(autouse=True)
    def _sans_editeur_ni_revue(self, monkeypatch):
        monkeypatch.setattr(normalize_scanr, "upsert_publisher", lambda d, **kw: None)
        monkeypatch.setattr(normalize_scanr, "upsert_journal", lambda d, p, **kw: None)
        monkeypatch.setattr(normalize_scanr, "process_authorships", lambda *a, **kw: None)

    def _run(self, raw, logger):
        queries = FakeSourcePublicationQueries()
        staging = FakeStagingQueries()
        rendu = process_work(
            MagicMock(),
            queries,
            logger,
            staging_row(staging_id=42, source_id="sc-1", raw=raw),
            journal_repo=MagicMock(),
            publisher_repo=MagicMock(),
            publication_repo=MagicMock(),
            staging_queries=staging,
            authorship_queries=MagicMock(),
        )
        return rendu, queries, staging

    def test_document_verse_et_ligne_marquee(self, logger):
        rendu, queries, staging = self._run(
            {"title": {"default": "Un titre"}, "year": 2024, "type": "journal-article"}, logger
        )

        assert rendu is True
        assert staging.marked_done == [42]
        (document,) = queries.upserted_documents
        assert document.source == "scanr"
        assert document.source_id == "sc-1"
        assert document.title == "Un titre"

    @pytest.mark.parametrize(
        ("raw", "motif"),
        [({"year": 2024}, "sans titre"), ({"title": {"default": "T"}}, "sans année")],
    )
    def test_document_refuse_mais_ligne_marquee(self, raw, motif, logger):
        rendu, queries, staging = self._run(raw, logger)

        assert rendu is False, motif
        assert staging.marked_done == [42]  # sans quoi la ligne reviendrait à chaque passe
        assert queries.upserted_documents == []


def test_le_normalizer_delegue_a_la_boucle(monkeypatch):
    """La classe ne fait que rassembler ses dépendances et passer la main."""
    vus: dict[str, object] = {}
    monkeypatch.setattr(
        normalize_scanr,
        "process_work",
        lambda conn, queries, logger, row, **kw: vus.update(row=row, **kw) or True,
    )
    normalizer = ScanrNormalizer(
        conn=MagicMock(),
        logger=MagicMock(),
        staging_queries=MagicMock(),
        queries=MagicMock(),
        journal_repo_factory=lambda c: MagicMock(),
        publisher_repo_factory=lambda c: MagicMock(),
        publication_repo_factory=lambda c: MagicMock(),
        authorship_queries=MagicMock(),
    )
    normalizer.preload_caches(MagicMock())
    row = staging_row()

    assert normalizer.process_work(MagicMock(), row) is True
    assert vus["row"] is row
