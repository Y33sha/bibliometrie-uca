"""Normalisation des fiches INSPIRE-HEP (`pipeline.ingestion.inspire.normalize`, `payload`) : identifiants, type, date, enregistrement source, contributions sources."""

from __future__ import annotations

from datetime import date

from domain.contributions.contribution_roles import ContributionRole
from domain.documents.dates import DatePrecision
from domain.source_records.doc_types import map_doc_type
from domain.source_records.identifiers import SourceIdentifierRole, SourceIdentifierType
from pipeline.ingestion.inspire.normalize import build_inspire_author_records, inspire_source_record
from pipeline.ingestion.inspire.payload import (
    doc_type_token,
    publication_date,
    record_dois,
    record_identifiers,
)

_ARTICLE = {
    "control_number": 2683002,
    "titles": [{"title": "Search for B0 → pμ− decays"}],
    "document_type": ["article"],
    "dois": [
        {"source": "APS", "value": "10.1103/PhysRevD.108.012021", "material": "publication"},
        {"value": "10.1103/PhysRevD.110.019901", "material": "erratum"},
    ],
    "arxiv_eprints": [{"value": "2210.10412", "categories": ["hep-ex"]}],
    "external_system_identifiers": [
        {"schema": "HAL", "value": "hal-04174615"},
        {"schema": "CDS", "value": "2838028"},
    ],
    "publication_info": [
        {
            "journal_title": "Phys.Rev.D",
            "journal_volume": "108",
            "journal_issue": "1",
            "artid": "012021",
            "year": 2023,
            "material": "publication",
        },
        {"journal_title": "Phys.Rev.D", "year": 2024, "material": "erratum"},
    ],
    "earliest_date": "2022-10-19",
    "abstracts": [{"source": "APS", "value": "A <math>search</math> is performed."}],
}


class TestIdentifiants:
    def test_doi_arxiv_hal_et_cds_secondaires_erratum_lie(self):
        identifiants = {(i.id_type, i.value, i.role) for i in record_identifiers(_ARTICLE)}
        secondaire, lie = SourceIdentifierRole.SECONDARY, SourceIdentifierRole.RELATED
        assert identifiants == {
            (SourceIdentifierType.DOI, "10.1103/physrevd.108.012021", secondaire),
            (SourceIdentifierType.DOI, "10.1103/physrevd.110.019901", lie),
            (SourceIdentifierType.DOI, "10.48550/arxiv.2210.10412", secondaire),
            (SourceIdentifierType.HAL_ID, "hal-04174615", secondaire),
            (SourceIdentifierType.CDS, "2838028", secondaire),
        }

    def test_doi_de_la_fiche_sans_l_erratum(self):
        assert record_dois(_ARTICLE) == ["10.1103/physrevd.108.012021"]

    def test_doi_lie_des_qu_une_mention_le_marque(self):
        """INSPIRE cite le DOI d'un erratum sans nature, puis comme erratum (fiche 1728111)."""
        fiche = {
            "dois": [
                {"source": "Springer", "value": "10.1140/epjc/s10052-021-09284-5"},
                {"value": "10.1140/epjc/s10052-019-7506-9", "material": "publication"},
                {"value": "10.1140/epjc/s10052-021-09284-5", "material": "erratum"},
            ]
        }
        assert record_dois(fiche) == ["10.1140/epjc/s10052-019-7506-9"]
        assert {(i.value, i.role) for i in record_identifiers(fiche)} == {
            ("10.1140/epjc/s10052-021-09284-5", SourceIdentifierRole.RELATED),
            ("10.1140/epjc/s10052-019-7506-9", SourceIdentifierRole.SECONDARY),
        }

    def test_doi_d_un_jeu_de_donnees_lie(self):
        fiche = {
            "dois": [
                {"value": "10.1088/1475-7516/2025/09/020", "material": "publication"},
                {"value": "10.5281/zenodo.15671861", "material": "data"},
            ]
        }
        assert record_dois(fiche) == ["10.1088/1475-7516/2025/09/020"]


