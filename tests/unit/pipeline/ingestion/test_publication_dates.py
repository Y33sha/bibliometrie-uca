"""Date de publication lue par chaque normaliseur, avec sa précision."""

from datetime import date

from domain.publications.dates import DatePrecision, PublicationDate
from pipeline.ingestion.crossref.payload import extract_crossref_publication_date
from pipeline.ingestion.datacite.payload import extract_datacite_publication_date
from pipeline.ingestion.hal.normalize import get_publication_date as hal_date
from pipeline.ingestion.openalex.normalize import get_publication_date as openalex_date
from pipeline.ingestion.scanr.normalize import get_publication_date as scanr_date

YEAR, MONTH, DAY = DatePrecision.YEAR, DatePrecision.MONTH, DatePrecision.DAY


def test_hal_date_de_parution_a_defaut_annee_de_production():
    doc = {"publicationDate_s": "2024-10", "producedDateY_i": 2023}
    assert hal_date(doc) == PublicationDate(date(2024, 10, 1), MONTH)
    assert hal_date({"producedDateY_i": 2023}) == PublicationDate.of_year(2023)


def test_openalex_jour_bouche_trou_ramene_a_sa_precision():
    assert openalex_date({"publication_date": "2024-01-01"}) == PublicationDate.of_year(2024)
    assert openalex_date({"publication_date": "2024-10-01"}) == PublicationDate(
        date(2024, 10, 1), MONTH
    )
    assert openalex_date({"publication_date": "2024-10-15"}) == PublicationDate(
        date(2024, 10, 15), DAY
    )
    assert openalex_date({"publication_year": 2024}) == PublicationDate.of_year(2024)


def test_scanr_horodatage():
    doc = {"publicationDate": "2024-10-15T00:00:00", "year": 2024}
    assert scanr_date(doc) == PublicationDate(date(2024, 10, 15), DAY)
    assert scanr_date({"year": 2024}) == PublicationDate.of_year(2024)


def test_crossref_premiere_date_plausible():
    msg = {"published": {"date-parts": [[2024, 10]]}, "issued": {"date-parts": [[2025]]}}
    assert extract_crossref_publication_date(msg, max_year=2026) == PublicationDate(
        date(2024, 10, 1), MONTH
    )


def test_datacite_date_issued_a_defaut_annee():
    attributes = {
        "publicationYear": 2024,
        "dates": [{"dateType": "Issued", "date": "2023-12-05"}],
    }
    assert extract_datacite_publication_date(attributes, max_year=2026) == PublicationDate(
        date(2023, 12, 5), DAY
    )
    assert extract_datacite_publication_date(
        {"publicationYear": "2024"}, max_year=2026
    ) == PublicationDate.of_year(2024)
