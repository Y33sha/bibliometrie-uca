"""Entrée dans le périmètre par les identifiants d'une personne qui a une fiche RH : identifiant fort, dates du contrat, filtres de confiance, recalcul après édition d'une adresse."""

import datetime

import pytest
from sqlalchemy import text

from pipeline.transformation.structures.perimeter_evidence import (
    SourceContributionPerimeterRecompute,
    sync_perimeter_evidence,
)
from tests.integration.helpers.persons import (
    insert_hr_record,
    insert_person,
    insert_person_identifier,
)
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_ORCID = "0000-0001-2345-6789"


@pytest.fixture
def rh_person(sa_sync_conn) -> int:
    """Personne RH sous contrat de 2020 à 2023, ORCID confirmé."""
    person = insert_person(sa_sync_conn, "Rh")
    insert_hr_record(
        sa_sync_conn,
        person,
        start_date=datetime.date(2020, 9, 1),
        end_date=datetime.date(2023, 3, 31),
    )
    insert_person_identifier(
        sa_sync_conn, person, id_type="orcid", id_value=_ORCID, status="confirmed"
    )
    return person


def _source_contribution(conn, *, publication_year: int, source: str = "openalex", **kwargs) -> int:
    record = insert_source_record(
        conn,
        source=source,
        source_id=f"{source}-{publication_year}-{kwargs}",
        publication_year=publication_year,
    )
    return insert_source_contribution(
        conn,
        record,
        source=source,
        author_name_normalized="x rh",
        identifiers={"orcid": _ORCID},
        in_perimeter=False,
        **kwargs,
    )


def _in_perimeter(conn, source_contribution: int) -> bool:
    return conn.execute(
        text("SELECT in_perimeter FROM source_contributions WHERE id = :id"),
        {"id": source_contribution},
    ).scalar_one()


def test_contribution_source_pendant_le_contrat_entre_dans_le_perimetre(sa_sync_conn, rh_person):
    debut, fin = (
        _source_contribution(sa_sync_conn, publication_year=2021),
        _source_contribution(sa_sync_conn, publication_year=2023),
    )

    counts = sync_perimeter_evidence(sa_sync_conn, perimeter_ids=[])

    assert _in_perimeter(sa_sync_conn, debut) and _in_perimeter(sa_sync_conn, fin)
    assert counts.added == 2
    evidence = sa_sync_conn.execute(
        text("SELECT perimeter_evidence::text[] FROM source_contributions WHERE id = :id"),
        {"id": debut},
    ).scalar_one()
    assert evidence == ["hr_record"]


def test_contribution_source_hors_des_dates_du_contrat_reste_hors_perimetre(
    sa_sync_conn, rh_person
):
    avant, apres = (
        _source_contribution(sa_sync_conn, publication_year=2019),
        _source_contribution(sa_sync_conn, publication_year=2024),
    )

    sync_perimeter_evidence(sa_sync_conn, perimeter_ids=[])

    assert not _in_perimeter(sa_sync_conn, avant)
    assert not _in_perimeter(sa_sync_conn, apres)


def test_contribution_source_de_l_annee_d_arrivee_reste_hors_perimetre(sa_sync_conn, rh_person):
    """Arrivée en septembre 2020 : une publication de 2020 a le plus souvent été écrite avant."""
    arrivee = _source_contribution(sa_sync_conn, publication_year=2020)

    sync_perimeter_evidence(sa_sync_conn, perimeter_ids=[])

    assert not _in_perimeter(sa_sync_conn, arrivee)


def test_orcid_d_une_source_non_fiable_ou_neutralise_ignore(sa_sync_conn, rh_person):
    wos = _source_contribution(sa_sync_conn, publication_year=2021, source="wos")
    neutralise = _source_contribution(
        sa_sync_conn, publication_year=2022, neutralized_identifiers={"orcid": "shared"}
    )

    sync_perimeter_evidence(sa_sync_conn, perimeter_ids=[])

    assert not _in_perimeter(sa_sync_conn, wos)
    assert not _in_perimeter(sa_sync_conn, neutralise)


def test_identifiant_en_attente_ignore(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Rh")
    insert_hr_record(sa_sync_conn, person, start_date=datetime.date(2020, 1, 1))
    insert_person_identifier(sa_sync_conn, person, id_type="orcid", id_value=_ORCID)
    source_contribution = _source_contribution(sa_sync_conn, publication_year=2021)

    sync_perimeter_evidence(sa_sync_conn, perimeter_ids=[])

    assert not _in_perimeter(sa_sync_conn, source_contribution)


def test_le_recalcul_apres_edition_d_adresse_garde_l_identite(sa_sync_conn, rh_person):
    source_contribution = _source_contribution(sa_sync_conn, publication_year=2021)

    SourceContributionPerimeterRecompute(sa_sync_conn).recompute_perimeter(
        [source_contribution], []
    )

    assert _in_perimeter(sa_sync_conn, source_contribution)
