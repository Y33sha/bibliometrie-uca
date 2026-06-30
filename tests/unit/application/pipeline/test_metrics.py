"""Métriques de phase : `total` dérivé (≥ ventilation) et sérialisation."""

from application.pipeline.metrics import PhaseMetrics


def test_total_derives_from_breakdown_without_explicit_denominator():
    # Régression : un extracteur qui catégorise sans renseigner le dénominateur
    # (cas OpenAlex/WoS, qui faisaient diverger total < new+updated+unchanged)
    # reporte quand même total = somme catégorisée.
    m = PhaseMetrics()
    m.add(new=204)
    m.add(updated=3891)
    m.add(unchanged=19101)
    assert m.total == 204 + 3891 + 19101


def test_total_uses_explicit_denominator_when_larger():
    # cross_imports : `total=` (DOI interrogés) dépasse les catégorisés (insérés).
    m = PhaseMetrics()
    m.add(new=10, total=100)
    assert m.total == 100


def test_total_never_below_breakdown():
    # Même dénominateur sous-évalué, total ≥ catégorisés (le max() protège).
    m = PhaseMetrics(seen=2)
    m.add(new=5)
    assert m.total == 5


def test_merge_sums_denominator_and_breakdown():
    a = PhaseMetrics()
    a.add(new=1, total=3)
    b = PhaseMetrics()
    b.add(updated=2, total=4)
    a.merge(b)
    assert (a.new, a.updated) == (1, 2)
    assert a.total == 7  # seen 3+4, ≥ catégorisés 3


def test_to_payload():
    metrics = PhaseMetrics(new=3, updated=1)
    metrics.extras["tagged"] = 2
    assert metrics.to_payload(duration_s=12.5) == {
        "new": 3,
        "updated": 1,
        "unchanged": 0,
        "total": 4,
        "errors": 0,
        "extras": {"tagged": 2},
        "duration_s": 12.5,
    }