class TestTypeDeDocument:
    def test_article_publie(self):
        assert map_doc_type(doc_type_token(_ARTICLE), "inspire") == "article"

    def test_article_sans_revue_est_un_preprint(self):
        fiche = {"document_type": ["article"], "publication_info": [{"year": 2024}]}
        assert doc_type_token(fiche) == "article_preprint"
        assert map_doc_type("article_preprint", "inspire") == "preprint"

    def test_communication(self):
        assert map_doc_type(doc_type_token({"document_type": ["conference paper"]}), "inspire") == (
            "conference_paper"
        )


class TestDateDePublication:
    def test_annee_de_la_publication_hors_erratum(self):
        date_publication = publication_date(_ARTICLE)
        assert date_publication is not None
        assert (date_publication.value, date_publication.precision) == (
            date(2023, 1, 1),
            DatePrecision.YEAR,
        )

    def test_impression_de_la_meme_annee_precise_la_date(self):
        fiche = {"publication_info": [{"year": 2024}], "imprints": [{"date": "2024-10"}]}
        date_publication = publication_date(fiche)
        assert date_publication is not None
        assert (date_publication.value, date_publication.precision) == (
            date(2024, 10, 1),
            DatePrecision.MONTH,
        )

    def test_sans_publication_date_de_prepublication(self):
        date_publication = publication_date(
            {"preprint_date": "2025-03-14", "earliest_date": "2025-03-01"}
        )
        assert date_publication is not None
        assert date_publication.value == date(2025, 3, 14)


def test_enregistrement_source():
    record = inspire_source_record(_ARTICLE, staging_id=5, has_series=False)
    assert (record.source, record.source_id, record.staging_id) == ("inspire", "2683002", 5)
    assert record.raw_doc_type == "article"
    assert record.container_title == "Phys.Rev.D"
    assert record.biblio == {"volume": "108", "issue": "1", "article_number": "012021"}
    assert record.abstract == "A <math>search</math> is performed."


class TestContributionsSources:
    def test_institutions_en_adresses_et_orcid(self):
        bloc = {
            "authors": [
                {
                    "full_name": "Deschamps, Olivier",
                    "first_name": "Olivier",
                    "last_name": "Deschamps",
                    "ids": [
                        {"schema": "INSPIRE BAI", "value": "O.Deschamps.1"},
                        {"schema": "ORCID", "value": "0000-0002-7047-6042"},
                    ],
                    "affiliations": [{"value": "Clermont-Ferrand U."}],
                    "affiliations_identifiers": [
                        {"schema": "ROR", "value": "https://ror.org/00f9tz983"}
                    ],
                },
                {
                    "full_name": "Xu, Z.",
                    "affiliations": [
                        {"value": "Beijing, GUCAS"},
                        {"value": "Beijing, Inst. High Energy Phys."},
                    ],
                    "affiliations_identifiers": [
                        {"schema": "ROR", "value": "https://ror.org/05qbk4x57"}
                    ],
                },
            ]
        }
        premier, second = build_inspire_author_records(bloc)

        assert (premier.position, premier.identifiers) == (0, {"orcid": "0000-0002-7047-6042"})
        assert [(a.text, sorted(r.value for r in a.ror_ids)) for a in premier.addresses] == [
            ("Clermont-Ferrand U.", ["00f9tz983"])
        ]
        # Deux institutions : la liste des ROR ne dit pas laquelle chacun désigne.
        assert second.position == 1
        assert [(a.text, a.ror_ids) for a in second.addresses] == [
            ("Beijing, GUCAS", frozenset()),
            ("Beijing, Inst. High Energy Phys.", frozenset()),
        ]

    def test_directeur_de_these_sans_position(self):
        bloc = {
            "authors": [
                {"full_name": "Doe, Jane", "inspire_roles": ["supervisor"]},
                {"full_name": "Roe, Max"},
            ]
        }
        directeur, auteur = build_inspire_author_records(bloc)
        assert (directeur.position, directeur.roles) == (None, [ContributionRole.THESIS_DIRECTOR])
        assert (auteur.position, auteur.roles) == (0, [ContributionRole.AUTHOR])
