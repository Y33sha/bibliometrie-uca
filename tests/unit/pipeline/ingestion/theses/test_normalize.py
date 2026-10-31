"""Tests unitaires de `pipeline.ingestion.theses.normalize`.

Couvre le titre et l'année (soutenance, sinon inscription), les champs propres à theses.fr, l'enregistrement source construit par `theses_source_record`, la lecture des auteurs et les méthodes de `ThesesNormalizer`. Doublures de `tests.helpers.normalize_doubles` et `MagicMock`, sans base de données.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from pipeline.ingestion.common.embargoes import Embargo
from pipeline.ingestion.common.source_records import SourceRecordUpsert
from pipeline.ingestion.theses.normalize import (
    ThesesNormalizer,
    _build_source_extras,
    build_theses_author_records,
    extract_theses_author_block,
    get_publication_year,
    get_title,
    theses_source_record,
)
from pipeline.transformation.publishing.find_or_create import Containers
from tests.helpers.normalize_doubles import (
    FakeSourceContributionStore,
    FakeSourceRecordStore,
    FakeStagingStore,
    identifier_values,
    staging_row,
)

# ── get_title, get_publication_year ──────────────────────────────────────


class TestExtractors:
    def test_title(self):
        assert get_title({"titrePrincipal": "T"}) == "T"

    def test_no_title(self):
        assert get_title({}) is None

    def test_no_dates_no_publication_year(self):
        assert get_publication_year({"titrePrincipal": "T"}) is None

    def test_publication_year_from_soutenance(self):
        assert get_publication_year({"titrePrincipal": "T", "dateSoutenance": "15/03/2024"}) == 2024

    def test_publication_year_fallback_to_inscription(self):
        """Sans date de soutenance, l'année vient de la première inscription."""
        thesis = {"titrePrincipal": "T", "datePremiereInscriptionDoctorat": "10/09/2020"}
        assert get_publication_year(thesis) == 2020

    def test_publication_year_soutenance_wins_over_inscription(self):
        thesis = {
            "titrePrincipal": "T",
            "dateSoutenance": "15/03/2024",
            "datePremiereInscriptionDoctorat": "10/09/2020",
        }
        assert get_publication_year(thesis) == 2024


# ── _build_source_extras ───────────────────────────────────────────


class TestBuildSourceMeta:
    def test_empty(self):
        assert _build_source_extras({}) is None

    def test_only_soutenance(self):
        meta = _build_source_extras({"dateSoutenance": "15/03/2024"})
        assert meta == {"date_soutenance": "2024-03-15"}

    def test_etablissement(self):
        meta = _build_source_extras(
            {
                "etabSoutenance": {
                    "nom": "Université Clermont Auvergne (2021-...)",
                    "ppn": "252404955",
                }
            }
        )
        assert meta == {
            "etablissement": "Université Clermont Auvergne (2021-...)",
            "etablissement_ppn": "252404955",
        }

    def test_full(self):
        thesis = {
            "dateSoutenance": "15/03/2024",
            "datePremiereInscriptionDoctorat": "10/09/2020",
            "discipline": "Informatique",
            "etabSoutenance": {"nom": "Université Clermont Auvergne (2021-...)"},
            "ecolesDoctorales": [{"nom": "EDSPI", "ppn": "1234"}, {"nom": "EDMS"}],
            "partenairesRecherche": [
                {"nom": "LIMOS", "type": "labo", "ppn": "035163569"},
                {"nom": "LRL"},
            ],
        }
        meta = _build_source_extras(thesis)
        assert meta is not None
        assert meta["date_soutenance"] == "2024-03-15"
        assert meta["date_inscription"] == "2020-09-10"
        assert meta["etablissement"] == "Université Clermont Auvergne (2021-...)"
        assert meta["ecoles_doctorales"] == [
            {"nom": "EDSPI", "ppn": "1234"},
            {"nom": "EDMS", "ppn": None},
        ]
        assert meta["partenaires"] == [
            {"nom": "LIMOS", "type": "labo", "ppn": "035163569"},
            {"nom": "LRL", "type": None, "ppn": None},
        ]

    def test_filters_ecoles_without_nom(self):
        meta = _build_source_extras({"ecolesDoctorales": [{"ppn": "123"}, {"nom": "EDSPI"}]})
        assert meta == {"ecoles_doctorales": [{"nom": "EDSPI", "ppn": None}]}

    def test_filters_partenaires_without_nom(self):
        meta = _build_source_extras({"partenairesRecherche": [{"type": "x"}, {"nom": "LIMOS"}]})
        assert meta == {"partenaires": [{"nom": "LIMOS", "type": None, "ppn": None}]}

    def test_entries_without_nom_give_none(self):
        thesis = {
            "ecolesDoctorales": [{"nom": ""}, {"ppn": "123"}],
            "partenairesRecherche": [{"type": "lab"}],
        }
        assert _build_source_extras(thesis) is None


