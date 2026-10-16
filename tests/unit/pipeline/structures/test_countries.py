"""Orchestrateur de la phase `countries` : enchaînement des sous-étapes et entonnoir du bilan.

La phase encadre ses sous-étapes de deux bilans, et en tire un résumé : combien d'adresses manquaient de pays au départ, combien la passe en a rattaché, ce qui reste. Ce résumé est le propos de la phase — les sous-étapes, elles, ont leurs propres tests.
"""

from unittest.mock import patch

import pytest

from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.structures.countries import countries as phase
from pipeline.transformation.structures.countries.countries_queries import AddressCountryStatus


class _FakeCountryQueries:
    """Rend les bilans successifs posés à la construction : l'initial, puis le final."""

    def __init__(self, bilans: list[AddressCountryStatus]) -> None:
        self._bilans = list(bilans)
        self.bilans_demandes = 0

    def count_address_country_status(self, conn) -> AddressCountryStatus:
        self.bilans_demandes += 1
        return self._bilans.pop(0)

    def insert_ror_candidates(self, conn) -> int:
        return 2

    def resolve_address_countries(self, conn, address_ids=None) -> int:
        return 3


def _bilan(total: int, with_country: int) -> AddressCountryStatus:
    return AddressCountryStatus(total=total, with_country=with_country)


@pytest.fixture
def sous_etapes():
    """Neutralise les sous-étapes et retient l'appel du recalcul."""
    appels: dict[str, object] = {}
    with (
        patch.object(phase.detect_by_country_name, "run", return_value=PhaseMetrics(new=4)),
        patch.object(phase.detect_by_place_name, "run", return_value=PhaseMetrics(new=6)),
        patch.object(
            phase.refresh_publication_countries,
            "refresh",
            side_effect=lambda conn, q, log: appels.__setitem__("refresh", True),
        ),
    ):
        yield appels


def test_resume_l_entonnoir_des_bilans(contexte, sous_etapes):
    queries = _FakeCountryQueries([_bilan(100, 60), _bilan(100, 85)])

    metrics = phase.CountriesPhase(queries).run(contexte(mode="daily"))

    assert metrics.details["summary"] == {
        "total": 100,
        "without_initial": 40,
        "without_pct": 40.0,
        "newly_attached": 25,
        "remaining": 15,
    }


def test_cumule_les_metriques_des_sous_etapes(contexte, sous_etapes):
    queries = _FakeCountryQueries([_bilan(10, 5), _bilan(10, 9)])

    metrics = phase.CountriesPhase(queries).run(contexte(mode="daily"))

    assert metrics.new == 12  # 2 (ROR) + 4 (nom de pays) + 6 (nom de lieu)
    assert metrics.updated == 3  # adresses dont la résolution change le pays
    assert sous_etapes["refresh"] is True


def test_base_vide_sans_division_par_zero(contexte, sous_etapes):
    queries = _FakeCountryQueries([_bilan(0, 0), _bilan(0, 0)])

    metrics = phase.CountriesPhase(queries).run(contexte(mode="daily"))

    assert metrics.details["summary"]["without_pct"] == 0


def test_chaque_sous_etape_dans_sa_transaction(open_tx, contexte, sous_etapes):
    queries = _FakeCountryQueries([_bilan(10, 5), _bilan(10, 9)])

    phase.CountriesPhase(queries).run(contexte(mode="daily"))

    assert open_tx.transactions == 7  # deux bilans + cinq sous-étapes
