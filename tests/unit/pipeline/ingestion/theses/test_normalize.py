"""Tests unitaires de `pipeline.ingestion.theses.normalize`.

Couvre `get_title` et `get_publication_year` (cascade soutenance/inscription), `_build_source_extras` (date_soutenance, date_inscription, discipline, écoles doctorales, partenaires), `theses_source_record` (métadonnées canoniques, keywords sujets, topics discipline+rameau, NNT external_ids), `build_theses_author_records` (rôles, positions, adresses du document) et les méthodes de `ThesesNormalizer` (métadonnées minimales, éditeur et conteneur absents, enregistrement source, contributions sources).

Pattern : doublures de `tests.helpers.normalize_doubles` + `MagicMock`, pas de DB.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

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
                "etabSoutenanceN": "Université Clermont Auvergne (2021-...)",
                "etabSoutenancePpn": "252404955",
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
            "etabSoutenanceN": "Université Clermont Auvergne (2021-...)",
            "ecolesDoctorale": [{"nom": "EDSPI", "ppn": "1234"}, {"nom": "EDMS"}],
            "partenairesDeRecherche": [
                {"nom": "LIMOS", "type": "labo", "ppn": "035163569"},
                {"nom": "LRL"},
            ],
        }
        meta = _build_source_extras(thesis)
        assert meta is not None
        assert meta["date_soutenance"] == "2024-03-15"
        assert meta["date_inscription"] == "2020-09-10"
        assert meta["discipline"] == "Informatique"
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
        meta = _build_source_extras({"ecolesDoctorale": [{"ppn": "123"}, {"nom": "EDSPI"}]})
        assert meta == {"ecoles_doctorales": [{"nom": "EDSPI", "ppn": None}]}

    def test_filters_partenaires_without_nom(self):
        meta = _build_source_extras({"partenairesDeRecherche": [{"type": "x"}, {"nom": "LIMOS"}]})
        assert meta == {"partenaires": [{"nom": "LIMOS", "type": None, "ppn": None}]}


# ── theses_source_record ─────────────────────────────────────────


class TestThesesSourceRecord:
    def _call(self, thesis: dict) -> SourceRecordUpsert:
        return theses_source_record(thesis, staging_id=1, theses_id="2024CLFAC001")

    def test_minimal(self):
        record = self._call({"titrePrincipal": "T"})
        assert record.title == "T"
        assert record.publication_year is None
        assert record.external_ids is None
        assert record.oa_status == "closed"
        assert record.serial_id is None

    def test_nnt_normalized(self):
        record = self._call({"titrePrincipal": "T", "nnt": "  2024clfac001  "})
        assert record.external_ids == {"nnt": "2024CLFAC001"}

    def test_doi_passthrough(self):
        assert self._call({"titrePrincipal": "T", "doi": "10.1/abc"}).doi == "10.1/abc"

    def test_nnt_goes_in_external_ids(self):
        record = self._call({"nnt": "2024CLFAC001"})
        assert record.external_ids == {"nnt": "2024CLFAC001"}

    def test_no_nnt_no_external_ids(self):
        assert self._call({}).external_ids is None

    def test_keywords_from_sujets(self):
        thesis = {"sujets": [{"libelle": "machine learning"}, {"libelle": "NLP"}, {}]}
        assert self._call(thesis).keywords == ["machine learning", "NLP"]

    def test_no_keywords(self):
        assert self._call({}).keywords is None

    def test_topics_discipline_only(self):
        assert self._call({"discipline": "Informatique"}).topics == {"discipline": "Informatique"}

    def test_topics_with_rameau(self):
        thesis = {
            "discipline": "Informatique",
            "sujetsRameau": [{"libelle": "Apprentissage automatique"}, {}],
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
            partenairesDeRecherche=[{"nom": "LIMOS"}],
            etabSoutenanceN="Université Clermont Auvergne (2021-...)",
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
    )


class TestThesesNormalizerClass:
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
        assert record.external_ids == {"nnt": "2024CLFAC001"}
        assert record.serial_id is None

    def test_contributions_sources_d_une_these(self):
        norm = _make_normalizer()
        records = norm.author_records(norm.author_block(_these()))
        assert [(r.position, r.roles) for r in records] == [
            (0, ["author"]),
            (None, ["thesis_director"]),
        ]