# ── theses_source_record ─────────────────────────────────────────


class TestThesesSourceRecord:
    def _call(self, thesis: dict) -> SourceRecordUpsert:
        return theses_source_record(thesis, staging_id=1, theses_id="2024CLFAC001")

    def test_minimal(self):
        record = self._call({"titrePrincipal": "T"})
        assert record.title == "T"
        assert record.publication_year is None
        assert identifier_values(record) == {}
        assert record.oa_status == "closed"
        assert record.serial_id is None

    def test_defended_thesis(self):
        assert self._call({"dateSoutenance": "15/03/2023"}).raw_doc_type == "thesis"

    def test_ongoing_thesis(self):
        record = self._call({"datePremiereInscriptionDoctorat": "01/09/2022"})
        assert record.raw_doc_type == "ongoing_thesis"
        assert record.publication_year == 2022

    def test_malformed_date(self):
        assert self._call({"dateSoutenance": "date-invalide"}).publication_year is None

    def test_nnt_normalized(self):
        record = self._call({"titrePrincipal": "T", "nnt": "  2024clfac001  "})
        assert identifier_values(record) == {"nnt": ["2024CLFAC001"]}

    def test_doi_passthrough(self):
        record = self._call({"titrePrincipal": "T", "doi": "10.1/abc"})
        assert identifier_values(record)["doi"] == ["10.1/abc"]

    def test_nnt_goes_in_identifiers(self):
        record = self._call({"nnt": "2024CLFAC001"})
        assert identifier_values(record) == {"nnt": ["2024CLFAC001"]}

    def test_no_nnt_no_identifiers(self):
        assert identifier_values(self._call({})) == {}

    def test_keywords_from_sujets(self):
        """Les mots-clés suivent l'ordre de `langues`."""
        thesis = {
            "langues": ["fr", "en"],
            "mapSujets": {
                "en": [
                    {"keyword": "machine learning", "type": "sujet"},
                    {"keyword": "apprentissage", "type": "sujet"},
                ],
                "fr": [
                    {"keyword": "apprentissage", "type": "sujet"},
                    {"keyword": "Apprentissage automatique", "type": "sujetsRameau"},
                    {"type": "sujet"},
                ],
            },
        }
        assert self._call(thesis).keywords == ["apprentissage", "machine learning"]

    def test_no_keywords(self):
        assert self._call({}).keywords is None

    def test_topics_discipline_only(self):
        assert self._call({"discipline": "Informatique"}).topics == {"discipline": "Informatique"}

    def test_topics_with_rameau(self):
        thesis = {
            "discipline": "Informatique",
            "mapSujets": {
                "fr": [{"keyword": "Apprentissage automatique", "type": "sujetsRameau"}, {}]
            },
        }
        assert self._call(thesis).topics == {
            "discipline": "Informatique",
            "rameau": ["Apprentissage automatique"],
        }

    def test_no_topics(self):
        assert self._call({}).topics is None

    def test_source_meta_passed(self):
        record = self._call({"dateSoutenance": "15/03/2024"})
        assert record.source_extras == {"date_soutenance": "2024-03-15"}

    def test_title_empty_string_when_none(self):
        record = self._call({})
        assert record.title == ""

    @pytest.mark.parametrize(
        ("diffusion", "expected"),
        [
            ({"cas": "cas1", "accessible": "oui"}, "green"),
            ({"cas": "cas3", "accessible": "oui"}, "green"),
            ({"cas": "cas1", "accessible": "non"}, "embargoed"),
            ({"cas": "cas4", "accessible": "non"}, "embargoed"),
            ({"cas": "cas5", "accessible": "non"}, "closed"),
            ({"cas": None, "accessible": "non"}, "closed"),  # thèse en cours
        ],
    )
    def test_statut_open_access_selon_la_diffusion(self, diffusion, expected):
        """Le statut open access suit la diffusion de la thèse ; une thèse accessible sur theses.fr est `green`."""
        assert self._call(diffusion).oa_status == expected

    def test_langue_et_resume_de_la_premiere_langue(self):
        thesis = {"langues": ["en", "fr"], "resumes": {"fr": "Résumé.", "en": "Summary."}}
        record = self._call(thesis)
        assert (record.raw_language, record.abstract) == ("en", "Summary.")

    def test_resume_d_une_autre_langue_a_defaut(self):
        record = self._call({"langues": ["fr"], "resumes": {"en": "Summary."}})
        assert record.abstract == "Summary."


