"""Lecture et normalisation d'une famille de brevets OPS (`pipeline.ingestion.ops.family`, `pipeline.ingestion.ops.normalize`), sur la réponse d'OPS pour la famille de la demande FR1658141."""

import json
from datetime import date
from pathlib import Path

import pytest

from pipeline.ingestion.ops.family import (
    DocId,
    Party,
    display_names,
    family_key,
    family_members,
    items,
)
from pipeline.ingestion.ops.harvest import family_document
from pipeline.ingestion.ops.normalize import (
    OpsNormalizer,
    build_inventor_records,
    espacenet_locations,
    get_publication_date,
    ops_source_record,
)

_BODY = json.loads((Path(__file__).parent / "family_FR1658141.json").read_text())


@pytest.fixture
def members():
    return family_members(_BODY)


@pytest.fixture
def record(members):
    return ops_source_record(family_document(_BODY, family_key(members) or ""), 1, "FR1658141")


def test_identifiant_et_date_de_la_priorite_la_plus_ancienne(members):
    assert family_key(members) == "FR1658141"
    publication_date = get_publication_date(members)
    assert publication_date is not None and publication_date.value == date(2016, 9, 1)


def test_numeros_de_publication_et_de_demande(record):
    """La demande internationale s'écrit sous l'office WO, sans office de dépôt."""
    numbers = {(i.id_type.value, i.value) for i in record.identifiers}
    assert numbers == {
        ("patent_publication_number", "FR3055338"),
        ("patent_publication_number", "WO2018041749"),
        ("patent_application_number", "FR1658141"),
        ("patent_application_number", "WO2017071490"),
    }


def test_titre_et_resume_en_francais(record):
    assert record.title.startswith("METHODE DE DETECTION")
    assert record.raw_language == "fr"
    assert record.abstract is not None and record.abstract.startswith("La présente invention")


def test_demandes_deposants_et_dates(record):
    extras = record.source_extras or {}
    applications = {a["office"]: a for a in extras["patent_applications"]}
    assert applications["FR"]["application_number"] == "1658141"
    assert applications["FR"]["publication_number"] == "3055338A1"
    assert applications["FR"]["priority"] is True
    assert applications["FR"]["granted"] is True
    assert applications["WO"]["priority"] is False
    assert extras["patent_first_publication_date"] == "2018-03-02"
    assert extras["patent_grant_date"] == "2020-05-29"
    assert {"name": "UNIVERSITE CLERMONT AUVERGNE"} in extras["patent_applicants"]
    assert {"univ clermont auvergne", "universite clermont auvergne"} <= set(
        extras["patent_applicant_forms"]
    )
    assert {"code": "C12Q1/6806"} in extras["cpc"]


def test_un_inventeur_par_nom(members):
    """OPS répète chaque inventeur à chaque publication et sous deux formats."""
    block = OpsNormalizer.author_block(
        OpsNormalizer.__new__(OpsNormalizer), family_document(_BODY, "FR1658141")
    )
    assert [r.name.raw for r in build_inventor_records(block)] == [
        "GASC, CYRIELLE",
        "DENONFOUX, JEREMIE",
        "PEYRETAILLADE, ERIC",
        "PEYRET, PIERRE",
    ]


def test_copie_espacenet_de_la_demande_prioritaire(members):
    (location,) = espacenet_locations(members)
    assert location.url == "https://worldwide.espacenet.com/patent/search?q=pn%3D%22FR3055338A1%22"


def test_noeud_seul_lu_comme_une_liste():
    assert items({"a": 1}) == [{"a": 1}]
    assert items([{"a": 1}, {"a": 2}]) == [{"a": 1}, {"a": 2}]
    assert items(None) == []


def test_demande_internationale_sous_l_office_wo():
    assert DocId("FR", "2017051773", "W", None).identifier == "WO2017051773"
    assert DocId("EP", "17745411", "A", None).identifier == "EP17745411"


def test_demande_americaine_publiee_sans_le_zero_qui_suit_l_annee():
    """OPS écrit `20240211607` depuis 2023 et `2020208181` avant : les deux formes donnent le même numéro."""
    assert DocId("US", "20240211607", "A1", None).identifier == "US2024211607"
    assert DocId("US", "2020208181", "A1", None).identifier == "US2020208181"
    assert DocId("US", "11198814", "B2", None).identifier == "US11198814"


def test_graphie_nom_virgule_prenom_preferee():
    parties = [
        Party("DENONFOUX JEREMIE", True),
        Party("DENONFOUX, Jérémie", True),
        Party("DENONFOUX JEREMIE [FR]", False),
    ]
    assert display_names(parties) == ["DENONFOUX, Jérémie"]
