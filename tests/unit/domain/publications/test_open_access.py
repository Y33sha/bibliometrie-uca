"""Statut open access déduit des accès constatés (`domain.publications.open_access`)."""

import pytest

from domain.platforms.platform import PlatformType
from domain.publications.access import Copy
from domain.publications.licenses import License
from domain.publications.open_access import OpenAccessFacts, copies_facts, decide_oa_status

_LICENSED = OpenAccessFacts(publisher_open=True, publisher_licensed=True, informed=True)


def _copy(url, *, is_oa=True, platform_type=None, licence=None) -> Copy:
    return Copy(
        url=url,
        version=None,
        is_oa=is_oa,
        platform=None,
        known_platform=None,
        platform_type=platform_type,
        license=licence,
        described_by_platform=False,
        arrival=1,
    )


@pytest.mark.parametrize(
    ("has_serial", "model", "expected"),
    [
        (True, "subscription", "hybrid"),
        (True, None, "hybrid"),
        (True, "full_oa", "gold"),
        (True, "diamond", "diamond"),
        (False, None, "gold"),
    ],
)
def test_copie_editeur_sous_licence_le_modele_de_la_revue_decide(has_serial, model, expected):
    assert decide_oa_status(_LICENSED, has_serial=has_serial, serial_oa_model=model) == expected


def test_green_passe_avant_bronze():
    facts = OpenAccessFacts(publisher_open=True, archive_open=True, informed=True)
    assert decide_oa_status(facts, has_serial=True, serial_oa_model="subscription") == "green"


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (OpenAccessFacts(publisher_open=True, informed=True), "bronze"),
        (OpenAccessFacts(embargoed=True, informed=True), "embargoed"),
        (OpenAccessFacts(informed=True), "closed"),
        (OpenAccessFacts(), "unknown"),
    ],
)
def test_sans_copie_editeur_sous_licence(facts, expected):
    assert decide_oa_status(facts, has_serial=True, serial_oa_model="full_oa") == expected


def test_le_modele_de_la_revue_seul_ne_donne_aucun_statut():
    assert decide_oa_status(OpenAccessFacts(), has_serial=True, serial_oa_model="diamond") == (
        "unknown"
    )


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [("gold", "gold"), ("bronze", "bronze"), ("green", "green"), ("closed", "closed")],
)
def test_le_verdict_d_unpaywall_releve(verdict, expected):
    facts = OpenAccessFacts().raised_by(verdict)
    assert decide_oa_status(facts, has_serial=True, serial_oa_model="full_oa") == expected


def test_le_verdict_d_unpaywall_n_abaisse_pas():
    facts = OpenAccessFacts(archive_open=True, informed=True).raised_by("closed")
    assert decide_oa_status(facts, has_serial=True, serial_oa_model=None) == "green"


def test_acces_constates_sur_les_copies():
    facts = copies_facts(
        [
            _copy("https://doi.org/10.1/x", licence=License.CC_BY),
            _copy("https://hal.science/hal-01607327", platform_type=PlatformType.REPOSITORY),
            _copy("https://example.org/fermee", is_oa=False),
        ]
    )
    assert facts == OpenAccessFacts(
        publisher_open=True, publisher_licensed=True, archive_open=True, informed=True
    )