# ── build_theses_author_records ──────────────────────────────────


def _these(**fields):
    """Thèse avec un auteur (IdRef connu) et un directeur."""
    return {
        "auteurs": [{"nom": "Dupont", "prenom": "Marie", "ppn": "123456789"}],
        "directeurs": [{"nom": "Martin", "prenom": "Jean"}],
        **fields,
    }


class TestBuildThesesAuthorRecords:
    def test_seuls_les_auteurs_ont_une_position(self):
        records = build_theses_author_records(extract_theses_author_block(_these()))
        assert [(r.position, r.roles, r.identifiers) for r in records] == [
            (0, ["author"], {"idref": "123456789"}),
            (None, ["thesis_director"], None),
        ]

    def test_aucune_adresse(self):
        """Partenaires et établissement de soutenance restent dans `meta` : aucune contribution source ne reçoit d'adresse."""
        thesis = _these(
            partenairesRecherche=[{"nom": "LIMOS"}],
            etabSoutenance={"nom": "Université Clermont Auvergne (2021-...)"},
        )
        records = build_theses_author_records(extract_theses_author_block(thesis))
        assert all(r.addresses == [] for r in records)


# ── ThesesNormalizer (classe) ────────────────────────────────────


def _make_normalizer():
    return ThesesNormalizer(
        conn=MagicMock(),
        logger=logging.getLogger("test"),
        staging_store=FakeStagingStore(),
        record_store=FakeSourceRecordStore(),
        container_stores=MagicMock(),
        publisher_store=MagicMock(),
        contribution_store=FakeSourceContributionStore(),
        location_store=MagicMock(),
        embargo_store=MagicMock(),
    )


class TestThesesNormalizerClass:
    def test_embargo_sans_date_d_une_these_destinee_a_internet(self):
        norm = _make_normalizer()
        assert norm.embargo(_these(cas="cas1", accessible="non")) == Embargo(None)
        assert norm.embargo(_these(cas="cas5", accessible="non")) is None
        assert norm.embargo(_these(cas="cas1", accessible="oui")) is None

    def test_metadonnees_minimales(self):
        assert _make_normalizer().minimal_metadata(staging_row(raw={})) == (None, None)

    def test_sans_editeur_ni_conteneur(self):
        norm = _make_normalizer()
        thesis = _these(titrePrincipal="T")
        assert norm.publisher(thesis) is None
        assert norm.container_facts(thesis) is None

    def test_source_record_d_une_these(self):
        """L'enregistrement source reprend la ligne de staging et les métadonnées lues dans la thèse."""
        thesis = {"titrePrincipal": "T", "nnt": "2024clfac001", "dateSoutenance": "15/03/2024"}
        row = staging_row(staging_id=42, source_id="2024CLFAC001", raw=thesis)
        record = _make_normalizer().source_record(row, thesis, Containers(None, None))
        assert (record.source, record.source_id, record.staging_id) == (
            "theses",
            "2024CLFAC001",
            42,
        )
        assert (record.title, record.publication_year) == ("T", 2024)
        assert identifier_values(record) == {"nnt": ["2024CLFAC001"]}
        assert record.serial_id is None

    def test_contributions_sources_d_une_these(self):
        norm = _make_normalizer()
        records = norm.author_records(norm.author_block(_these()))
        assert [(r.position, r.roles) for r in records] == [
            (0, ["author"]),
            (None, ["thesis_director"]),
        ]
